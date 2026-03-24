import logging
import mimetypes
import shutil
import sys
import httpx

from pathlib import Path
from typing import Dict, Union, Literal, List, Optional

from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Request
from fastapi.responses import PlainTextResponse, FileResponse, JSONResponse

WORKSPACE = Path("/home/user")


def resolve(path: str) -> Path:
    """Resolve a workspace-relative POSIX path, rejecting traversal outside WORKSPACE."""
    resolved = (WORKSPACE / path).resolve()
    if not str(resolved).startswith(str(WORKSPACE)):
        raise ValueError(f"Path outside workspace: {path}")
    return resolved

from api.models.context import Context
from api.models.create_context import CreateContext
from api.models.execution_request import ExecutionRequest
from consts import JUPYTER_BASE_URL
from contexts import create_context, normalize_language
from messaging import ContextWebSocket
from stream import StreamingListJsonResponse
from utils.locks import LockedMap

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
logger = logging.Logger(__name__)
http_logger = logging.getLogger("httpcore.http11")
http_logger.setLevel(logging.WARNING)


websockets: Dict[Union[str, Literal["default"]], ContextWebSocket] = {}
default_websockets = LockedMap()
global client


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    client = httpx.AsyncClient()

    try:
        python_context = await create_context(
            client, websockets, "python", "/home/user"
        )
        default_websockets["python"] = python_context.id
        websockets["default"] = websockets[python_context.id]

        logger.info("Connected to default runtime")
        yield

        for ws in websockets.values():
            await ws.close()

        await client.aclose()
    except Exception as e:
        logger.error(f"Failed to initialize default context: {e}")
        raise


app = FastAPI(lifespan=lifespan)

logger.info("Starting Code Interpreter server")


@app.get("/health")
async def get_health():
    return "OK"


@app.post("/execute")
async def post_execute(exec_request: ExecutionRequest):
    logger.info(f"Executing code: {exec_request.code}")

    if exec_request.context_id and exec_request.language:
        return PlainTextResponse(
            "Only one of context_id or language can be provided",
            status_code=400,
        )

    context_id = None
    if exec_request.language:
        language = normalize_language(exec_request.language)

        async with await default_websockets.get_lock(language):
            context_id = default_websockets.get(language)

            if not context_id:
                try:
                    context = await create_context(
                        client, websockets, language, "/home/user"
                    )
                except Exception as e:
                    return PlainTextResponse(str(e), status_code=500)

                context_id = context.id
                default_websockets[language] = context_id

    elif exec_request.context_id:
        context_id = exec_request.context_id

    if context_id:
        ws = websockets.get(context_id, None)
    else:
        ws = websockets["default"]

    if not ws:
        return PlainTextResponse(
            f"Context {exec_request.context_id} not found",
            status_code=404,
        )

    return StreamingListJsonResponse(
        ws.execute(
            exec_request.code,
            env_vars=exec_request.env_vars,
        )
    )


@app.post("/contexts")
async def post_contexts(request: CreateContext) -> Context:
    logger.info("Creating a new context")

    language = normalize_language(request.language)
    cwd = request.cwd or "/home/user"

    try:
        return await create_context(client, websockets, language, cwd)
    except Exception as e:
        return PlainTextResponse(str(e), status_code=500)


@app.get("/contexts")
async def get_contexts() -> List[Context]:
    logger.info("Listing contexts")

    return [
        Context(
            id=ws.context_id,
            language=ws.language,
            cwd=ws.cwd,
        )
        for key, ws in websockets.items()
        if key != "default"
    ]


@app.post("/contexts/{context_id}/restart")
async def restart_context(context_id: str) -> None:
    logger.info(f"Restarting context {context_id}")

    ws = websockets.get(context_id, None)
    if not ws:
        return PlainTextResponse(
            f"Context {context_id} not found",
            status_code=404,
        )

    session_id = ws.session_id

    await ws.close()

    response = await client.post(
        f"{JUPYTER_BASE_URL}/api/kernels/{ws.context_id}/restart"
    )
    if not response.is_success:
        return PlainTextResponse(
            f"Failed to restart context {context_id}",
            status_code=500,
        )

    ws = ContextWebSocket(
        ws.context_id,
        session_id,
        ws.language,
        ws.cwd,
    )

    await ws.connect()

    websockets[context_id] = ws


@app.delete("/contexts/{context_id}")
async def remove_context(context_id: str) -> None:
    logger.info(f"Removing context {context_id}")

    ws = websockets.get(context_id, None)
    if not ws:
        return PlainTextResponse(
            f"Context {context_id} not found",
            status_code=404,
        )

    try:
        await ws.close()
    except:  # noqa: E722
        pass

    response = await client.delete(f"{JUPYTER_BASE_URL}/api/kernels/{ws.context_id}")
    if not response.is_success:
        return PlainTextResponse(
            f"Failed to remove context {context_id}",
            status_code=500,
        )

    del websockets[context_id]


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

@app.get("/files")
async def list_files(path: Optional[str] = Query(default=".")):
    try:
        target = resolve(path)
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=400)

    if not target.exists():
        return PlainTextResponse(f"Not found: {path}", status_code=404)
    if not target.is_dir():
        return PlainTextResponse(f"Not a directory: {path}", status_code=400)

    entries = [
        {
            "name": entry.name,
            "type": "dir" if entry.is_dir() else "file",
            "size": entry.stat().st_size if entry.is_file() else None,
            "modified": entry.stat().st_mtime,
        }
        for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name))
    ]
    return JSONResponse({"path": path, "entries": entries})


@app.get("/files/{path:path}")
async def download_file(path: str):
    try:
        target = resolve(path)
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=400)

    if not target.exists():
        return PlainTextResponse(f"Not found: {path}", status_code=404)
    if target.is_dir():
        return PlainTextResponse(f"Is a directory: {path}", status_code=400)

    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(target, media_type=media_type or "application/octet-stream")


@app.put("/files/{path:path}")
async def upload_file(path: str, request: Request):
    try:
        target = resolve(path)
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=400)

    target.parent.mkdir(parents=True, exist_ok=True)
    created = not target.exists()
    target.write_bytes(await request.body())
    return PlainTextResponse("", status_code=201 if created else 200)


@app.delete("/files/{path:path}")
async def delete_file(path: str):
    try:
        target = resolve(path)
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=400)

    if not target.exists():
        return PlainTextResponse(f"Not found: {path}", status_code=404)

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    return PlainTextResponse("", status_code=204)

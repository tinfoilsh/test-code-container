import json
from typing import Mapping, Optional, AsyncIterable

from fastapi.encoders import jsonable_encoder
from starlette.background import BackgroundTask
from fastapi.responses import StreamingResponse


class StreamingListJsonResponse(StreamingResponse):
    """Streams execution results as newline-delimited JSON."""

    def __init__(
        self,
        content_generator: AsyncIterable,
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        media_type: Optional[str] = None,
        background: Optional[BackgroundTask] = None,
    ) -> None:
        super().__init__(
            content=self._encoded_async_generator(content_generator),
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )

    async def _encoded_async_generator(self, async_generator: AsyncIterable):
        async for item in async_generator:
            yield f"{json.dumps(jsonable_encoder(item))}\n"
        yield '{"type": "end_of_execution"}\n'

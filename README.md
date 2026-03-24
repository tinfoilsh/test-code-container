# code-interpreter

A containerised Python execution engine. Send code over HTTP, get back streaming results — stdout, rich output, errors — exactly like executing cells in a Jupyter notebook.

Derived from [e2b-dev/code-interpreter](https://github.com/e2b-dev/code-interpreter).

---

## How it works

Two processes run inside the container:

- **Jupyter Server** (port 8888, internal) — manages Python kernel processes. Each kernel is a separate OS process with its own memory space.
- **FastAPI server** (port 49999, exposed) — the HTTP API. It holds a persistent WebSocket connection to each kernel and speaks the [Jupyter wire protocol](https://jupyter-client.readthedocs.io/en/stable/messaging.html) internally.

When you `POST /execute`, the server sends an `execute_request` over the kernel's WebSocket and streams back whatever the kernel emits — stdout, expression results, display data (images, HTML, etc.), errors — as newline-delimited JSON.

State is **persistent across calls** within a context. Variables, imports, and side effects from one execution are visible in the next, exactly like notebook cells.

### Isolation

Each context is a separate Python process. Kernels do not share memory or module state. They do share the container filesystem, network namespace, and system resources — there is no per-kernel resource quota. For user-level isolation, run one container per user.

---

## Repository layout

```
Dockerfile                  # Image definition
start-up.sh                 # Entrypoint: starts Jupyter then the FastAPI server
jupyter-healthcheck.sh      # Polls :8888/api/status before starting the API server
jupyter_server_config.py    # Jupyter: allow_origin=*, no token, allow_root
ipython_kernel_config.py    # IPython: unlimited sequence output
server/
  main.py                   # FastAPI app, route handlers, lifespan
  messaging.py              # ContextWebSocket — WebSocket lifecycle, execution, streaming
  contexts.py               # create_context() — creates Jupyter session + WebSocket
  consts.py                 # JUPYTER_BASE_URL
  stream.py                 # StreamingListJsonResponse — newline-delimited JSON
  errors.py                 # ExecutionError
  api/models/               # Pydantic models for all request/response types
  utils/locks.py            # LockedMap — per-key async locks
tests/
  test_api.py               # Integration tests (requires container on :49999)
```

---

## Build & run

```bash
docker build -t code-interpreter .
docker run -p 49999:49999 code-interpreter
```

---

## API

All endpoints are on port `49999`. Execution results stream as **newline-delimited JSON** — one object per line, terminated by `{"type": "end_of_execution"}`.

### `GET /health`

Returns `"OK"` when the server is up.

---

### `POST /execute`

Execute Python code. Streams results back as newline-delimited JSON.

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `code` | string | yes | Code to execute |
| `context_id` | string | no | Run in a specific context |
| `language` | string | no | Run in the default context for this language |
| `env_vars` | object | no | Environment variables to inject for this execution only |

`context_id` and `language` are mutually exclusive. Omit both to use the default Python context.

**Example:**

```bash
curl -X POST http://localhost:49999/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "print(\"hello\")"}'
```

**Response stream:**

Each line is one of:

```jsonc
// Execution counter (first message)
{"type": "number_of_executions", "execution_count": 1}

// Standard output
{"type": "stdout", "text": "hello\n", "timestamp": "2024-01-01T00:00:00Z"}

// Standard error
{"type": "stderr", "text": "...", "timestamp": "2024-01-01T00:00:00Z"}

// Expression result or display output (images, HTML, etc.)
// is_main_result=true for the cell's return value, false for display() calls
{
  "type": "result",
  "is_main_result": true,
  "text": "42",
  "html": null,
  "png": "<base64>",   // e.g. matplotlib figures
  "svg": null,
  "jpeg": null,
  "pdf": null,
  "markdown": null,
  "latex": null,
  "json": null,
  "javascript": null
}

// Execution error
{"type": "error", "name": "ZeroDivisionError", "value": "division by zero", "traceback": "..."}

// Always the final message
{"type": "end_of_execution"}
```

**Error responses:**

| Status | Condition |
|---|---|
| `400` | Both `context_id` and `language` provided |
| `404` | `context_id` not found |

---

### `POST /contexts`

Create a new isolated Python kernel.

**Request body:**

| Field | Type | Default | Description |
|---|---|---|---|
| `language` | string | `"python"` | Kernel language |
| `cwd` | string | `"/home/user"` | Working directory |

**Response:**

```json
{"id": "<uuid>", "language": "python", "cwd": "/home/user"}
```

---

### `GET /contexts`

List all active contexts.

**Response:**

```json
[
  {"id": "<uuid>", "language": "python", "cwd": "/home/user"}
]
```

---

### `POST /contexts/{context_id}/restart`

Restart the kernel for a context. All state is wiped.

---

### `DELETE /contexts/{context_id}`

Shut down and remove a context.

---

## Tests

Tests are integration tests — they require the container to be running on `localhost:49999`.

```bash
pip install pytest requests
pytest tests/test_api.py -v
```

The suite covers: health, stdout/stderr, expression results, rich output (matplotlib PNG), syntax and runtime errors, state persistence across calls, env var injection and cleanup, context creation/isolation/deletion/restart, and error handling (404, 400).

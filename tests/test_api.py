"""
Integration tests for the code-interpreter HTTP API.
Requires the container to be running on localhost:49999.

    docker run -p 49999:49999 code-interpreter
    pytest tests/test_api.py -v
"""
import json
import time
import pytest
import requests

BASE = "http://localhost:49999"


def wait_for_server(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)
    raise RuntimeError("Server did not become healthy in time")


def execute(code, **kwargs):
    """POST /execute and return the list of streamed objects."""
    payload = {"code": code, **kwargs}
    r = requests.post(f"{BASE}/execute", json=payload, stream=True, timeout=30)
    r.raise_for_status()
    return [json.loads(line) for line in r.iter_lines() if line]


@pytest.fixture(scope="session", autouse=True)
def server_ready():
    wait_for_server()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------

def test_stdout():
    items = execute("print('hello')")
    types = [i["type"] for i in items]
    assert "stdout" in types
    stdout = next(i for i in items if i["type"] == "stdout")
    assert stdout["text"] == "hello\n"
    assert types[-1] == "end_of_execution"


def test_expression_result():
    items = execute("1 + 1")
    result = next((i for i in items if i["type"] == "result"), None)
    assert result is not None
    assert result["text"] == "2"
    assert result["is_main_result"] is True


def test_multiline():
    items = execute("x = 10\ny = 20\nprint(x + y)")
    stdout = next(i for i in items if i["type"] == "stdout")
    assert stdout["text"] == "30\n"


def test_stderr():
    items = execute("import sys; print('err', file=sys.stderr)")
    types = [i["type"] for i in items]
    assert "stderr" in types
    stderr = next(i for i in items if i["type"] == "stderr")
    assert "err" in stderr["text"]


def test_syntax_error():
    items = execute("def foo(")
    types = [i["type"] for i in items]
    assert "error" in types
    err = next(i for i in items if i["type"] == "error")
    # Python 3.13 raises _IncompleteInputError (subclass of SyntaxError)
    assert "SyntaxError" in err["name"] or "IncompleteInputError" in err["name"]


def test_runtime_error():
    items = execute("1 / 0")
    err = next((i for i in items if i["type"] == "error"), None)
    assert err is not None
    assert "ZeroDivisionError" in err["name"]
    assert err["traceback"] != ""


def test_always_ends():
    """Every execution must finish with end_of_execution."""
    for code in ["print('ok')", "1/0", "x = 42"]:
        items = execute(code)
        assert items[-1]["type"] == "end_of_execution"


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def test_state_persists_across_calls():
    execute("counter = 0")
    execute("counter += 1")
    items = execute("print(counter)")
    stdout = next(i for i in items if i["type"] == "stdout")
    assert stdout["text"] == "1\n"


def test_imports_persist():
    execute("import math")
    items = execute("print(math.pi)")
    stdout = next(i for i in items if i["type"] == "stdout")
    assert stdout["text"].startswith("3.14")


# ---------------------------------------------------------------------------
# env_vars
# ---------------------------------------------------------------------------

def test_env_vars_injected():
    items = execute(
        "import os; print(os.environ['MY_VAR'])",
        env_vars={"MY_VAR": "hello_env"},
    )
    stdout = next(i for i in items if i["type"] == "stdout")
    assert stdout["text"] == "hello_env\n"


def test_env_vars_cleaned_up():
    execute("x = 1", env_vars={"TEMP_VAR": "temp"})
    # give cleanup task a moment to run
    time.sleep(0.3)
    items = execute("import os; print(os.environ.get('TEMP_VAR', 'gone'))")
    stdout = next(i for i in items if i["type"] == "stdout")
    assert stdout["text"] == "gone\n"


# ---------------------------------------------------------------------------
# Contexts
# ---------------------------------------------------------------------------

def test_list_contexts():
    r = requests.get(f"{BASE}/contexts")
    assert r.status_code == 200
    contexts = r.json()
    assert isinstance(contexts, list)
    assert len(contexts) >= 1
    assert all("id" in c and "language" in c and "cwd" in c for c in contexts)


def test_create_and_use_context():
    r = requests.post(f"{BASE}/contexts", json={"language": "python", "cwd": "/tmp"})
    assert r.status_code == 200
    ctx = r.json()
    assert ctx["language"] == "python"
    assert ctx["cwd"] == "/tmp"

    # isolated from default context
    execute("secret = 42")  # set in default
    items = execute("print(secret)", context_id=ctx["id"])
    types = [i["type"] for i in items]
    assert "error" in types  # NameError — not visible in new context


def test_context_isolation():
    r1 = requests.post(f"{BASE}/contexts", json={"language": "python"})
    r2 = requests.post(f"{BASE}/contexts", json={"language": "python"})
    ctx1, ctx2 = r1.json()["id"], r2.json()["id"]

    execute("val = 'ctx1'", context_id=ctx1)
    execute("val = 'ctx2'", context_id=ctx2)

    items1 = execute("print(val)", context_id=ctx1)
    items2 = execute("print(val)", context_id=ctx2)

    out1 = next(i for i in items1 if i["type"] == "stdout")["text"]
    out2 = next(i for i in items2 if i["type"] == "stdout")["text"]
    assert out1 == "ctx1\n"
    assert out2 == "ctx2\n"


def test_delete_context():
    r = requests.post(f"{BASE}/contexts", json={"language": "python"})
    ctx_id = r.json()["id"]

    del_r = requests.delete(f"{BASE}/contexts/{ctx_id}")
    assert del_r.status_code == 200

    contexts = requests.get(f"{BASE}/contexts").json()
    assert not any(c["id"] == ctx_id for c in contexts)


def test_restart_context():
    r = requests.post(f"{BASE}/contexts", json={"language": "python"})
    ctx_id = r.json()["id"]

    execute("x = 99", context_id=ctx_id)
    requests.post(f"{BASE}/contexts/{ctx_id}/restart")
    time.sleep(1)  # let kernel come back up

    items = execute("print(x)", context_id=ctx_id)
    types = [i["type"] for i in items]
    assert "error" in types  # x was wiped


def test_missing_context():
    r = requests.post(
        f"{BASE}/execute",
        json={"code": "print(1)", "context_id": "does-not-exist"},
        stream=True,
    )
    assert r.status_code == 404


def test_context_id_and_language_mutually_exclusive():
    r = requests.post(
        f"{BASE}/execute",
        json={"code": "1", "context_id": "x", "language": "python"},
        stream=True,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Rich output
# ---------------------------------------------------------------------------

def test_matplotlib_png():
    code = (
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots()\n"
        "ax.plot([1,2,3])\n"
        "plt.show()\n"
    )
    items = execute(code)
    result = next((i for i in items if i["type"] == "result"), None)
    assert result is not None
    assert result.get("png") is not None


def test_number_of_executions():
    items = execute("42")
    num = next((i for i in items if i["type"] == "number_of_executions"), None)
    assert num is not None
    assert isinstance(num["execution_count"], int)

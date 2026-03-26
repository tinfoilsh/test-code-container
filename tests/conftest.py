import time
import pytest
import requests

BASE = "http://localhost:49999"


def _wait_for_server(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{BASE}/health", timeout=2).status_code == 200:
                return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)
    raise RuntimeError("Server did not become healthy in time")


@pytest.fixture(scope="session")
def auth_headers():
    _wait_for_server()
    r = requests.post(f"{BASE}/claim", timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}

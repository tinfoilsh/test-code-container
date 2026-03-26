"""
Integration tests for the file API.
Requires the container to be running on localhost:49999.
"""
import pytest
import requests

BASE = "http://localhost:49999"
HEADERS = {}


def put(path, data=b""):
    return requests.put(f"{BASE}/files/{path}", data=data, headers=HEADERS)

def get(path):
    return requests.get(f"{BASE}/files/{path}", headers=HEADERS)

def delete(path):
    return requests.delete(f"{BASE}/files/{path}", headers=HEADERS)

def ls(path=None):
    url = f"{BASE}/files"
    if path:
        url += f"?path={path}"
    return requests.get(url, headers=HEADERS)


@pytest.fixture(scope="session", autouse=True)
def server_ready(auth_headers):
    HEADERS.update(auth_headers)


# ---------------------------------------------------------------------------
# PUT — create
# ---------------------------------------------------------------------------

def test_put_new_file_returns_201():
    assert put("new_file.txt", b"hi").status_code == 201

def test_put_empty_file():
    r = put("empty.txt", b"")
    assert r.status_code == 201
    assert get("empty.txt").content == b""

def test_put_creates_intermediate_dirs():
    assert put("x/y/z/deep.txt", b"deep").status_code == 201

def test_put_binary_roundtrip():
    data = bytes(range(256))
    put("binary.bin", data)
    assert get("binary.bin").content == data

def test_put_unicode_content():
    data = "héllo wörld 🌍".encode()
    put("unicode.txt", data)
    assert get("unicode.txt").content == data

def test_put_large_file():
    data = b"x" * 10 * 1024 * 1024  # 10 MB
    put("large.bin", data)
    assert get("large.bin").content == data


# ---------------------------------------------------------------------------
# PUT — overwrite
# ---------------------------------------------------------------------------

def test_put_overwrite_returns_200():
    put("ow.txt", b"v1")
    assert put("ow.txt", b"v2").status_code == 200

def test_put_overwrite_content_is_replaced():
    put("replace.txt", b"original content")
    put("replace.txt", b"new")
    assert get("replace.txt").content == b"new"

def test_put_overwrite_shorter_no_trailing_bytes():
    put("trunc.txt", b"longcontent")
    put("trunc.txt", b"short")
    assert get("trunc.txt").content == b"short"

def test_put_delete_put_returns_201_again():
    put("cycle.txt", b"a")
    delete("cycle.txt")
    assert put("cycle.txt", b"b").status_code == 201


# ---------------------------------------------------------------------------
# GET /files/{path} — download
# ---------------------------------------------------------------------------

def test_download_text_content():
    put("dl.txt", b"hello world")
    assert get("dl.txt").content == b"hello world"

def test_download_nested_path():
    put("dir/sub/nested.txt", b"nested")
    assert get("dir/sub/nested.txt").content == b"nested"

def test_download_missing_returns_404():
    assert get("no_such_file.txt").status_code == 404

def test_download_directory_returns_400():
    put("adir/placeholder.txt", b"x")
    assert get("adir").status_code == 400

def test_download_content_type_png():
    put("img.png", b"\x89PNG\r\n\x1a\n")
    assert "image/png" in get("img.png").headers["content-type"]

def test_download_content_type_json():
    put("data.json", b'{"k":1}')
    assert "json" in get("data.json").headers["content-type"]

def test_download_content_type_html():
    put("page.html", b"<html/>")
    assert "html" in get("page.html").headers["content-type"]

def test_download_content_type_csv():
    put("data.csv", b"a,b\n1,2")
    ct = get("data.csv").headers["content-type"]
    assert "csv" in ct or "text" in ct

def test_download_unknown_extension_octet_stream():
    put("file.xyz", b"data")
    assert "octet-stream" in get("file.xyz").headers["content-type"]


# ---------------------------------------------------------------------------
# GET /files — list
# ---------------------------------------------------------------------------

def test_list_default_returns_workspace():
    r = ls()
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body and "path" in body

def test_list_explicit_dot():
    r = ls(".")
    assert r.status_code == 200

def test_list_multiple_files_all_appear():
    put("multi/a.txt", b"a")
    put("multi/b.txt", b"b")
    put("multi/c.txt", b"c")
    names = {e["name"] for e in ls("multi").json()["entries"]}
    assert {"a.txt", "b.txt", "c.txt"}.issubset(names)

def test_list_file_entry_shape():
    put("shaped.txt", b"hello")
    entry = next(e for e in ls().json()["entries"] if e["name"] == "shaped.txt")
    assert entry["type"] == "file"
    assert entry["size"] == 5
    assert isinstance(entry["modified"], float)

def test_list_directory_entry_shape():
    put("listed_dir/f.txt", b"x")
    entry = next(e for e in ls().json()["entries"] if e["name"] == "listed_dir")
    assert entry["type"] == "dir"
    assert entry["size"] is None

def test_list_dirs_appear_before_files():
    # our impl sorts dirs first
    put("ordered/file.txt", b"x")
    put("ordered/subdir/f.txt", b"x")
    entries = ls("ordered").json()["entries"]
    types = [e["type"] for e in entries]
    last_dir = max(i for i, t in enumerate(types) if t == "dir")
    first_file = min(i for i, t in enumerate(types) if t == "file")
    assert last_dir < first_file

def test_list_nested_directory():
    put("deep/a/b/c.txt", b"x")
    r = ls("deep/a/b")
    assert r.status_code == 200
    assert any(e["name"] == "c.txt" for e in r.json()["entries"])

def test_list_empty_directory():
    # create dir by putting a file then deleting it
    put("emptydir/tmp.txt", b"x")
    delete("emptydir/tmp.txt")
    r = ls("emptydir")
    assert r.status_code == 200
    assert r.json()["entries"] == []

def test_list_missing_dir_returns_404():
    assert ls("no_such_dir").status_code == 404

def test_list_file_path_returns_400():
    put("notadir.txt", b"x")
    assert ls("notadir.txt").status_code == 400


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

def test_delete_file_returns_204():
    put("del.txt", b"x")
    assert delete("del.txt").status_code == 204

def test_delete_file_no_longer_downloadable():
    put("gone.txt", b"x")
    delete("gone.txt")
    assert get("gone.txt").status_code == 404

def test_delete_file_removed_from_listing():
    put("listed_then_gone.txt", b"x")
    delete("listed_then_gone.txt")
    names = [e["name"] for e in ls().json()["entries"]]
    assert "listed_then_gone.txt" not in names

def test_delete_directory_removes_all_children():
    put("treedir/a.txt", b"a")
    put("treedir/sub/b.txt", b"b")
    delete("treedir")
    assert get("treedir/a.txt").status_code == 404
    assert get("treedir/sub/b.txt").status_code == 404

def test_delete_directory_removed_from_listing():
    put("rmdir/f.txt", b"x")
    delete("rmdir")
    names = [e["name"] for e in ls().json()["entries"]]
    assert "rmdir" not in names

def test_delete_missing_returns_404():
    assert delete("ghost.txt").status_code == 404

def test_delete_nested_file():
    put("nest/deep/file.txt", b"x")
    assert delete("nest/deep/file.txt").status_code == 204
    assert get("nest/deep/file.txt").status_code == 404


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------

def test_full_crud_cycle():
    # create
    assert put("crud.txt", b"v1").status_code == 201
    assert get("crud.txt").content == b"v1"
    # update
    assert put("crud.txt", b"v2").status_code == 200
    assert get("crud.txt").content == b"v2"
    # list
    assert any(e["name"] == "crud.txt" for e in ls().json()["entries"])
    # delete
    assert delete("crud.txt").status_code == 204
    assert get("crud.txt").status_code == 404
    assert not any(e["name"] == "crud.txt" for e in ls().json()["entries"])

def test_put_list_delete_list():
    put("seq/one.txt", b"1")
    put("seq/two.txt", b"2")
    names = {e["name"] for e in ls("seq").json()["entries"]}
    assert "one.txt" in names and "two.txt" in names

    delete("seq/one.txt")
    names = {e["name"] for e in ls("seq").json()["entries"]}
    assert "one.txt" not in names
    assert "two.txt" in names

def test_nested_dir_structure_create_list_delete():
    put("proj/src/main.py", b"code")
    put("proj/src/utils.py", b"utils")
    put("proj/data/input.csv", b"a,b")

    # src and data appear in proj listing
    proj_names = {e["name"] for e in ls("proj").json()["entries"]}
    assert {"src", "data"}.issubset(proj_names)

    # files appear in subdirs
    src_names = {e["name"] for e in ls("proj/src").json()["entries"]}
    assert {"main.py", "utils.py"}.issubset(src_names)

    # delete subtree
    delete("proj")
    assert ls("proj").status_code == 404


# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------

def test_traversal_via_dotdot():
    assert get("../../etc/passwd").status_code in (400, 404)

def test_traversal_via_absolute_path():
    # FastAPI strips leading slash in path params, but verify safe outcome
    r = requests.get(f"{BASE}/files//etc/passwd", headers=HEADERS)
    assert r.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Integration — kernel writes, API reads
# ---------------------------------------------------------------------------

def test_kernel_write_text_file():
    requests.post(f"{BASE}/execute",
        json={"code": "open('/home/user/out.txt','w').write('from kernel')"},
        stream=True, headers=HEADERS).content
    assert get("out.txt").content == b"from kernel"

def test_kernel_write_csv():
    code = "import csv\nwith open('/home/user/data.csv','w') as f:\n    csv.writer(f).writerows([[1,2],[3,4]])\n"
    requests.post(f"{BASE}/execute", json={"code": code}, stream=True, headers=HEADERS).content
    r = get("data.csv")
    assert r.status_code == 200
    assert b"1,2" in r.content

def test_kernel_savefig_png():
    code = (
        "import matplotlib.pyplot as plt\n"
        "fig,ax=plt.subplots()\nax.plot([1,2,3])\n"
        "fig.savefig('/home/user/chart.png')\n"
    )
    requests.post(f"{BASE}/execute", json={"code": code}, stream=True, headers=HEADERS).content
    r = get("chart.png")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

def test_api_write_kernel_reads():
    put("input.txt", b"hello from api")
    code = "print(open('/home/user/input.txt').read())"
    items = []
    r = requests.post(f"{BASE}/execute", json={"code": code}, stream=True, headers=HEADERS)
    import json
    for line in r.iter_lines():
        if line:
            items.append(json.loads(line))
    stdout = next(i for i in items if i["type"] == "stdout")
    assert "hello from api" in stdout["text"]

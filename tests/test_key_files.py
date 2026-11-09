"""Agent 类 key 存成 .speclock/keys/ 里的文件：明文不经过响应、人类 key 不落盘、吊销删文件、MCP 读文件。"""

from __future__ import annotations

import json

import pytest

from speclock import home, keyfiles


@pytest.fixture()
def kh(env, tmp_path, monkeypatch):
    h = tmp_path / ".speclock"
    home.write_home(h, 8000)
    monkeypatch.setenv("SPECLOCK_HOME", str(h))
    return h


def _create(env, role, label="qa"):
    return env["client"].post("/api/v1/keys", json={"role": role, "label": label, "via": "cli"},
                              headers=env["human"])


def test_agent_key_is_saved_to_a_file_and_not_returned(env, kh):
    r = _create(env, "tester-agent", "QA 测试")
    assert r.status_code == 201
    body = r.json()
    assert "key" not in body and body["key_file"].startswith("tester-agent--") and body["key_file"].endswith(".key")
    saved = (kh / "keys" / body["key_file"]).read_text(encoding="utf-8").strip()
    assert saved.startswith("agent-")
    # 保存下来的 key 真的能用
    assert env["client"].get("/api/v1/me", headers={"X-API-Key": saved}).json()["role"] == "tester-agent"
    # 列表里只给文件名，不给内容
    rows = env["client"].get("/api/v1/keys", headers=env["human"]).json()
    assert [k["key_file"] for k in rows if k["id"] == body["id"]] == [body["key_file"]]
    assert saved not in json.dumps(rows)


def test_keys_folder_has_a_readme_and_is_ignored_by_git(env, kh):
    _create(env, "executor-agent")
    d = kh / "keys"
    assert "不要打开" in (d / "README.md").read_text(encoding="utf-8")
    assert (d / ".gitignore").read_text(encoding="utf-8").strip() == "*.key"


def test_human_keys_are_never_written_to_disk(env, kh):
    r = _create(env, "reviewer", "me")
    assert r.json()["key"].startswith("human-") and r.json()["key_file"] == ""
    assert not list((kh / "keys").glob("*.key")) if (kh / "keys").exists() else True


def test_same_label_does_not_overwrite_another_key(env, kh):
    a = _create(env, "tester-agent", "qa").json()
    b = _create(env, "tester-agent", "qa").json()
    assert a["key_file"] != b["key_file"]
    assert len(list((kh / "keys").glob("*.key"))) == 2


def test_revoking_a_key_deletes_its_file(env, kh):
    made = _create(env, "scanner-agent", "scan").json()
    path = kh / "keys" / made["key_file"]
    assert path.is_file()
    assert env["client"].delete(f"/api/v1/keys/{made['id']}", headers=env["human"]).status_code == 200
    assert not path.exists()


def test_without_a_speclock_dir_the_plaintext_is_returned_as_before(env):
    r = _create(env, "tester-agent")
    assert r.json()["key"].startswith("agent-") and r.json()["key_file"] == ""


def test_read_key_accepts_names_and_paths(kh):
    keyfiles.ensure_keys_dir(kh)
    (kh / "keys" / "x--y.key").write_text("agent-abc\n", encoding="utf-8")
    assert keyfiles.read_key("x--y.key", kh) == "agent-abc"
    assert keyfiles.read_key("x--y", kh) == "agent-abc"
    assert keyfiles.read_key(str(kh / "keys" / "x--y.key")) == "agent-abc"
    with pytest.raises(FileNotFoundError):
        keyfiles.read_key("nope", kh)
    (kh / "keys" / "empty.key").write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError):
        keyfiles.read_key("empty", kh)


def test_mcp_can_switch_to_a_key_file_and_keeps_identity_on_a_bad_file(env, kh, monkeypatch):
    from speclock import mcp_server

    c = env["client"]

    def fake_request(method, url, headers=None, timeout=None, **kw):
        return c.request(method, url.removeprefix(mcp_server.BASE_URL), headers=headers, **kw)

    admin = env["human"]["X-API-Key"]
    monkeypatch.setattr(mcp_server.httpx, "request", fake_request)
    monkeypatch.setattr(mcp_server, "CONFIGURED_KEY", admin)
    monkeypatch.setattr(mcp_server, "AGENT_KEY", admin)
    made = json.loads(mcp_server.create_api_key("tester-agent", "qa", evidence="同意，建一把测试用的"))
    assert "key" not in made["body"] and made["body"]["key_file"]
    out = json.loads(mcp_server.use_api_key(key_file=made["body"]["key_file"]))
    assert out["switched"] is True and out["identity"]["role"] == "tester-agent"
    bad = json.loads(mcp_server.use_api_key(key_file="不存在的文件"))
    assert "error" in bad
    assert json.loads(mcp_server.whoami())["body"]["role"] == "tester-agent"  # 失败后身份不变


def test_mcp_configured_key_can_come_from_a_key_file(kh, monkeypatch):
    from speclock import mcp_server

    keyfiles.ensure_keys_dir(kh)
    (kh / "keys" / "a--b.key").write_text("agent-from-file\n", encoding="utf-8")
    monkeypatch.delenv("SPECLOCK_KEY", raising=False)
    monkeypatch.setenv("SPECLOCK_KEY_FILE", "a--b.key")
    assert mcp_server._configured_key() == "agent-from-file"
    monkeypatch.setenv("SPECLOCK_KEY_FILE", "missing.key")
    assert mcp_server._configured_key() == ""

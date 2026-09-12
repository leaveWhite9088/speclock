"""密钥管理：列表/新建/删除 API + 最后一把 human key 保护 + 管理页渲染。"""

from __future__ import annotations


def test_create_list_delete_key(env):
    c, h = env["client"], env["human"]
    r = c.post("/api/v1/keys", json={"prefix": "agent", "label": "claude"}, headers=h)
    assert r.status_code == 201
    new = r.json()
    assert new["key"].startswith("agent-") and new["label"] == "claude"

    keys = c.get("/api/v1/keys", headers=h).json()
    assert len(keys) == 3  # 初始 human + agent + 新建
    assert any(k["key"] == new["key"] for k in keys)

    # 新 key 立即可用
    assert c.get("/api/v1/index", headers={"X-API-Key": new["key"]}).status_code == 200

    r = c.delete(f"/api/v1/keys/{new['id']}", headers=h)
    assert r.status_code == 200 and r.json()["deleted"] is True
    # 删除后立即失效
    assert c.get("/api/v1/index", headers={"X-API-Key": new["key"]}).status_code == 401


def test_create_key_invalid_prefix(env):
    c, h = env["client"], env["human"]
    assert c.post("/api/v1/keys", json={"prefix": "root"}, headers=h).status_code == 422


def test_last_human_key_cannot_be_deleted(env):
    c, h = env["client"], env["human"]
    keys = c.get("/api/v1/keys", headers=h).json()
    human_key = next(k for k in keys if k["prefix"] == "human")
    r = c.delete(f"/api/v1/keys/{human_key['id']}", headers=h)
    assert r.status_code == 409
    # 再建一把 human key 后，旧的就可以删了
    r2 = c.post("/api/v1/keys", json={"prefix": "human", "label": "backup"}, headers=h)
    assert r2.status_code == 201
    assert c.delete(f"/api/v1/keys/{human_key['id']}", headers=h).status_code == 200


def test_agent_key_cannot_manage_keys(env):
    """agent key 对密钥管理三个端点（含读取列表）一律 403——不能泄露任何 key。"""
    c, a = env["client"], env["agent"]
    assert c.get("/api/v1/keys", headers=a).status_code == 403
    assert c.post("/api/v1/keys", json={"prefix": "human"}, headers=a).status_code == 403
    assert c.delete("/api/v1/keys/1", headers=a).status_code == 403


def test_keys_page_renders(env):
    c, h = env["client"], env["human"]
    body = c.get(f"/ui/keys?key={h['X-API-Key']}").text
    assert "密钥管理" in body
    assert "test human" in body and "test agent" in body
    assert h["X-API-Key"] in body  # 当前 key 完整显示可复制
    assert "当前正在使用" in body
    assert "delKey" in body and "createKey" in body

"""版本作废（逻辑删除）：作废后 agent/页面不可见，DB 行保留；版本号永不复用。"""

from __future__ import annotations

from speclock.db import SessionLocal
from speclock.models import AuditLog, Block, BlockVersion
from tests.conftest import APIS_V2_MINOR, publish_v1


def _publish_v2_minor(env):
    """在 v1(1.0.0) 之后加一个响应字段并 fastTrack 发布 → 1.1.0。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    r = c.put(f"/api/v1/blocks/{bid}", json={"apis": APIS_V2_MINOR}, headers=h)
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "v2", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.1.0"


def _publish_two_versions(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    _publish_v2_minor(env)


def _void(env, version, headers=None):
    return env["client"].post(
        f"/api/v1/blocks/{env['block_id']}/versions/{version}/void",
        headers=headers if headers is not None else env["human"],
    )


def test_void_flow_visibility(env):
    """human 作废 1.1.0 → admin 列表/快照消失；agent pin 404、不 pin 回落 1.0.0；
    diff 涉作废版 404；index 回落；ack 作废版 404。"""
    _publish_two_versions(env)
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]

    r = _void(env, "1.1.0")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "block_id": bid, "version": "1.1.0", "voided": True,
        "current_published_version": "1.0.0",
    }

    # admin：历史列表不再出现，快照 404
    r = c.get(f"/api/v1/blocks/{bid}/versions", headers=h)
    assert [v["version"] for v in r.json()] == ["1.0.0"]
    assert c.get(f"/api/v1/blocks/{bid}/versions/1.1.0", headers=h).status_code == 404
    assert c.get(f"/api/v1/blocks/{bid}/versions/1.0.0", headers=h).status_code == 200

    # agent：pin 作废版 404；不 pin 回落到最新未作废版本
    assert c.get(f"/api/v1/blocks/{bid}@1.1.0", headers=a).status_code == 404
    r = c.get(f"/api/v1/blocks/{bid}", headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.0.0"

    # diff：默认取未作废版本（只剩一版 → 友好提示 200）；显式涉作废版 → 404
    r = c.get(f"/api/v1/blocks/{bid}/diff", headers=a)
    assert r.status_code == 200 and "message" in r.json()
    assert r.json()["versions"] == ["1.0.0"]
    assert c.get(f"/api/v1/blocks/{bid}/diff?from=1.0.0&to=1.1.0",
                 headers=a).status_code == 404
    assert c.get(f"/api/v1/blocks/{bid}/diff?from=1.0.0&to=1.1.0",
                 headers=h).status_code == 404

    # index / admin tree：当前版本回落 1.0.0
    r = c.get("/api/v1/index", headers=a)
    blocks = r.json()[0]["documents"][0]["blocks"]
    assert [b["version"] for b in blocks if b["block_id"] == bid] == ["1.0.0"]
    r = c.get("/api/v1/tree", headers=h)
    tblock = r.json()[0]["domains"][0]["documents"][0]["blocks"][0]
    assert tblock["current_published_version"] == "1.0.0"

    # ack：作废版 404，未作废版正常
    assert c.post(f"/api/v1/blocks/{bid}/ack", json={"version": "1.1.0"},
                  headers=a).status_code == 404
    assert c.post(f"/api/v1/blocks/{bid}/ack", json={"version": "1.0.0"},
                  headers=a).status_code == 201

    # 审计留痕
    db = SessionLocal()
    try:
        log = (db.query(AuditLog)
               .filter(AuditLog.action == "void", AuditLog.target == f"block:{bid}@1.1.0")
               .first())
        assert log is not None
    finally:
        db.close()


def test_void_is_idempotent_conflict(env):
    """已作废版本再次作废 → 409（与 restore/complete 的状态冲突语义一致）。"""
    _publish_two_versions(env)
    assert _void(env, "1.1.0").status_code == 200
    r = _void(env, "1.1.0")
    assert r.status_code == 409


def test_void_requires_human_key(env):
    _publish_two_versions(env)
    assert _void(env, "1.1.0", headers=env["agent"]).status_code == 403
    assert _void(env, "1.1.0", headers={}).status_code == 401
    # 未作废：agent 仍可读 1.1.0
    assert env["client"].get(f"/api/v1/blocks/{env['block_id']}@1.1.0",
                             headers=env["agent"]).status_code == 200


def test_void_nonexistent_version_404(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    assert _void(env, "9.9.9").status_code == 404
    assert env["client"].post("/api/v1/blocks/9999/versions/1.0.0/void",
                              headers=env["human"]).status_code == 404


def test_void_all_versions_behaves_unpublished(env):
    """全部版本作废：status 保持 published，但按未发布处理——agent get_block
    404、index 不出现、admin tree 版本为 null。"""
    _publish_two_versions(env)
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    assert _void(env, "1.1.0").status_code == 200
    r = _void(env, "1.0.0")
    assert r.status_code == 200
    assert r.json()["current_published_version"] is None

    assert c.get(f"/api/v1/blocks/{bid}", headers=a).status_code == 404
    r = c.get("/api/v1/index", headers=a)
    assert r.status_code == 200
    all_blocks = [
        b for dom in r.json() for doc in dom["documents"] for b in doc["blocks"]
    ]
    assert all(b["block_id"] != bid for b in all_blocks)

    r = c.get("/api/v1/tree", headers=h)
    tblock = r.json()[0]["domains"][0]["documents"][0]["blocks"][0]
    assert tblock["status"] == "published"
    assert tblock["current_published_version"] is None

    db = SessionLocal()
    try:
        block = db.get(Block, bid)
        assert block.status == "published"
        assert block.current_published_version is None
    finally:
        db.close()


def test_publish_after_void_never_reuses_version(env):
    """1.0.0/1.1.0 作废 1.1.0 后再发布 → 1.2.0（从含作废版本的历史最大号递增）。"""
    _publish_two_versions(env)
    assert _void(env, "1.1.0").status_code == 200
    c, h, bid = env["client"], env["human"], env["block_id"]
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "v3", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.2.0"
    # diff 基线是回退后的 1.0.0（extra_note 相对它仍是新增）
    assert any("extra_note" in x for x in r.json()["delta"]["added"])
    # 作废历史中间版本也不影响：再作废 1.2.0，下一版仍递增
    assert _void(env, "1.2.0").status_code == 200
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "v4", "fastTrack": True}, headers=h)
    assert r.json()["version"] == "1.3.0"


def test_voided_row_stays_in_db(env):
    """逻辑删除：BlockVersion 行仍在，voided_at 非空。"""
    _publish_two_versions(env)
    assert _void(env, "1.1.0").status_code == 200
    db = SessionLocal()
    try:
        bv = (db.query(BlockVersion)
              .filter(BlockVersion.block_id == env["block_id"],
                      BlockVersion.version == "1.1.0")
              .first())
        assert bv is not None
        assert bv.voided_at is not None
    finally:
        db.close()

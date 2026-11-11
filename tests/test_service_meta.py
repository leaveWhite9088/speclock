"""服务自身的状态接口：/api/v1/health。"""

from __future__ import annotations

from speclock_config import __version__

LOCAL = {"host": "127.0.0.1:8000"}


def test_health_needs_no_key_and_reports_the_version(env):
    r = env["client"].get("/api/v1/health", headers=LOCAL)
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


def test_health_works_for_localhost_and_ipv6_loopback(env):
    for host in ("localhost:8000", "[::1]:8000", "127.0.0.1"):
        assert env["client"].get("/api/v1/health", headers={"host": host}).status_code == 200, host


def test_health_refuses_other_hosts(env):
    for host in ("evil.example", "10.0.0.5:8000", "testserver"):
        r = env["client"].get("/api/v1/health", headers={"host": host})
        assert r.status_code == 403 and r.json()["code"] == "local_only", host
        assert r.json()["detail"] == "只对本机地址开放"


def test_health_reports_an_unreadable_database_as_503(env, monkeypatch):
    from sqlalchemy.orm import Session

    def broken(self, *a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(Session, "execute", broken)
    r = env["client"].get("/api/v1/health", headers=LOCAL)
    assert r.status_code == 503 and r.json() == {"status": "error", "version": __version__}

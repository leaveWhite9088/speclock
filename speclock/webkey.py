"""网页用的只读 key：``speclock init`` / ``serve`` 时自动准备，网页打开就自动取用，不用登录。

网页是只读展示，不该拿全权限的 admin key。这里给它一把 ``viewer`` 角色的 key（只能读），
明文放在 ``.speclock/web.key``（被 .gitignore 忽略），库里只存哈希。key 被删或文件丢了，
下次启动自动补一把。
"""

from __future__ import annotations

from pathlib import Path

from speclock.home import find_home

WEB_KEY_FILE = "web.key"
WEB_KEY_LABEL = "web"


def read_web_key(home: Path | None = None) -> str | None:
    home = home or find_home()
    if home is None:
        return None
    path = home / WEB_KEY_FILE
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def _ensure_gitignore(home: Path) -> None:
    path = home / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if WEB_KEY_FILE not in text.splitlines():
        path.write_text(text.rstrip("\n") + ("\n" if text else "") + f"{WEB_KEY_FILE}\n", encoding="utf-8")


def ensure_web_key(home: Path | None = None) -> str | None:
    """确保 .speclock/ 里有一把有效的网页只读 key，返回明文；没有 .speclock/（如测试）返回 None。
    调用前数据库必须已经 init_db（要用到 viewer 角色）。"""
    from speclock.auth import hash_key, key_hint, new_key
    from speclock.db import SessionLocal
    from speclock.models import ApiKey
    from speclock.permissions import get_role

    home = home or find_home()
    if home is None:
        return None
    key = read_web_key(home)
    db = SessionLocal()
    try:
        if key and db.query(ApiKey).filter(ApiKey.key == hash_key(key)).first():
            _ensure_gitignore(home)
            return key
        role = get_role(db, "viewer")
        key = new_key("human")
        db.add(ApiKey(key=hash_key(key), hint=key_hint(key), prefix=role.kind,
                      role_id=role.id, project_id=None, label=WEB_KEY_LABEL))
        db.commit()
    finally:
        db.close()
    (home / WEB_KEY_FILE).write_text(key + "\n", encoding="utf-8")
    _ensure_gitignore(home)
    return key

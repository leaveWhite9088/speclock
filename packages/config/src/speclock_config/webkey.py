"""网页用的只读 key 的文件部分：明文放在 ``.speclock/web.key``（被 .gitignore 忽略）。

这里只管文件；库里的 key 记录（viewer 角色、哈希）由 speclock_core 的引导逻辑维护。
"""

from __future__ import annotations

from pathlib import Path

from speclock_config.home import find_home

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


def ensure_web_key_ignored(home: Path) -> None:
    path = home / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if WEB_KEY_FILE not in text.splitlines():
        path.write_text(text.rstrip("\n") + ("\n" if text else "") + f"{WEB_KEY_FILE}\n", encoding="utf-8")


def write_web_key(home: Path, key: str) -> None:
    (home / WEB_KEY_FILE).write_text(key + "\n", encoding="utf-8")
    ensure_web_key_ignored(home)

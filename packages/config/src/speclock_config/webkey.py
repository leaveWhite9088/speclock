"""网页用的只读 key 的文件部分：每个项目一把，明文放在 ``.speclock/web-keys/<项目 id>.key``（被 .gitignore 忽略）。

网页只看得到一个项目：它用**绑定了该项目**的 ``viewer`` key 画界面，所以跨项目的内容它根本拿不到。
这里只管文件；库里的 key 记录（viewer 角色、哈希、绑定的项目）由 speclock_core 的引导逻辑维护。
"""

from __future__ import annotations

from pathlib import Path

from speclock_config.home import find_home

WEB_KEY_FILE = "web.key"  # 旧版：一把全局的网页 key。现在不再使用，启动时会清掉
WEB_KEYS_DIR = "web-keys"
WEB_KEY_LABEL = "web"


def web_key_path(home: Path, project_id: int) -> Path:
    return home / WEB_KEYS_DIR / f"{int(project_id)}.key"


def read_web_key(home: Path | None = None, project_id: int | None = None) -> str | None:
    home = home or find_home()
    if home is None or project_id is None:
        return None
    path = web_key_path(home, project_id)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def ensure_web_key_ignored(home: Path) -> None:
    path = home / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = text.splitlines()
    missing = [name for name in (WEB_KEY_FILE, f"{WEB_KEYS_DIR}/") if name not in lines]
    if missing:
        head = text.rstrip("\n") + "\n" if text else ""
        path.write_text(head + "".join(f"{name}\n" for name in missing), encoding="utf-8")


def write_web_key(home: Path, key: str, project_id: int) -> None:
    path = web_key_path(home, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    ensure_web_key_ignored(home)


def delete_legacy_web_key(home: Path) -> None:
    (home / WEB_KEY_FILE).unlink(missing_ok=True)

"""Agent 类 key 的存放：``.speclock/keys/`` 里每把一个 ``.key`` 文件。

- 只存 **Agent 类**角色的 key（需求 / 执行 / 测试 / 扫描）。人类 key（admin / reviewer）创建时显示一次，
  由人自己保管，不放进这里，免得同目录的 Agent 读到管理员权限。
- 创建 key 时由服务端直接写文件，API 响应里只给文件名、不给明文，所以明文不会经过任何对话。
- 吊销 key 时对应文件一并删除。
- 每个 Agent 只该读自己的那一个，不属于它的就不要读——靠 ``keys/README.md`` 和各角色的提示词约束
  （同一目录里文件互相看得见，这一点 Core 强制不了）。
"""

from __future__ import annotations

import re
from pathlib import Path

KEYS_DIRNAME = "keys"
KEY_SUFFIX = ".key"

README = """# 这里放各个 Agent 的 SpecLock key

每个文件是一把 key，文件名是「角色--名称」，内容就是 key 本身。

**如果你是 Agent：**

- 只读**属于你自己**的那一个文件（你的提示词 / 配置里会写明是哪个）。
- **不要打开、列出、复制、使用别的文件**，那是别的 Agent 的身份，不是你的职责。
- 不要把 key 的内容写进对话、日志、代码或提交里。
- 找不到自己的 key 文件，或者里面的 key 失效了：停下来告诉用户，不要去用别的。

**如果你是人：**

- 这些文件不会进 git（同目录的 `.gitignore` 已忽略 `*.key`）。
- `speclock key show <id>` 可以查看某把 key；`speclock key delete <id>` 吊销，文件一并删除。
- admin 等人类角色的 key 不会存在这里，请自己保管。
"""


def keys_dir(home: Path) -> Path:
    return home / KEYS_DIRNAME


def ensure_keys_dir(home: Path) -> Path:
    d = keys_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    readme = d / "README.md"
    if not readme.is_file():
        readme.write_text(README, encoding="utf-8")
    ignore = d / ".gitignore"
    if not ignore.is_file():
        ignore.write_text(f"*{KEY_SUFFIX}\n", encoding="utf-8")
    return d


def _slug(text: str) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "-", text.strip(), flags=re.UNICODE).strip("-_")
    return s[:40]


def file_name(role: str, label: str, key_id: int, taken: set[str] | None = None) -> str:
    base = f"{role}--{_slug(label) or key_id}"
    name = f"{base}{KEY_SUFFIX}"
    if taken and name in taken:
        name = f"{base}-{key_id}{KEY_SUFFIX}"
    return name


def save_key(home: Path, role: str, label: str, key_id: int, key: str) -> str:
    """把 key 写进 keys/ 目录，返回文件名。"""
    d = ensure_keys_dir(home)
    taken = {p.name for p in d.glob(f"*{KEY_SUFFIX}")}
    name = file_name(role, label, key_id, taken)
    (d / name).write_text(key + "\n", encoding="utf-8")
    return name


def delete_key_file(home: Path | None, name: str) -> None:
    if home is None or not name:
        return
    path = keys_dir(home) / Path(name).name  # 只认文件名，不跟路径
    if path.is_file():
        path.unlink()


def read_key(ref: str, home: Path | None = None) -> str:
    """读 key 文件：ref 可以是 keys/ 里的文件名（带不带 .key 都行），也可以是一个文件路径。"""
    p = Path(ref)
    if not p.is_file() and home is not None:
        for cand in (keys_dir(home) / ref, keys_dir(home) / f"{ref}{KEY_SUFFIX}"):
            if cand.is_file():
                p = cand
                break
    if not p.is_file():
        raise FileNotFoundError(f"找不到 key 文件：{ref}")
    key = p.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError(f"key 文件是空的：{p}")
    return key

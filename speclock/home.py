"""SpecLock 的「家」：配置和数据库放在哪、怎么找到、怎么创建。

数据永远不放在 SpecLock 源码目录里（源码可能只是项目里的一份克隆，或电脑上任意位置的一份）。
数据放在名为 ``.speclock/`` 的目录里：

    .speclock/
    ├── config.toml     # host / port / db 文件名；不含任何密钥
    ├── speclock.db     # 数据库（默认被 .gitignore 忽略，不进 git）
    └── .gitignore

两种用法只是 ``.speclock/`` 放在哪：
- 跟项目走：``<项目根>/.speclock/``（在项目根目录 ``speclock init``）；
- 跟电脑走：``~/.speclock/``（``speclock init --global``），一个服务、多个项目共用。

查找顺序（和 git 找 .git 一样）：
1. 环境变量 ``SPECLOCK_HOME``（直接指向某个 .speclock 目录）；
2. 从当前目录往上找最近的 ``.speclock/``（含 config.toml）；
3. 电脑级的 ``~/.speclock/``（环境变量 ``SPECLOCK_GLOBAL_HOME`` 可改位置，测试用）；
都没有就是没初始化过：提示先 ``speclock init``。
"""

from __future__ import annotations

import os
import socket
import tomllib
from dataclasses import dataclass
from pathlib import Path

HOME_DIRNAME = ".speclock"
CONFIG_NAME = "config.toml"
DB_NAME = "speclock.db"
# 电脑级用法的默认端口：挑了个冷门的，避开 8000 / 8080 / 3000 这类常见开发端口
GLOBAL_PORT = 47821
DEFAULT_HOST = "127.0.0.1"


class NotInitialised(RuntimeError):
    """找不到 .speclock/：还没有 init 过。"""


@dataclass(frozen=True)
class Config:
    home: Path
    host: str
    port: int
    db_file: str

    @property
    def db_path(self) -> Path:
        p = Path(self.db_file)
        return p if p.is_absolute() else self.home / p

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def global_home() -> Path:
    return Path(os.environ.get("SPECLOCK_GLOBAL_HOME") or (Path.home() / HOME_DIRNAME))


def _is_home(p: Path) -> bool:
    return (p / CONFIG_NAME).is_file()


def find_home(start: Path | None = None) -> Path | None:
    env = os.environ.get("SPECLOCK_HOME")
    if env:
        return Path(env)
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if _is_home(d / HOME_DIRNAME):
            return d / HOME_DIRNAME
    g = global_home()
    return g if _is_home(g) else None


def read_config(home: Path) -> Config:
    path = home / CONFIG_NAME
    if not path.is_file():
        raise NotInitialised(f"{home} 里没有 {CONFIG_NAME}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Config(
        home=home,
        host=str(data.get("host", DEFAULT_HOST)),
        port=int(data.get("port", GLOBAL_PORT)),
        db_file=str(data.get("db", DB_NAME)),
    )


def load_config(start: Path | None = None) -> Config:
    home = find_home(start)
    if home is None:
        raise NotInitialised("还没有初始化：在项目根目录运行 `speclock init`（或 `speclock init --global`）")
    return read_config(home)


def free_port() -> int:
    """挑一个空闲端口（init 时写进 config.toml）。在 20000~39999 里随机找，
    避开系统给出站连接用的临时端口段（49152 以上），否则过一阵可能被占掉。"""
    import random

    for _ in range(100):
        port = random.randint(20000, 39999)
        with socket.socket() as s:
            try:
                s.bind((DEFAULT_HOST, port))
            except OSError:
                continue
            return port
    with socket.socket() as s:
        s.bind((DEFAULT_HOST, 0))
        return s.getsockname()[1]


def write_home(home: Path, port: int) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / CONFIG_NAME).write_text(
        "# SpecLock 配置。不含任何密钥，可以提交进 git。\n"
        f'host = "{DEFAULT_HOST}"   # 只监听本机\n'
        f"port = {port}\n"
        f'db = "{DB_NAME}"\n',
        encoding="utf-8",
    )
    (home / ".gitignore").write_text(
        "# 数据库和网页用的 key 不进 git\n*.db\n*.db-*\nweb.key\n", encoding="utf-8")


def init_home(root: Path, *, glob: bool = False, project_name: str | None = None,
              port: int | None = None, new_admin: bool = False) -> tuple[Config, str | None]:
    """创建（或补全）.speclock/，建库、建项目、生成一把**随机** admin key。

    返回 (配置, admin key 明文或 None)。库里已经有 key 就不再生成（明文无法找回，
    只显示 hint），返回 None。``new_admin=True`` 在已有 key 的库里**再发一把** admin key
    （admin key 丢了的恢复办法：能在本机跑这条命令，就等于拥有这个库）。
    """
    from speclock import db as dbmod
    from speclock.auth import hash_key, key_hint, new_key
    from speclock.models import ApiKey, Project
    from speclock.permissions import get_role

    home = global_home() if glob else root / HOME_DIRNAME
    if not _is_home(home):
        write_home(home, port or (GLOBAL_PORT if glob else free_port()))
    cfg = read_config(home)

    dbmod.configure(cfg.db_url)
    dbmod.init_db()
    from speclock.webkey import WEB_KEY_LABEL, ensure_web_key

    session = dbmod.SessionLocal()
    try:
        if not new_admin and session.query(ApiKey).filter(ApiKey.label != WEB_KEY_LABEL).count():
            ensure_web_key(home)
            from speclock.keyfiles import ensure_keys_dir

            ensure_keys_dir(home)
            return cfg, None
        project = session.query(Project).first()
        if project is None:
            project = Project(name=project_name or (root.resolve().name or "我的项目"))
            session.add(project)
            session.flush()
        key = new_key("human")
        role = get_role(session, "admin")
        session.add(ApiKey(key=hash_key(key), hint=key_hint(key), prefix=role.kind,
                           role_id=role.id, project_id=None, label="admin"))
        session.commit()
    finally:
        session.close()
    ensure_web_key(home)  # 网页用的只读 key
    from speclock.keyfiles import ensure_keys_dir

    ensure_keys_dir(home)  # Agent key 的存放目录 + README
    return cfg, key


def default_url() -> str:
    """客户端（MCP / CLI）默认连哪里：SPECLOCK_URL 优先，其次找到的 .speclock/ 里的地址，
    都没有就用电脑级的默认端口。"""
    env = os.environ.get("SPECLOCK_URL")
    if env:
        return env.rstrip("/")
    home = find_home()
    if home is not None:
        try:
            return read_config(home).url
        except (NotInitialised, ValueError, OSError):
            pass
    return f"http://{DEFAULT_HOST}:{GLOBAL_PORT}"

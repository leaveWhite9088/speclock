"""环境配置：单个 speclock.toml 管理多套环境，改 active 一键切换。

文件位置（按序）：
1. 环境变量 SPECLOCK_CONFIG 指定的路径；
2. 仓库根目录 speclock.toml（pyproject.toml 旁）。

当前环境也可由环境变量 SPECLOCK_ENV 覆盖（systemd / CI 场景不方便改文件时）。
文件缺失时回退到 local 默认值，保证裸 checkout 也能跑。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent.parent / "speclock.toml"


@dataclass(frozen=True)
class Settings:
    env: str
    db_url: str  # 数据库 URL（SPECLOCK_DB_URL 环境变量优先，测试用它隔离）
    host: str  # uvicorn 监听地址
    port: int  # uvicorn 监听端口
    public_url: str  # MCP 页面展示的对外地址；空 = 按访问地址动态生成


def load_settings() -> Settings:
    path = Path(os.environ.get("SPECLOCK_CONFIG", str(_DEFAULT_PATH)))
    data: dict = {}
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    env = os.environ.get("SPECLOCK_ENV") or data.get("active", "local")
    profile = data.get(env, {})
    if env not in ("local",) and not profile:
        available = [k for k, v in data.items() if isinstance(v, dict)]
        raise ValueError(f"speclock.toml 中没有环境 [{env}]（可选：{available}）")
    return Settings(
        env=env,
        db_url=profile.get("db_url", "sqlite:///speclock.db"),
        host=profile.get("host", "127.0.0.1"),
        port=int(profile.get("port", 8000)),
        public_url=profile.get("public_url", ""),
    )

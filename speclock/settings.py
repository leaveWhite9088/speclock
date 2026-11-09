"""运行配置：来自 .speclock/config.toml（见 home.py）。

数据库地址 ``SPECLOCK_DB_URL`` 环境变量优先（测试用它隔离）；否则用 .speclock/ 里的库。
找不到 .speclock/ 时抛 ``NotInitialised``，提示先 ``speclock init``。
"""

from __future__ import annotations

from dataclasses import dataclass

from speclock.home import Config, load_config


@dataclass(frozen=True)
class Settings:
    db_url: str
    host: str
    port: int


def load_settings() -> Settings:
    cfg: Config = load_config()
    return Settings(db_url=cfg.db_url, host=cfg.host, port=cfg.port)

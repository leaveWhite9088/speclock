"""speclock_server —— HTTP 服务：FastAPI 路由、应用装配、网页托管。

依赖 speclock_config 与 speclock_core（都只通过它们的 index 使用）。

``app`` / ``create_app`` / ``run`` 是惰性导出：``main`` 一被导入就会建应用、连库，
而 ``import speclock_server.deps`` 之类的用法不该有这个副作用。
"""

from __future__ import annotations

__all__ = ["app", "create_app", "run"]


def __getattr__(name: str):
    if name in __all__:
        from speclock_server import main

        return getattr(main, name)
    raise AttributeError(f"module 'speclock_server' has no attribute {name!r}")

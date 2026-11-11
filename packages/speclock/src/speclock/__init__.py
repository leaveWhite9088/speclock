"""SpecLock — single source of truth for business docs, read-only to coding agents.

这是 monorepo 的「总装包」：自己没有逻辑，只依赖 speclock-config / core / server / mcp / cli，
让 ``pip install speclock`` 一次装全，并提供 ``python -m speclock``。
"""

from speclock_config import __version__

__all__ = ["__version__"]

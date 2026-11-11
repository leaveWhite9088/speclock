"""speclock_cli —— 命令行：init / serve / key / export / backup 等。

最上层的入口之一，可以依赖 config / core / server / mcp（都只通过各自的 index）。
"""

from speclock_cli.cli import main

__all__ = ["main"]

"""speclock_mcp —— Agent 用的 MCP server（stdio）。

只依赖 speclock_config（找服务地址、读 key 文件），经 HTTP 调 REST，不碰数据库，
所以 Agent 那一侧可以只装这个包。
"""

from speclock_mcp.server import main

__all__ = ["main"]

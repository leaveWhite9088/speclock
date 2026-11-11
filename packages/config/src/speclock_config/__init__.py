"""speclock_config —— 最底层：.speclock/ 目录的查找、配置、key 文件。

不依赖任何其他 speclock 包，也不碰数据库。上层只能通过这里导出的名字使用它
（``from speclock_config import ...``），不要深入子模块。
"""

__version__ = "0.2.6"

from speclock_config import keyfiles
from speclock_config.home import (
    CONFIG_NAME,
    DB_NAME,
    DEFAULT_EMBED_ORIGINS,
    DEFAULT_HOST,
    GLOBAL_PORT,
    HOME_DIRNAME,
    Config,
    NotInitialised,
    default_url,
    embed_origins,
    find_home,
    free_port,
    global_home,
    is_home,
    load_config,
    locate_home,
    mcp_config,
    read_config,
    write_home,
)
from speclock_config.keyfiles import (
    KEY_SUFFIX,
    KEYS_DIRNAME,
    delete_key_file,
    ensure_keys_dir,
    keys_dir,
    read_key,
    save_key,
)
from speclock_config.webkey import (
    WEB_KEY_FILE,
    WEB_KEY_LABEL,
    ensure_web_key_ignored,
    read_web_key,
    write_web_key,
)

__all__ = [
    "__version__", "keyfiles",
    "CONFIG_NAME", "DB_NAME", "DEFAULT_EMBED_ORIGINS", "DEFAULT_HOST", "GLOBAL_PORT", "HOME_DIRNAME",
    "Config", "NotInitialised",
    "default_url", "embed_origins", "find_home", "free_port", "global_home", "is_home",
    "load_config", "locate_home", "mcp_config", "read_config", "write_home",
    "KEY_SUFFIX", "KEYS_DIRNAME", "delete_key_file", "ensure_keys_dir", "keys_dir", "read_key", "save_key",
    "WEB_KEY_FILE", "WEB_KEY_LABEL", "ensure_web_key_ignored", "read_web_key", "write_web_key",
]

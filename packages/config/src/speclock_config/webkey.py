"""网页用的只读 key。

它就是一把**普通的、绑定了项目的 viewer 角色 key**，和其他 key 一样存放：明文在 ``.speclock/keys/`` 里的 key 文件，
库里只有哈希，列表里看得到、能吊销。每个项目一把（项目创建时自动建出来），网页用绑定该项目的 key 画界面，
所以只看得到这一个项目。这里只放几个常量和清理旧版遗留文件的函数。
"""

from __future__ import annotations

import shutil
from pathlib import Path

WEB_KEY_LABEL = "web"  # 自动建出来的网页 key 的标签
WEB_ROLE = "viewer"
# 旧版的存放方式（已废弃，启动时清掉）：一把全局的 .speclock/web.key，或每个项目一个 .speclock/web-keys/<id>.key
LEGACY_WEB_KEY_FILE = "web.key"
LEGACY_WEB_KEYS_DIR = "web-keys"


def delete_legacy_web_files(home: Path) -> None:
    (home / LEGACY_WEB_KEY_FILE).unlink(missing_ok=True)
    shutil.rmtree(home / LEGACY_WEB_KEYS_DIR, ignore_errors=True)

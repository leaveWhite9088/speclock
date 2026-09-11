"""Seed a demo project and print the two demo keys.

Usage:
    .venv/Scripts/python.exe -m speclock.seed          # uses ./speclock.db
    SPECLOCK_DB_URL=sqlite:///test.db python -m speclock.seed

Creates: 项目「Demo 电商系统」→ 大业务「运营」→ 文档「经营日报」→ 三个模块：
数据采集模块、异常数据展示模块、历史记录模块（每个模块 = 业务描述 + 结构化
API 列表 + 非功能性需求），全部以 1.0.0 发布；文档版本随之派生。
"""

from __future__ import annotations

import json

from speclock.api_admin import publish_block
from speclock.auth import new_key
from speclock.db import SessionLocal, get_engine, init_db
from speclock.models import ApiKey, Block, Document, Domain, Project

COLLECT_MD = """\
# 数据采集模块

## 业务逻辑
每日 06:00 由数据仓库任务汇总前一日经营数据，按「大区 → 门店」两级粒度落库。

- 销售额口径：支付成功订单金额合计（不含退款）
- 订单量口径：支付成功订单数
- 采集失败时任务重试 3 次，仍失败则告警到运营群，日报对应门店行标记「数据缺失」

前端通过 `GET /api/daily-report/collect-status` 查询某日的采集完成状态，
状态为「未完成」的门店在日报页灰显。
"""

COLLECT_APIS = [
    {
        "name": "查询采集状态",
        "api": "GET /api/daily-report/collect-status",
        "request": [
            {"name": "date", "type": "string", "required": True, "desc": "查询日期，YYYY-MM-DD"},
            {"name": "region", "type": "string", "required": False, "desc": "大区，不传查全部"},
        ],
        "response": [
            {"name": "date", "type": "string", "required": True, "desc": "日期"},
            {"name": "total_stores", "type": "integer", "required": True, "desc": "应采门店数"},
            {"name": "finished_stores", "type": "integer", "required": True, "desc": "已采集门店数"},
            {"name": "status", "type": "string", "required": True, "desc": "未完成/进行中/已完成"},
        ],
    }
]

COLLECT_NFR = """\
- 采集状态查询接口 P95 ≤ 300ms
- 采集任务须在每日 06:30 前完成
"""

ANOMALY_MD = """\
# 异常数据展示模块

## 业务逻辑
日报主表逐行套用异常值规则，命中任一规则即视为异常行，整行标红并置顶：

1. 销售额环比下降超过 30%（对比前一同口径日期）
2. 订单量为 0 但门店状态为「营业中」
3. 客单价超过该门店近 30 天均值 3 倍

前端通过 `GET /api/daily-report/anomalies` 拉取某日异常行列表；
规则阈值通过 `GET /api/daily-report/anomaly-rules` 读取，阈值修改次日生效，不回溯历史。
"""

ANOMALY_APIS = [
    {
        "name": "拉取异常行列表",
        "api": "GET /api/daily-report/anomalies",
        "request": [
            {"name": "date", "type": "string", "required": True, "desc": "查询日期"},
        ],
        "response": [
            {"name": "store_name", "type": "string", "required": True, "desc": "门店名"},
            {"name": "rule_id", "type": "string", "required": True, "desc": "命中的规则 ID"},
            {"name": "metric_value", "type": "number", "required": True, "desc": "触发指标值"},
        ],
    },
    {
        "name": "读取异常值规则",
        "api": "GET /api/daily-report/anomaly-rules",
        "request": [],
        "response": [
            {"name": "rule_id", "type": "string", "required": True, "desc": "规则 ID"},
            {"name": "metric", "type": "string", "required": True, "desc": "指标名"},
            {"name": "operator", "type": "string", "required": True, "desc": "比较符"},
            {"name": "threshold", "type": "number", "required": True, "desc": "阈值"},
            {"name": "enabled", "type": "boolean", "required": True, "desc": "是否启用"},
        ],
    },
]

ANOMALY_NFR = """\
- 异常行列表接口 P95 ≤ 500ms
- 规则数量上限 50 条
"""

HISTORY_MD = """\
# 历史记录模块

## 业务逻辑
日报页支持回看任意历史日期的主表数据，默认展示昨日，可切换日期或选择日期区间导出。
历史数据只读，不提供修改入口；数据保留 730 天。

前端通过 `GET /api/daily-report/history` 按日期区间分页拉取历史行。
"""

HISTORY_APIS = [
    {
        "name": "查询历史日报",
        "api": "GET /api/daily-report/history",
        "request": [
            {"name": "start_date", "type": "string", "required": True, "desc": "起始日期"},
            {"name": "end_date", "type": "string", "required": True, "desc": "结束日期"},
            {"name": "page", "type": "integer", "required": False, "desc": "页码，默认 1"},
        ],
        "response": [
            {"name": "date", "type": "string", "required": True, "desc": "日期"},
            {"name": "region", "type": "string", "required": True, "desc": "大区"},
            {"name": "store_name", "type": "string", "required": True, "desc": "门店名"},
            {"name": "sales", "type": "number", "required": True, "desc": "销售额"},
            {"name": "orders", "type": "integer", "required": True, "desc": "订单量"},
            {"name": "avg_order_value", "type": "number", "required": False, "desc": "客单价"},
        ],
    }
]

HISTORY_NFR = """\
- 历史查询接口 P95 ≤ 800ms（区间 ≤ 31 天）
- 单页默认 50 行，最大 200 行
"""


def main() -> None:
    get_engine()
    init_db()
    db = SessionLocal()

    existing = db.query(ApiKey).all()
    if existing:
        print("数据库已有 key，跳过建库，直接打印：")
        for k in existing:
            print(f"  {k.prefix}: {k.key}")
        db.close()
        return

    project = Project(name="Demo 电商系统")
    db.add(project)
    db.flush()
    domain = Domain(project_id=project.id, name="运营")
    db.add(domain)
    db.flush()
    document = Document(domain_id=domain.id, title="经营日报", doc_type="business")
    db.add(document)
    db.flush()

    human_key = new_key("human")
    agent_key = new_key("agent")
    db.add_all(
        [
            ApiKey(key=human_key, prefix="human", project_id=project.id, label="demo human"),
            ApiKey(key=agent_key, prefix="agent", project_id=project.id, label="demo agent"),
        ]
    )

    modules = [
        ("数据采集模块", "汇总前一日经营数据并落库，提供采集状态查询", COLLECT_MD, COLLECT_APIS, COLLECT_NFR),
        ("异常数据展示模块", "销售额环比骤降等三类异常行的标红置顶展示与规则配置", ANOMALY_MD, ANOMALY_APIS, ANOMALY_NFR),
        ("历史记录模块", "按日期区间回看/导出历史日报数据", HISTORY_MD, HISTORY_APIS, HISTORY_NFR),
    ]
    created = []
    for title, summary, md, apis, nfr in modules:
        block = Block(
            document_id=document.id,
            title=title,
            summary=summary,
            draft_content_md=md,
            draft_apis_json=json.dumps(apis, ensure_ascii=False),
            draft_nfr_md=nfr,
        )
        db.add(block)
        db.flush()
        result = publish_block(db, block, actor=human_key, change_note="初始发布",
                               fast_track=True, confirm=False)
        created.append((block, result))

    db.commit()

    print("SpecLock demo 数据已创建：")
    print("  项目: Demo 电商系统 → 大业务: 运营 → 文档: 经营日报")
    for block, result in created:
        print(f"  模块 #{block.id}「{block.title}」@{result.version}（文档版本 @{result.document_version}）")
    print()
    print(f"  human key (读写/UI): {human_key}")
    print(f"  agent key (只读+提案): {agent_key}")
    print()
    print("启动服务:  .venv/Scripts/python.exe -m uvicorn speclock.main:app")
    print(f"管理 UI:   http://127.0.0.1:8000/ui?key={human_key}")
    db.close()


if __name__ == "__main__":
    main()

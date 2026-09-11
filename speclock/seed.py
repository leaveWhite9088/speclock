"""Seed a demo project and print the two demo keys.

Usage:
    .venv/Scripts/python.exe -m speclock.seed          # uses ./speclock.db
    SPECLOCK_DB_URL=sqlite:///test.db python -m speclock.seed

Creates: 项目「Demo 电商系统」→ 大业务「运营」→
  文档「经营日报」: 数据采集模块 / 异常数据展示模块 / 历史记录模块 / 异常规则配置模块
  文档「售罄率报表」: 数据采集模块 / 异常数据展示模块 / 历史版本记录模块 / 异常规则配置模块
每个模块 = 业务描述 + 结构化 API 列表（含 object/array 嵌套 children 演示）+
非功能性需求，全部以 1.0.0 发布；文档版本随之派生。
"""

from __future__ import annotations

import json

from speclock.api_admin import publish_block
from speclock.auth import new_key
from speclock.db import SessionLocal, get_engine, init_db
from speclock.models import ApiKey, Block, Document, Domain, Project


def F(name, type_, required=False, description="", children=None):
    """Field shorthand for the recursive {name,type,required,description,children} model."""
    return {
        "name": name,
        "type": type_,
        "required": required,
        "description": description,
        "children": children or [],
    }


# ================= 经营日报 =================

DAILY_COLLECT_MD = """\
# 数据采集模块（经营日报）

## 业务逻辑
每日 06:00 由数据仓库任务汇总前一日经营数据，按「大区 → 门店」两级粒度落库。

- 销售额口径：支付成功订单金额合计（不含退款）
- 订单量口径：支付成功订单数
- 采集失败时任务重试 3 次，仍失败则告警到运营群，日报对应门店行标记「数据缺失」

前端通过 `GET /api/daily-report/collect-status` 查询某日的采集完成状态，
状态为「未完成」的门店在日报页灰显。
"""

DAILY_COLLECT_APIS = [
    {
        "name": "查询采集状态",
        "api": "GET /api/daily-report/collect-status",
        "request": [
            F("date", "string", True, "查询日期，YYYY-MM-DD"),
            F("region", "string", False, "大区，不传查全部"),
        ],
        "response": [
            F("date", "string", True, "日期"),
            F("total_stores", "integer", True, "应采门店数"),
            F("finished_stores", "integer", True, "已采集门店数"),
            F("status", "string", True, "未完成/进行中/已完成"),
        ],
    }
]

DAILY_COLLECT_NFR = "- 采集状态查询接口 P95 ≤ 300ms\n- 采集任务须在每日 06:30 前完成\n"

DAILY_ANOMALY_MD = """\
# 异常数据展示模块（经营日报）

## 业务逻辑
日报主表逐行套用异常值规则，命中任一规则即视为异常行，整行标红并置顶：

1. 销售额环比下降超过 30%（对比前一同口径日期）
2. 订单量为 0 但门店状态为「营业中」
3. 客单价超过该门店近 30 天均值 3 倍

前端通过 `GET /api/daily-report/anomalies` 拉取某日异常行列表。
规则阈值的读取与修改见「异常规则配置模块」。
"""

DAILY_ANOMALY_APIS = [
    {
        "name": "拉取异常行列表",
        "api": "GET /api/daily-report/anomalies",
        "request": [F("date", "string", True, "查询日期")],
        "response": [
            F("store_name", "string", True, "门店名"),
            F("rule_id", "string", True, "命中的规则 ID"),
            F("metric_value", "number", True, "触发指标值"),
        ],
    }
]

DAILY_ANOMALY_NFR = "- 异常行列表接口 P95 ≤ 500ms\n"

DAILY_HISTORY_MD = """\
# 历史记录模块（经营日报）

## 业务逻辑
日报页支持回看任意历史日期的主表数据，默认展示昨日，可切换日期或选择日期区间导出。
历史数据只读，不提供修改入口；数据保留 730 天。

前端通过 `GET /api/daily-report/history` 按日期区间分页拉取历史行。
"""

DAILY_HISTORY_APIS = [
    {
        "name": "查询历史日报",
        "api": "GET /api/daily-report/history",
        "request": [
            F("start_date", "string", True, "起始日期"),
            F("end_date", "string", True, "结束日期"),
            F("page", "integer", False, "页码，默认 1"),
        ],
        "response": [
            F("date", "string", True, "日期"),
            F("region", "string", True, "大区"),
            F("store_name", "string", True, "门店名"),
            F("sales", "number", True, "销售额"),
            F("orders", "integer", True, "订单量"),
            F("avg_order_value", "number", False, "客单价"),
        ],
    }
]

DAILY_HISTORY_NFR = "- 历史查询接口 P95 ≤ 800ms（区间 ≤ 31 天）\n- 单页默认 50 行，最大 200 行\n"

DAILY_RULE_MD = """\
# 异常规则配置模块（经营日报）

## 业务逻辑
运营在日报页配置异常值规则的阈值与生效范围。规则保存后次日生效，不回溯历史数据。

- `rule.scope` 决定规则生效范围：可限定大区或门店，缺省为全量
- 同一指标只允许一条启用中的规则
- 前端通过 `POST /api/daily-report/anomaly-rules` 新增或修改规则（带 rule_id 为修改）
"""

DAILY_RULE_APIS = [
    {
        "name": "保存异常规则",
        "api": "POST /api/daily-report/anomaly-rules",
        "request": [
            F("rule", "object", True, "规则对象（嵌套结构演示）", children=[
                F("rule_id", "string", False, "规则 ID，新增时留空"),
                F("metric", "string", True, "指标名：sales/orders/avg_order_value"),
                F("operator", "string", True, "比较符：lt/gt/eq"),
                F("threshold", "number", True, "阈值"),
                F("enabled", "boolean", True, "是否启用"),
                F("scope", "object", False, "生效范围，缺省全量", children=[
                    F("region", "string", False, "限定大区"),
                    F("store_name", "string", False, "限定门店"),
                ]),
            ]),
        ],
        "response": [
            F("saved", "boolean", True, "是否保存成功"),
            F("rule_id", "string", True, "规则 ID"),
        ],
    }
]

DAILY_RULE_NFR = "- 规则保存接口 P95 ≤ 500ms\n- 规则数量上限 50 条\n"

# ================= 售罄率报表 =================

SELLOUT_COLLECT_MD = """\
# 数据采集模块（售罄率报表）

## 业务逻辑
售罄率 = 累计销售量 / 累计到货量。每日 07:00 由数据仓库按「大区 → 门店 → SKU」
三级粒度汇总前一日数据落库；到货量以仓库入库单为准，销售量以支付成功订单为准。

前端通过 `GET /api/sellout-report/collect-status` 查询采集状态。
"""

SELLOUT_COLLECT_APIS = [
    {
        "name": "查询售罄数据采集状态",
        "api": "GET /api/sellout-report/collect-status",
        "request": [F("date", "string", True, "查询日期")],
        "response": [
            F("date", "string", True, "日期"),
            F("total_skus", "integer", True, "应采 SKU 数"),
            F("finished_skus", "integer", True, "已采集 SKU 数"),
            F("status", "string", True, "未完成/进行中/已完成"),
        ],
    }
]

SELLOUT_COLLECT_NFR = "- 采集状态查询接口 P95 ≤ 300ms\n- 采集任务须在每日 07:30 前完成\n"

SELLOUT_ANOMALY_MD = """\
# 异常数据展示模块（售罄率报表）

## 业务逻辑
售罄率报表逐行套用异常值规则，命中即标红置顶：

1. 售罄率 7 日内从低于 30% 跳升到 95% 以上（疑似超卖或数据错误）
2. 到货量为 0 但产生销售（库存数据缺失）
3. 售罄率连续 14 天低于 5%（滞销预警）

前端通过 `GET /api/sellout-report/anomalies` 拉取异常行。
"""

SELLOUT_ANOMALY_APIS = [
    {
        "name": "拉取售罄异常行",
        "api": "GET /api/sellout-report/anomalies",
        "request": [F("date", "string", True, "查询日期")],
        "response": [
            F("store_name", "string", True, "门店名"),
            F("sku_id", "string", True, "SKU 编码"),
            F("rule_id", "string", True, "命中的规则 ID"),
            F("sellout_rate", "number", True, "触发时的售罄率"),
        ],
    }
]

SELLOUT_ANOMALY_NFR = "- 异常行列表接口 P95 ≤ 500ms\n"

SELLOUT_HISTORY_MD = """\
# 历史版本记录模块（售罄率报表）

## 业务逻辑
售罄率报表按日快照保存，运营可回看任意历史日期的报表版本，
并下钻到「门店 → SKU」两级明细。快照只读，保留 365 天。

前端通过 `GET /api/sellout-report/history` 拉取历史快照，
响应为按日期分组的多层嵌套结构（日期 → 门店 → SKU）。
"""

SELLOUT_HISTORY_APIS = [
    {
        "name": "查询售罄率历史快照",
        "api": "GET /api/sellout-report/history",
        "request": [
            F("start_date", "string", True, "起始日期"),
            F("end_date", "string", True, "结束日期"),
        ],
        "response": [
            F("snapshots", "array", True, "按日期分组的快照列表（多层嵌套演示）", children=[
                F("date", "string", True, "快照日期"),
                F("stores", "array", True, "门店明细", children=[
                    F("store_name", "string", True, "门店名"),
                    F("sellout_rate", "number", True, "门店售罄率"),
                    F("skus", "array", False, "SKU 明细", children=[
                        F("sku_id", "string", True, "SKU 编码"),
                        F("sku_name", "string", True, "SKU 名称"),
                        F("sales_qty", "integer", True, "累计销售量"),
                        F("stock_qty", "integer", True, "累计到货量"),
                    ]),
                ]),
            ]),
        ],
    }
]

SELLOUT_HISTORY_NFR = "- 历史快照接口 P95 ≤ 1s（区间 ≤ 31 天）\n- 快照保留 365 天\n"

SELLOUT_RULE_MD = """\
# 异常规则配置模块（售罄率报表）

## 业务逻辑
运营配置售罄率异常规则的阈值与生效范围。规则保存后次日生效。
`rule.condition` 为嵌套对象，描述触发条件；`rule.scope` 限定生效的大区/门店/SKU。

前端通过 `POST /api/sellout-report/anomaly-rules` 新增或修改规则。
"""

SELLOUT_RULE_APIS = [
    {
        "name": "保存售罄异常规则",
        "api": "POST /api/sellout-report/anomaly-rules",
        "request": [
            F("rule", "object", True, "规则对象", children=[
                F("rule_id", "string", False, "规则 ID，新增时留空"),
                F("condition", "object", True, "触发条件", children=[
                    F("metric", "string", True, "指标名：sellout_rate/sales_qty/stock_qty"),
                    F("operator", "string", True, "比较符：lt/gt/jump"),
                    F("threshold", "number", True, "阈值"),
                    F("window_days", "integer", False, "观察窗口天数，默认 7"),
                ]),
                F("enabled", "boolean", True, "是否启用"),
                F("scope", "object", False, "生效范围，缺省全量", children=[
                    F("region", "string", False, "限定大区"),
                    F("store_name", "string", False, "限定门店"),
                    F("sku_id", "string", False, "限定 SKU"),
                ]),
            ]),
        ],
        "response": [
            F("saved", "boolean", True, "是否保存成功"),
            F("rule_id", "string", True, "规则 ID"),
        ],
    }
]

SELLOUT_RULE_NFR = "- 规则保存接口 P95 ≤ 500ms\n- 规则数量上限 50 条\n"


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

    human_key = new_key("human")
    agent_key = new_key("agent")
    db.add_all(
        [
            ApiKey(key=human_key, prefix="human", project_id=project.id, label="demo human"),
            ApiKey(key=agent_key, prefix="agent", project_id=project.id, label="demo agent"),
        ]
    )

    docs = [
        ("经营日报", [
            ("数据采集模块", "汇总前一日经营数据并落库，提供采集状态查询",
             DAILY_COLLECT_MD, DAILY_COLLECT_APIS, DAILY_COLLECT_NFR),
            ("异常数据展示模块", "销售额环比骤降等三类异常行的标红置顶展示",
             DAILY_ANOMALY_MD, DAILY_ANOMALY_APIS, DAILY_ANOMALY_NFR),
            ("历史记录模块", "按日期区间回看/导出历史日报数据",
             DAILY_HISTORY_MD, DAILY_HISTORY_APIS, DAILY_HISTORY_NFR),
            ("异常规则配置模块", "异常值规则的阈值与生效范围配置（增改接口）",
             DAILY_RULE_MD, DAILY_RULE_APIS, DAILY_RULE_NFR),
        ]),
        ("售罄率报表", [
            ("数据采集模块", "按大区/门店/SKU 三级粒度汇总售罄率数据",
             SELLOUT_COLLECT_MD, SELLOUT_COLLECT_APIS, SELLOUT_COLLECT_NFR),
            ("异常数据展示模块", "超卖、库存缺失、滞销三类售罄异常行展示",
             SELLOUT_ANOMALY_MD, SELLOUT_ANOMALY_APIS, SELLOUT_ANOMALY_NFR),
            ("历史版本记录模块", "按日快照回看售罄率报表，下钻门店/SKU 明细",
             SELLOUT_HISTORY_MD, SELLOUT_HISTORY_APIS, SELLOUT_HISTORY_NFR),
            ("异常规则配置模块", "售罄率异常规则的阈值与生效范围配置",
             SELLOUT_RULE_MD, SELLOUT_RULE_APIS, SELLOUT_RULE_NFR),
        ]),
    ]

    created = []
    for doc_title, modules in docs:
        document = Document(domain_id=domain.id, title=doc_title, doc_type="business")
        db.add(document)
        db.flush()
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
            created.append((document, block, result))

    db.commit()

    print("SpecLock demo 数据已创建：")
    print("  项目: Demo 电商系统 → 大业务: 运营")
    for document, block, result in created:
        print(f"  文档「{document.title}」模块 #{block.id}「{block.title}」@{result.version}"
              f"（文档版本 @{result.document_version}）")
    print()
    print(f"  human key (读写/UI): {human_key}")
    print(f"  agent key (只读+提案): {agent_key}")
    print()
    print("启动服务:  .venv/Scripts/python.exe -m uvicorn speclock.main:app")
    print(f"管理 UI:   http://127.0.0.1:8000/ui?key={human_key}")
    db.close()


if __name__ == "__main__":
    main()

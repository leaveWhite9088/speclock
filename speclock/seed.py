"""Seed a demo project and print the two demo keys.

Usage:
    .venv/Scripts/python.exe -m speclock.seed          # uses ./speclock.db
    SPECLOCK_DB_URL=sqlite:///test.db python -m speclock.seed

Creates: 项目「Demo 电商系统」→ 大业务「运营」→ 文档「经营日报」→
块「日报主表」与「异常值规则」, both published at 1.0.0.
"""

from __future__ import annotations

import json

from speclock import diffing
from speclock.auth import new_key
from speclock.db import SessionLocal, get_engine, init_db
from speclock.models import (
    ApiKey,
    Block,
    BlockVersion,
    Document,
    Domain,
    Project,
    utcnow,
)

DAILY_REPORT_MD = """\
# 日报主表

## 业务逻辑
每日 06:00 由数据仓库任务汇总前一日经营数据，按「大区 → 门店」两级粒度产出日报。
运营同学打开经营日报页时，前端调用 `GET /api/daily/report` 拉取主表数据，
默认展示昨日数据，可切换日期；销售额、订单量、客单价为核心指标。

- 销售额口径：支付成功订单金额合计（不含退款）
- 订单量口径：支付成功订单数
- 客单价 = 销售额 / 订单量，分母为 0 时展示「-」

## 异常联动
某行触发异常值规则（见块「异常值规则」）时，该行整行标红并置顶。
"""

DAILY_REPORT_YAML = """\
openapi: "3.0.3"
info:
  title: 经营日报 API 片段
  version: "1.0.0"
paths:
  /api/daily/report:
    get:
      summary: 拉取日报主表
      parameters:
        - name: date
          in: query
          schema:
            type: string
        - name: region
          in: query
          schema:
            type: string
      responses:
        "200":
          description: 日报主表行列表
components:
  schemas:
    DailyReportRow:
      type: object
      required: [date, region, sales, orders]
      properties:
        date:
          type: string
        region:
          type: string
        store_name:
          type: string
        sales:
          type: number
        orders:
          type: integer
        avg_order_value:
          type: number
"""

DAILY_REPORT_NFR = """\
- 主表接口 P95 ≤ 500ms
- 单页默认 50 行，翻页加载
"""

ANOMALY_MD = """\
# 异常值规则

## 业务逻辑
日报主表逐行套用以下规则，命中任一规则即视为异常行：

1. 销售额环比下降超过 30%（对比前一同口径日期）
2. 订单量为 0 但门店状态为「营业中」
3. 客单价超过该门店近 30 天均值 3 倍

规则阈值由运营在页面上配置，前端通过 `GET /api/daily/anomaly-rules` 读取，
保存在 `AnomalyRule` 结构中。阈值修改次日生效，不回溯历史数据。
"""

ANOMALY_YAML = """\
openapi: "3.0.3"
info:
  title: 异常值规则 API 片段
  version: "1.0.0"
paths:
  /api/daily/anomaly-rules:
    get:
      summary: 读取异常值规则配置
      responses:
        "200":
          description: 当前生效的规则列表
components:
  schemas:
    AnomalyRule:
      type: object
      required: [rule_id, metric, operator, threshold]
      properties:
        rule_id:
          type: string
        metric:
          type: string
        operator:
          type: string
        threshold:
          type: number
        enabled:
          type: boolean
"""

ANOMALY_NFR = """\
- 规则数量上限 50 条
- 规则读取接口 P95 ≤ 300ms
"""


def _publish(db, block: Block, actor: str, change_note: str) -> BlockVersion:
    d = diffing.delta("", block.draft_openapi_yaml)
    version = diffing.next_version(None, d)
    bv = BlockVersion(
        block_id=block.id,
        version=version,
        content_md=block.draft_content_md,
        openapi_yaml=block.draft_openapi_yaml,
        nfr_md=block.draft_nfr_md,
        change_note=change_note,
        delta_json=json.dumps(d, ensure_ascii=False),
        published_by=actor,
        published_at=utcnow(),
    )
    db.add(bv)
    block.current_published_version = version
    block.status = "published"
    return bv


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

    b1 = Block(
        document_id=document.id,
        title="日报主表",
        summary="按大区/门店展示昨日销售额、订单量、客单价的主表模块",
        draft_content_md=DAILY_REPORT_MD,
        draft_openapi_yaml=DAILY_REPORT_YAML,
        draft_nfr_md=DAILY_REPORT_NFR,
    )
    b2 = Block(
        document_id=document.id,
        title="异常值规则",
        summary="销售额环比骤降、订单为 0、客单价异常三类规则及阈值配置",
        draft_content_md=ANOMALY_MD,
        draft_openapi_yaml=ANOMALY_YAML,
        draft_nfr_md=ANOMALY_NFR,
    )
    db.add_all([b1, b2])
    db.flush()
    _publish(db, b1, human_key, "初始发布")
    _publish(db, b2, human_key, "初始发布")
    db.commit()

    print("SpecLock demo 数据已创建：")
    print("  项目: Demo 电商系统 → 大业务: 运营 → 文档: 经营日报")
    print(f"  块 #{b1.id}「日报主表」@1.0.0, 块 #{b2.id}「异常值规则」@1.0.0")
    print()
    print(f"  human key (读写/UI): {human_key}")
    print(f"  agent key (只读+提案): {agent_key}")
    print()
    print("启动服务:  .venv/Scripts/python.exe -m uvicorn speclock.main:app")
    print(f"管理 UI:   http://127.0.0.1:8000/ui?key={human_key}")
    db.close()


if __name__ == "__main__":
    main()

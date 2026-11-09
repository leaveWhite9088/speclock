"""开发辅助：往一个「空库」（python -m speclock.seed --empty）里灌一套有代表性的场景，
用来在网页上看各个页面的样子。只用公开 REST 接口，和真实 Agent 走的是同一条路。

    python tools/demo_scenario.py http://127.0.0.1:8012

场景（社区小店）：3 个模块；一个任务已验收、一个被阻塞、一个失败、一个等验收、一个进行中；
一张等人确认的审核单；一张 Agent 自行判定的内部整理单；一张被驳回的审核单。
"""

from __future__ import annotations

import os
import sys

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
ADMIN = os.environ.get("SPECLOCK_ADMIN_KEY", "human-dev-0000000000000000000000000001")

BG = "# {t}\n\n{t}的业务背景与流程叙述，写得稍微长一点，满足不少于二十个字符的要求。"


def call(method, path, key, **kw):
    r = httpx.request(method, BASE + path, headers={"X-API-Key": key}, timeout=30, **kw)
    if r.status_code >= 400:
        sys.exit(f"{method} {path} -> {r.status_code}: {r.text}")
    return r.json()


def new_key(role, label):
    return call("POST", "/keys", ADMIN, json={"role": role, "label": label, "via": "api", "project_id": 1})["key"]


def cr_flow(req, body, approve=True, evidence="同意，按这个来"):
    cr = call("POST", "/change-requests", req, json=body)
    cr = call("POST", f"/change-requests/{cr['id']}/submit", req)
    if approve and cr["status"] == "pending_review":
        call("POST", f"/change-requests/{cr['id']}/approve", ADMIN,
             json={"content_hash": cr["content_hash"], "via": "natural_language", "evidence": evidence})
    return cr["id"]


def results(ids, evidence):
    return [{"ac_id": i, "result": "pass", "evidence": evidence} for i in ids]


def main():
    req = new_key("requirements-agent", "需求 Agent")
    exe = new_key("executor-agent", "后端执行 Agent")
    qa = new_key("tester-agent", "测试 Agent")

    def block(title, rules, acs):
        return {"op": "create_block", "capability": "$cap", "title": title, "content_md": BG.format(t=title),
                "rules": rules, "apis": [], "acceptance": acs}

    cr1 = cr_flow(req, {
        "title": "建立社区小店订单管理的业务规格", "intent": "社区小店要上线线上订单，需要先把订单业务讲清楚",
        "expected_outcome": "订单从下单到完成、退款的业务规则都有明确的规格",
        "acceptance": [{"name": "订单流程完整", "detail": "下单、接单、完成三步都有规则"},
                       {"name": "退款规则明确", "detail": "退款条件与金额口径写清楚"}],
        "obsolete": ["订单只能电话下单"], "impact_note": "新增业务，不影响现有内容",
    })
    ops = [
        {"op": "create_business", "name": "社区小店", "ref": "biz"},
        {"op": "create_capability", "business": "$biz", "title": "订单管理", "ref": "cap"},
        block("订单生命周期", [{"name": "状态流转", "detail": "下单 → 接单 → 完成，不能跳步"}],
              [{"name": "状态按序流转", "detail": "不能从下单直接到完成"}]),
        block("退款", [{"name": "退款条件", "detail": "完成后 7 天内可退款"}],
              [{"name": "超期不可退", "detail": "超过 7 天的退款申请被拒绝"}]),
        block("订单内容", [{"name": "金额币种", "detail": "订单金额统一以人民币计价"}],
              [{"name": "金额显示", "detail": "金额带人民币符号"}]),
    ]
    call("POST", f"/change-requests/{cr1}/commits", req,
         json={"ops": ops, "covers": ["AC-1", "AC-2"], "change_note": "初始规格"})
    call("POST", f"/change-requests/{cr1}/complete", req)

    work = {w["block_title"]: w["id"] for w in call("GET", "/work", exe)}
    # 订单生命周期：已验收
    w = work["订单生命周期"]
    call("POST", f"/work/{w}/claim", exe)
    call("POST", f"/work/{w}/implementation", exe, json={"results": results(["AC-1"], "联调模拟：测试通过")})
    call("POST", f"/work/{w}/verification", qa, json={"results": results(["AC-1"], "独立复测通过")})
    # 退款：被阻塞
    w = work["退款"]
    call("POST", f"/work/{w}/claim", exe)
    call("POST", f"/work/{w}/blocked", exe, json={"reason": "退款金额是否包含运费？规格没写，不敢猜"})
    # 订单内容：先失败一次再重新领取后等验收
    w = work["订单内容"]
    call("POST", f"/work/{w}/claim", exe)
    call("POST", f"/work/{w}/failed", exe, json={"reason": "金额格式化依赖的服务不可用"})

    # 再发布一个新版本，让「订单内容」多一个待领取，并让另一个任务处于等验收
    cr2 = cr_flow(req, {
        "title": "订单金额增加优惠前后两种口径", "intent": "运营要看优惠前后的金额", "expected_outcome": "订单内容同时记录原价和实付",
        "acceptance": [{"name": "两种口径", "detail": "订单里能看到原价和实付"}],
        "obsolete": ["订单只有一个金额"], "impact_note": "只影响订单内容",
    })
    call("POST", f"/change-requests/{cr2}/commits", req, json={"ops": [{
        "op": "update_block", "id": 3,
        "rule_ops": [{"op": "upsert", "entry": {"name": "两种金额", "detail": "同时记录原价和实付金额"}}]}],
        "covers": ["AC-1"]})
    call("POST", f"/change-requests/{cr2}/complete", req)
    new_w = [w for w in call("GET", "/work?status=pending", exe) if w["block_title"] == "订单内容"][0]["id"]
    call("POST", f"/work/{new_w}/claim", exe)  # 进行中

    # 一张等人确认的审核单
    cr_flow(req, {
        "title": "退款支持部分退款", "intent": "顾客只想退其中一件商品", "expected_outcome": "退款可以按商品部分退",
        "acceptance": [{"name": "部分退款", "detail": "可以只退订单里的部分商品"}],
        "obsolete": ["退款只能整单退"], "impact_note": "只影响退款模块",
    }, approve=False)

    # 一张 Agent 自行判定的内部整理单
    cr3 = cr_flow(req, {
        "title": "把「订单管理」改名为「订单中心」", "intent": "名字更贴近业务叫法", "expected_outcome": "小业务名称变化，内容不变",
        "acceptance": [{"name": "只改名", "detail": "规则、验收条件、API 一字未改"}],
        "kind": "internal", "kind_reason": "只是改小业务的名字，所有规则和验收条件原样保留",
    })
    call("POST", f"/change-requests/{cr3}/commits", req,
         json={"ops": [{"op": "update_capability", "id": 1, "title": "订单中心"}], "covers": ["AC-1"]})
    call("POST", f"/change-requests/{cr3}/complete", req)

    # 一张被驳回的审核单
    cr4 = call("POST", "/change-requests", req, json={
        "title": "退款不收手续费", "intent": "促销", "expected_outcome": "退款免手续费",
        "acceptance": [{"name": "免手续费", "detail": "任何退款都不扣手续费"}]})["id"]
    call("POST", f"/change-requests/{cr4}/submit", req)
    call("POST", f"/change-requests/{cr4}/reject", ADMIN,
         json={"reason": "手续费政策还没定，先不改", "via": "natural_language", "evidence": "先不改，手续费政策还没定"})

    print("场景已灌入：3 个模块；任务已验收 / 被阻塞 / 失败 / 进行中；审核单 待确认 / 内部整理 / 被驳回 各一张。")


if __name__ == "__main__":
    main()

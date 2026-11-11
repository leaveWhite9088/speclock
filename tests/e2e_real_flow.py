"""端到端：在临时目录里真的 speclock init -> serve，再通过 MCP 工具函数（真实 HTTP）走完整个业务流程。

不是 pytest 用例（不会被自动收集），需要时手动跑：
    python tests/e2e_real_flow.py             # 跟项目走（<项目>/.speclock）
    python tests/e2e_real_flow.py --global    # 跟电脑走（~/.speclock，这里用临时目录代替）
覆盖：项目、密钥（文件）、审核单 → 批准 → Commit → 执行 → 验收、卡住后的新版本、内部整理、
权限边界（各角色的 403）、活动日志、网页只读 key、/embed.js。"""
import logging
import json, os, re, subprocess, sys, tempfile, time
from pathlib import Path

import httpx

EXE = [sys.executable, "-m", "speclock"]
logging.getLogger("httpx").setLevel(logging.WARNING)
work = Path(tempfile.mkdtemp(prefix="speclock-e2e-"))
GLOBAL = "--global" in sys.argv
home_dir = (work / "g" / ".speclock") if GLOBAL else (work / ".speclock")
env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
if GLOBAL:
    env["SPECLOCK_GLOBAL_HOME"] = str(home_dir)
for k in ("SPECLOCK_HOME", "SPECLOCK_URL", "SPECLOCK_KEY", "SPECLOCK_DB_URL", "SPECLOCK_KEY_FILE"):
    env.pop(k, None)

out = subprocess.run([*EXE, "init", "--project", "E2E项目", *(["--global"] if GLOBAL else [])], cwd=work, env=env, capture_output=True, text=True, encoding="utf-8").stdout
admin = re.search(r"human-[0-9a-f]{32}", out).group(0)
url = re.search(r"http://127\.0\.0\.1:\d+", out).group(0)
server = subprocess.Popen([*EXE, "serve"], cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if not cond else ""))


try:
    for _ in range(40):
        try:
            if httpx.get(url + "/api/v1/web/session", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    os.environ.update(env)
    os.environ["SPECLOCK_URL"] = url
    os.environ["SPECLOCK_KEY"] = admin
    os.chdir(work)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from speclock_mcp import server as m

    J = json.loads
    def call(raw):
        d = J(raw)
        return d.get("status"), d.get("body", d)

    s, b = call(m.whoami()); ok("admin whoami", s == 200 and b["role"] == "admin")
    s, projects = call(m.list_projects()); pid = projects[0]["id"]; ok("list_projects", s == 200 and projects[0]["name"] == "E2E项目")
    s, b = call(m.create_project("第二个项目")); p2 = b["id"]; ok("create_project", s == 201)
    s, b = call(m.rename_project(p2, "第二个项目-改名")); ok("rename_project", s == 200 and b["name"].endswith("改名"))

    files = {}
    for role, label in [("requirements-agent", "req"), ("executor-agent", "exec"), ("tester-agent", "qa"), ("scanner-agent", "scan")]:
        s, b = call(m.create_api_key(role, label, evidence="同意，建这把"))
        ok(f"create_api_key {role} -> file, no plaintext", s == 201 and b.get("key_file") and "key" not in b)
        files[label] = b["key_file"]
    s, b = call(m.create_api_key("tester-agent", "cfg", evidence="同意"))
    cfgj = b["mcp_config"]["mcpServers"]["speclock"]
    ok("create_api_key returns a ready .mcp.json using the file name and SPECLOCK_HOME", cfgj["env"]["SPECLOCK_HOME"] == str(home_dir) and "--key-file" in cfgj["args"] and "key" not in b)
    call(m.revoke_api_key(b["id"], evidence="同意"))
    ok("key files on disk", all((home_dir / "keys" / f).is_file() for f in files.values()))
    s, b = call(m.create_api_key("reviewer", "human-rev", evidence="同意"))
    ok("human key: plaintext once, no file", s == 201 and b["key"].startswith("human-") and b["key_file"] == "")

    def as_(label):
        r = J(m.use_api_key(key_file=files[label])); assert r.get("switched"), r
    as_("req")
    s, b = call(m.whoami()); ok("use_api_key(key_file) switches to requirements-agent", b["role"] == "requirements-agent")

    s, b = call(m.create_change_request(
        title="新增日报功能", intent="运营需要每天看到前一日的经营数据", expected_outcome="每天早上能看到日报",
        acceptance=[{"name": "能看到日报", "detail": "打开日报页能看到前一日销售额"}, {"name": "数据准确", "detail": "销售额与订单系统一致"}],
        impact_note="只新增，不影响现有功能", project_id=pid))
    ok("create_change_request", s == 201, str(b)); cr = b["id"]
    s, b = call(m.submit_change_request(cr)); ok("submit_change_request", s == 200 and b["status"] == "pending_review")
    h = call(m.get_change_request(cr))[1]["content_hash"]
    s, b = call(m.approve_change_request(cr, h, "同意")); ok("requirements-agent cannot approve (403)", s == 403)

    J(m.use_api_key())  # 回到管理员
    s, b = call(m.approve_change_request(cr, h, "同意，按这个来")); ok("admin approves on human's behalf", s == 200 and b["status"] == "approved", str(b))

    as_("req")
    ops = [
        {"op": "create_business", "name": "运营", "ref": "biz"},
        {"op": "create_capability", "business": "$biz", "title": "经营日报", "summary": "每日经营数据", "ref": "cap"},
        {"op": "create_block", "capability": "$cap", "title": "数据采集", "summary": "汇总前一日数据",
         "content_md": "汇总前一日的经营数据并落库，供日报页查询使用。",
         "rules": [{"name": "采集时间", "detail": "每天凌晨 2 点采集前一日数据"}],
         "apis": [{"name": "拉取日报", "api": "GET /api/daily-report", "desc": "日报页调用，拉取某日经营数据",
                   "request": [{"name": "date", "type": "string", "required": True, "description": "日期"}],
                   "response": [{"name": "sales", "type": "number", "required": True, "description": "销售额"}]}],
         "acceptance": [{"name": "凌晨采集", "detail": "凌晨 2 点后能查到前一日数据"}], "ref": "blk"},
    ]
    s, b = call(m.submit_commit(cr, ops, covers=["AC-1", "AC-2"], dry_run=True)); ok("submit_commit dry_run", s == 200 and b.get("dry_run") is True, str(b)[:200])
    s, b = call(m.submit_commit(cr, ops, covers=["AC-1", "AC-2"], change_note="首版")); ok("submit_commit", s in (200, 201), str(b)[:200])
    s, b = call(m.complete_change_request(cr)); ok("complete_change_request", s == 200 and b["status"] == "applied", str(b)[:200])

    s, idx = call(m.get_index()); ok("get_index shows the new structure", s == 200 and "经营日报" in json.dumps(idx, ensure_ascii=False))
    block_id = [bl for biz in idx for cap in biz.get("capabilities", []) for bl in cap.get("blocks", [])][0]["block_id"]
    cap_id = idx[0]["capabilities"][0]["capability_id"]
    s, b = call(m.get_block(block_id)); ok("get_block", s == 200 and b["version"] == "1.0.0")
    s, b = call(m.get_capability(cap_id)); ok("get_capability", s == 200)
    s, b = call(m.get_block_history(block_id)); ok("get_block_history", s == 200 and len(b) == 1)

    as_("exec")
    s, w = call(m.list_work(status="pending")); ok("executor sees pending work", s == 200 and len(w) == 1); wid = w[0]["block_id"]
    s, b = call(m.claim_work(wid)); ok("claim_work returns locked spec", s == 200 and b["status"] == "in_progress")
    s, b = call(m.submit_implementation(wid, [{"ac_id": "AC-1", "result": "pass", "evidence": ""}]))
    ok("submit_implementation without evidence is rejected", s in (409, 422))
    s, b = call(m.submit_implementation(wid, [{"ac_id": "AC-1", "result": "pass", "evidence": "单测：凌晨 2 点采集成功"}]))
    ok("submit_implementation", s == 200 and b["status"] == "implemented", str(b)[:200])
    s, b = call(m.verify_work(wid, [{"ac_id": "AC-1", "result": "pass", "evidence": "自测"}])); ok("executor cannot verify (403)", s == 403)

    as_("qa")
    s, b = call(m.verify_work(wid, [{"ac_id": "AC-1", "result": "pass", "evidence": "我自己跑了，凌晨采集正常"}])); ok("tester verifies", s == 200 and b["status"] == "verified", str(b)[:200])

    # 卡住 -> 新版本
    J(m.use_api_key()); as_("req")
    s, b = call(m.create_change_request(title="调整采集时间", intent="改成凌晨 3 点", expected_outcome="凌晨 3 点采集", acceptance=[{"name": "三点采集", "detail": "3 点采集"}], project_id=pid)); cr2 = b["id"]
    call(m.submit_change_request(cr2)); h2 = call(m.get_change_request(cr2))[1]["content_hash"]
    J(m.use_api_key()); call(m.approve_change_request(cr2, h2, "同意"))
    as_("req")
    s, b = call(m.submit_commit(cr2, [{"op": "update_block", "id": block_id, "rule_ops": [{"op": "upsert", "id": "R-1", "entry": {"name": "采集时间", "detail": "每天凌晨 3 点采集前一日数据"}}]}], covers=["AC-1"]))
    ok("update_block makes a new version", s in (200, 201) and b["blocks"][0]["version"] == "2.0.0", str(b)[:200])
    call(m.complete_change_request(cr2))
    s, w = call(m.list_work(status="pending")); ok("new version -> new pending work, old one superseded", len(w) == 1 and w[0]["version"] == "2.0.0")

    # 内部整理
    s, b = call(m.create_change_request(title="改个名", intent="小业务改名", expected_outcome="名字更准确", kind="internal", kind_reason="只改名，业务含义不变", acceptance=[{"name": "名字改了", "detail": "小业务名称更准确"}], project_id=pid))
    cr3 = b["id"]; ok("internal CR", s == 201 and b["kind"] == "internal")
    s, b = call(m.submit_change_request(cr3)); ok("internal CR takes effect on submit", s == 200 and b["status"] == "approved", str(b)[:200])
    s, b = call(m.submit_commit(cr3, [{"op": "update_capability", "id": cap_id, "title": "经营日报（改名）"}], covers=["AC-1"]))
    ok("internal rename commit", s in (200, 201), str(b)[:200])

    as_("scan")
    s, b = call(m.get_index()); ok("scanner can read", s == 200)
    s, b = call(m.create_change_request(title="x", intent="x", expected_outcome="x", project_id=pid)); ok("scanner cannot open CR (403)", s == 403)
    s, b = call(m.claim_work(1)); ok("scanner cannot claim work (403)", s == 403)

    J(m.use_api_key())
    s, rows = call(m.get_activity(limit=200, exclude_action="pull")); ok("get_activity has the full trail", s == 200 and {"cr_approve", "commit"} <= {r["action"] for r in rows}, str({r["action"] for r in rows}))
    s, keys = call(m.list_api_keys()); ok("list_api_keys shows files, no plaintext", s == 200 and any(k["key_file"] for k in keys))
    kid = [k["id"] for k in keys if k["label"] == "scan"][0]
    s, b = call(m.revoke_api_key(kid, evidence="同意吊销")); ok("revoke_api_key", s == 200)
    ok("revoked key file removed", not (home_dir / "keys" / files["scan"]).exists())

    web = httpx.get(url + "/api/v1/web/session").json()["key"]
    me = httpx.get(url + "/api/v1/me", headers={"X-API-Key": web}).json(); ok("web viewer key is read-only", me["role"] == "viewer")
    r = httpx.post(url + "/api/v1/projects", json={"name": "x"}, headers={"X-API-Key": web}); ok("viewer cannot write (403)", r.status_code == 403)
    ok("web served at /", httpx.get(url + "/").status_code == 200)
    ok("embed.js served", "SpecLock" in httpx.get(url + "/embed.js").text)

    # MCP 从任意目录启动也能找到 key 文件和服务地址（SPECLOCK_HOME 写死在配置里）
    elsewhere = tempfile.mkdtemp(prefix="elsewhere-")
    probe = subprocess.run(
        [sys.executable, "-c", "import speclock_mcp.server as m; print(m.BASE_URL, bool(m.CONFIGURED_KEY))"],
        cwd=elsewhere, capture_output=True, text=True, encoding="utf-8",
        env={**env, "SPECLOCK_HOME": str(home_dir), "SPECLOCK_KEY_FILE": files["exec"]},
    ).stdout.split()
    ok("MCP started from another directory finds the service and its key file", probe == [url, "True"], str(probe))

    # 环境变量里有 admin key（人在 shell 里为跑 CLI 设的）时，配了 key 文件的 MCP 仍然是自己的身份
    probe = subprocess.run(
        [sys.executable, "-c", "import speclock_mcp.server as m; print(m.KEY_SOURCE); print(m.CONFIGURED_KEY == " + repr(admin) + ")"],
        cwd=elsewhere, capture_output=True, text=True, encoding="utf-8",
        env={**env, "SPECLOCK_HOME": str(home_dir), "SPECLOCK_KEY_FILE": files["exec"], "SPECLOCK_KEY": admin},
    ).stdout.splitlines()
    ok("a leaked SPECLOCK_KEY does not override --key-file", files["exec"] in probe[0] and probe[1] == "False", str(probe))
    # use_api_key 不能借路径读到 keys/ 之外的文件
    r = J(m.use_api_key(key_file="../web.key")); ok("use_api_key refuses paths outside keys/", "error" in r and "switched" not in r)

    # 导出与备份（本机命令）
    exp = work / "exported"
    r = subprocess.run([*EXE, "export", "--out", str(exp)], cwd=work, env=env, capture_output=True, text=True, encoding="utf-8")
    ok("speclock export", r.returncode == 0 and (exp / "index.md").is_file() and "1 个模块" in r.stdout, r.stdout + r.stderr)
    r = subprocess.run([*EXE, "backup"], cwd=work, env=env, capture_output=True, text=True, encoding="utf-8")
    ok("speclock backup", r.returncode == 0 and any((home_dir / "backups").glob("*.db")), r.stdout + r.stderr)
finally:
    server.terminate()

bad = [n for n, c in checks if not c]
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)

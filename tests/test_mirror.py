"""镜像页测试（tools/build_mirror.py 生成的 Claude artifact）。
在浏览器里模拟 Claude 页面环境（window.claude.use：数据库、用户、Google Drive 连接器），中转站文件由一份数据生成：
  ① 打开就从中转站同步进镜像数据库，App 界面显示出来，没有报错
  ② 镜像里 App 代码算出的所有数字（库存、每天、合伙人、结账状态…）== 同一份数据在手机 App（public/，模拟 Firebase）里算出的（tests/golden.py 当裁判）
  ③ 只读：业务代码的写入一律被拒，镜像数据库没变
  ④ App 再上传一次（多一单）→ 点「重新读取」只写变了的那几条，新单出现在界面数据里；文件没变时不下载
  ⑤ 设置页能打开（#shezhi），备份、数据结构升级隐藏
用法：python3 tests/test_mirror.py [数据 fixture.json]   不给就用编的小数据（tests/v2_cases.js 那份，GitHub 上也跑）
"""
import os, sys, json, pathlib, subprocess, tempfile, functools, http.server, threading
from playwright.sync_api import sync_playwright

T = pathlib.Path(__file__).resolve().parent
ROOT = T.parent
tmp = pathlib.Path(tempfile.mkdtemp(prefix="fbjz-mirror-"))
if len(sys.argv) > 1:
    FIXP = pathlib.Path(sys.argv[1]).resolve()
else:
    subprocess.run(["node", str(T / "v2_cases.js")], check=True, capture_output=True)  # 顺手生成编的数据
    FIXP = pathlib.Path(tempfile.gettempdir()) / "fbjz-v2-cases.json"
FIX = json.loads(FIXP.read_text(encoding="utf8"))
fails = 0
def check(name, ok, extra=""):
    global fails
    print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra else ""))
    if not ok: fails += 1

# 裁判：手机 App（public/ + 模拟 Firebase）在同一份数据上算出的数字
ref = tmp / "ref.json"
r = subprocess.run([sys.executable, str(T / "golden.py"), str(ROOT / "public"), str(FIXP), str(ref)], capture_output=True, text=True)
assert r.returncode == 0, r.stderr[-800:]

# 镜像页（带 __GM 钩子）
page_dir = tmp / "site"; page_dir.mkdir()
subprocess.run([sys.executable, str(ROOT / "tools/build_mirror.py"), str(page_dir / "index.html"), "--hook"], check=True, capture_output=True)
COLLECT = (T / "golden.py").read_text(encoding="utf8").split('COLLECT = r"""', 1)[1].split('"""', 1)[0]

def relay_of(fx, at):
    data = {c: dict(fx.get(c) or {}) for c in ["items", "orders", "movements", "expenses", "purchases", "transfers", "settlements", "customers", "followups"]}
    data["log"] = {"l-t-1": {"at": "2026-11-15T00:00:00.000Z", "by": "u1", "op": "新增", "col": "orders", "ref": "x", "text": "测试记录"}}
    data["meta"] = {"schema": {"version": 2}}  # App 迁移后上传的文件里有这个；镜像不能照抄（不然会去读 v2_*）
    return {"format": "fb-jizhang-relay/1", "uploaded_at": at, "saved_at": at, "uploaded_by": "测试", "counts": {c: len(v) for c, v in data.items()},
            "last_record": {"at": at, "collection": "orders", "id": "x", "text": "测试"}, "data": data}

MOCK = r"""
(() => {
  const store = {}, subs = new Set(); window.__store = store; window.__writes = []; window.__downloads = 0;
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const split = (p) => { const i = p.lastIndexOf("/"); return [p.slice(0, i), p.slice(i + 1)]; };
  const docSnap = (p) => { const [, id] = split(p); const v = store[p]; return { id, exists: !!v, data: () => v ? clone(v) : undefined }; };
  const fire = () => setTimeout(() => subs.forEach((f) => f()), 0);
  const query = (col, fs = [], ord = null, lim = 0) => {
    const run = () => {
      let rows = Object.keys(store).filter((p) => split(p)[0] === col).map((p) => ({ id: split(p)[1], v: store[p] }));
      for (const [f, op, val] of fs) rows = rows.filter((r) => op === "==" ? r.v[f] === val : op === ">" ? r.v[f] > val : op === "in" ? val.includes(r.v[f]) : true);
      if (ord) rows.sort((a, b) => (a.v[ord[0]] < b.v[ord[0]] ? -1 : 1) * (ord[1] === "desc" ? -1 : 1));
      if (lim) rows = rows.slice(0, lim);
      const docs = rows.map((r) => ({ id: r.id, exists: true, data: () => clone(r.v) }));
      return { docs, size: docs.length, empty: !docs.length, forEach: (f) => docs.forEach(f) };
    };
    return { where: (f, op, v) => query(col, fs.concat([[f, op, v]]), ord, lim), orderBy: (f, d) => query(col, fs, [f, d || "asc"], lim), limit: (n) => query(col, fs, ord, n),
      get: async () => run(), onSnapshot: (cb) => { const f = () => cb(run()); subs.add(f); setTimeout(f, 0); return () => subs.delete(f); }, doc: (id) => doc(col + "/" + id) };
  };
  const doc = (p) => ({ id: split(p)[1], get: async () => docSnap(p), onSnapshot: (cb) => { const f = () => cb(docSnap(p)); subs.add(f); setTimeout(f, 0); return () => subs.delete(f); },
    set: async (d) => { store[p] = clone(d); window.__writes.push(p); fire(); }, update: async (d) => { store[p] = Object.assign(store[p] || {}, clone(d)); window.__writes.push(p); fire(); },
    delete: async () => { delete store[p]; window.__writes.push("-" + p); fire(); } });
  const db = Object.freeze({ doc, collection: (c) => query(c) });
  const user = Object.freeze({ id: async () => "u_owner", me: async () => ({ id: "u_owner" }), isOwner: async () => true, canEdit: async () => true, can: async () => true, profiles: async (ids) => Object.fromEntries(ids.map((i) => [i, { name: "" }])) });
  const mcp = Object.freeze({ callTool: async (server, tool, input) => {
    const R = window.__relay;
    if (tool === "search_files") return { payload: { files: [{ id: "f1", title: "最新数据.json", mimeType: "application/json", modifiedTime: R.mod }] } };
    if (tool === "download_file_content") { window.__downloads++; const bytes = new TextEncoder().encode(JSON.stringify(R.body)); let s = ""; bytes.forEach((b) => s += String.fromCharCode(b)); return { payload: { content: btoa(s) } }; }
    throw { code: "tool_error" };
  } });
  const caps = { db, user, mcp };
  window.claude = Object.freeze({ use: (n) => Promise.resolve(caps[n] || null) });
})();
"""

class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(page_dir)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 390, "height": 844})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.add_init_script("window.__relay=" + json.dumps({"mod": "2026-11-15T01:00:00.000Z", "body": relay_of(FIX, "2026-11-15T01:00:00.000Z")}, ensure_ascii=False) + ";" + MOCK)
    pg.goto(url)
    pg.wait_for_function("window.__store['meta/mirror'] && window.__GM && window.__GM.S.orders.length > 0", timeout=60000)
    pg.wait_for_timeout(1500)
    n0 = len(pg.evaluate("window.__writes"))
    bar = pg.inner_text("#mirror-bar")
    check("① 打开就从中转站同步，界面显示出来", "App 数据截至" in bar and pg.is_visible("#inv-view"), bar.replace("\n", " ")[:80])
    check("① 中转站文件里的 meta（数据结构版本）没抄进镜像，App 走旧样子", not pg.evaluate("Object.keys(window.__store).some((p) => p.startsWith('meta/schema') || p.startsWith('v2_'))"))
    check("① 页面没有报错", not errs, errs[:3])

    got = pg.evaluate(COLLECT)
    want = json.loads(ref.read_text(encoding="utf8"))
    want["counts"]["log"] = got["counts"].get("log")  # 镜像多了中转站里的操作记录，手机那边测试数据里没有
    diff = [k for k in want if json.dumps(want[k], sort_keys=True, ensure_ascii=False) != json.dumps(got.get(k), sort_keys=True, ensure_ascii=False)]
    check("② 镜像算出的数字 == 手机 App 算出的（库存、每天、合伙人、结账状态、客户…）", not diff, diff)
    check("   库存总根数一样", sum(got["st"].values()) == sum(want["st"].values()), (sum(got["st"].values()), sum(want["st"].values())))

    ro = pg.evaluate("""async () => { const db = await __M.use("db"); const before = JSON.stringify(window.__store);
      const res = []; for (const f of [() => db.doc("items/XF-01").set({x: 1}), () => db.collection("orders").doc("o-x").set({}), () => db.doc("orders/o-x").update({}), () => db.doc("items/XF-01").delete(), () => db.batch().commit()])
        { try { await f(); res.push("ok"); } catch (e) { res.push(e.code); } }
      return { res, same: before === JSON.stringify(window.__store) }; }""")
    check("③ 只读：写入一律被拒（read_only），镜像数据库没变", ro["same"] and set(ro["res"]) == {"read_only"}, ro)
    # 在界面上真的点一次保存：拿快速下单记一笔
    pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300)
    if pg.is_visible("#fin-sale"):
        pg.click("#fin-sale"); pg.wait_for_timeout(300)
        it = pg.evaluate("(() => { const st = window.__GM.derive().st; const i = window.__GM.S.items.find((i) => st[i.sku] >= 1 && i.variant); return i && i.variant; })()")
        if it:
            pg.fill("#f-skuq-0", it); pg.press("#f-skuq-0", "Enter")
            nw = len(pg.evaluate("window.__writes"))
            pg.check('input[name="f-payr"][value="现金"]'); pg.click("#sheet-save"); pg.wait_for_timeout(800)
            check("③ 界面上点「保存」：没写进数据库，顶上提示只读", len(pg.evaluate("window.__writes")) == nw and "要改请在手机 App 里改" in pg.inner_text("#mirror-bar"), (pg.inner_text("#mirror-bar")[:60], pg.evaluate("window.__writes.length") - nw, errs[:2]))
        pg.keyboard.press("Escape")

    # ④ 文件没变：不下载；App 再上传一次（多一单）：只写变了的
    d0 = pg.evaluate("window.__downloads")
    pg.click("#mb-go", force=True); pg.wait_for_timeout(1500)  # 强制重新读取：会下载，但没有记录变化
    w1 = pg.evaluate("window.__writes").__len__()
    check("④ 文件内容没变时重新读取：数据记录一条都不重写", all(not x.split("/")[0] in ("orders", "items", "movements") for x in pg.evaluate("window.__writes")[n0:]), pg.evaluate("window.__writes")[n0:][:5])
    fx2 = json.loads(json.dumps(FIX)); oid = "o-20261115-mirr01"
    any_sku = sorted(fx2["items"])[0]
    fx2["orders"][oid] = {"date": "2026-11-15", "at": "2026-11-15T01:30:00.000Z", "status": "sold", "customer": "镜像测试", "lines": [{"sku": any_sku, "name": "x", "qty": 1, "unit_price": 60}], "total": 60, "payment": "现金"}
    pg.evaluate("(r) => { window.__relay = r; }", {"mod": "2026-11-15T01:31:00.000Z", "body": relay_of(fx2, "2026-11-15T01:31:00.000Z")})
    pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # 切回页面会查；10 秒节流，这里直接点按钮
    pg.click("#mb-go", force=True)
    pg.wait_for_function(f"window.__GM.S.orders.some((o) => o.id === '{oid}')", timeout=15000)
    new_w = [x for x in pg.evaluate("window.__writes")[w1:] if not x.startswith("meta/")]
    check("④ App 多记一单 → 镜像只写那一条，新单出现在界面数据里", new_w == ["orders/" + oid], new_w)
    try: pg.wait_for_function("document.getElementById('mb-text').textContent.includes('刚更新')", timeout=10000)
    except Exception: pass
    check("④ 顶上显示新数据的时间", "刚更新" in pg.inner_text("#mirror-bar"), pg.inner_text("#mirror-bar")[:60])

    pg.evaluate("location.hash = '#shezhi'"); pg.wait_for_timeout(400)
    check("⑤ 设置页能打开；备份、数据结构升级隐藏", pg.is_visible("#set-view") and not pg.is_visible("#mig-sec") and not pg.is_visible("#bk-btn"))
    check("⑤ 全程页面没有报错", not errs, errs[:3])
    b.close()

print("全部通过" if not fails else f"{fails} 项没通过")
sys.exit(1 if fails else 0)

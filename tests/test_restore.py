"""备份能不能真的恢复：演练「备份 → 云端的账被弄坏 → 从备份恢复 → 回到一模一样的账」（从旧结构、新结构各开始一遍）。
1. 设置页「备份到 Google Drive」：除了 Excel，还存一份整份数据的 JSON（恢复用）
2. 把云端弄坏（删订单、改往来单价、多出一张假订单）
3. import.html：只核对 → 报不一样；恢复 → 逐字段跟备份一样，数据结构回到旧结构
4. 打开 App：库存、收入、成本、净赚、合伙人账跟备份时一样；再「数据结构升级」回新结构，还是一样
用编出来的小数据，GitHub 上也跑。可以给一份真实数据（旧样子的 fixture，放仓库外）：python3 tests/test_restore.py [fixture.json]"""
import os, re, sys, json, hashlib, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive, finBook, partnerNames, ledgerNet };\n})();"
OWNER = hashlib.sha256(b"test@example.com").hexdigest()
TOKEN = "localStorage.setItem('fb-gtoken', JSON.stringify({ t: 'tok', exp: Date.now() + 3600e3, sc: 'https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly' })); localStorage.setItem('fb-drive-folder', 'folder1');"
D = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date() - datetime.timedelta(days=3)).isoformat()
A, B = "合伙人甲", "合伙人乙"
LEDGER = ["items", "movements", "orders", "expenses", "purchases", "settlements", "transfers", "customers", "followups"]

if len(sys.argv) > 1:
    V1 = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf8")); V1["meta"] = {"backfill": {"done": True}}
else:
    item = lambda sku, ser, en: (sku, {"sku": sku, "series": ser, "variant": en, "name": en, "price_aud": 60, "cost_aud": 30, "status": "在售"})
    at = lambda h: D + f"T0{h}:00:00Z"
    V1 = {
        "items": dict([item("XF-01", "Bar Pro", "Banana Buzz"), item("XF-02", "Bar Pro", "Grape Ice"), item("XF-03", "Ali", "Cool Mint")]),
        "movements": {
            "b-0-XF-01": {"type": "in", "sku": "XF-01", "name": "Banana Buzz", "qty": 6, "cost": 180, "date": D, "at": at(1), "batch_id": "b-0", "expense_id": "b-0-cost", "note": "进货"},
            "o-1-XF-01": {"type": "out", "sku": "XF-01", "name": "Banana Buzz", "qty": 2, "date": D, "at": at(2), "order_id": "o-1"},
            "o-2-XF-02": {"type": "out", "sku": "XF-02", "name": "Grape Ice", "qty": 1, "date": D, "at": at(3), "order_id": "o-2"},
            "o-2-pick-XF-02": {"type": "in", "sku": "XF-02", "name": "Grape Ice", "qty": 1, "cost": 30, "date": D, "at": at(3), "order_id": "o-2", "batch_id": "o-2-pick", "expense_id": "o-2-pick-cost", "note": "按单向合伙人拿货"},
            "o-3-XF-02": {"type": "out", "sku": "XF-02", "name": "Grape Ice", "qty": 1, "date": D, "at": at(4), "order_id": "o-3"},
            "o-3-pick-XF-02": {"type": "in", "sku": "XF-02", "name": "Grape Ice", "qty": 1, "cost": 30, "date": D, "at": at(4), "order_id": "o-3", "batch_id": "o-3-pick", "expense_id": "o-3-pick-cost", "note": "按单向合伙人拿货"},
            "t-1-out-XF-01": {"type": "adjust", "sku": "XF-01", "name": "Banana Buzz", "qty": -1, "date": D, "at": at(5), "transfer_id": "t-1", "note": "合伙人往来：给 " + B},
            "t-2-in-XF-03": {"type": "in", "sku": "XF-03", "name": "Cool Mint", "qty": 2, "cost": 100, "date": D, "at": at(6), "transfer_id": "t-2", "note": "合伙人往来：" + A + " 给的"},
        },
        "expenses": {
            "b-0-cost": {"date": D, "at": at(1), "amount": 180, "category": "进货成本", "note": "进货", "batch_id": "b-0"},
            "o-2-pick-cost": {"date": D, "at": at(3), "amount": 30, "category": "进货成本", "note": "按单拿货 Grape Ice ×1", "batch_id": "o-2-pick"},
            "o-3-pick-cost": {"date": D, "at": at(4), "amount": 30, "category": "进货成本", "note": "按单拿货 Grape Ice ×1", "batch_id": "o-3-pick"},
            "x-1": {"date": D, "at": at(7), "amount": 12.5, "category": "油费", "note": "油费"},
        },
        "orders": {
            "o-1": {"status": "paid", "date": D, "at": at(2), "lines": [{"sku": "XF-01", "name": "Banana Buzz", "qty": 2, "unit_price": 60}], "delivery_fee": 10, "note": "", "payment": "现金", "customer": "测试客人"},
            "o-2": {"status": "paid", "date": D, "at": at(3), "lines": [{"sku": "XF-02", "name": "Grape Ice", "qty": 1, "unit_price": 60}], "delivery_fee": 0, "note": "", "payment": "PayID", "pick_from": A, "partner_settlement_id": "s-1"},
            "o-3": {"status": "paid", "date": D, "at": at(4), "lines": [{"sku": "XF-02", "name": "Grape Ice", "qty": 1, "unit_price": 55}], "delivery_fee": 0, "note": "", "payment": "现金", "pick_from": B},
        },
        "transfers": {
            "t-1": {"date": D, "at": at(5), "partner": B, "out": [{"sku": "XF-01", "name": "Banana Buzz", "qty": 1, "unit": 36}], "in": [], "note": ""},
            "t-2": {"date": D, "at": at(6), "partner": A, "out": [], "in": [{"sku": "XF-03", "name": "Cool Mint", "qty": 2, "unit": 50}], "note": ""},
        },
        "settlements": {"s-1": {"date": D, "at": at(8), "order_ids": ["o-2"], "transfer_ids": [], "po_ids": [], "qty": {"Bar Pro": 1}, "amount": 30, "paid": 30, "partner": A, "payment": "现金", "note": ""}},
        "purchases": {}, "customers": {}, "followups": {},
        "meta": {"backfill": {"done": True}},
    }
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8"))
# 迁移过的手机：旧集合还留着迁移那一刻的样子，新结构才是现在的账
# （最后一单是迁移以后才记的 → 旧集合里没有它，恢复时要真的写进去）
LATE = sorted(V1["orders"], key=lambda k: V1["orders"][k].get("at") or "")[-1]
stale = {c: dict(V1.get(c, {})) for c in LEDGER}
stale["orders"].pop(LATE)
stale["movements"] = {k: v for k, v in stale["movements"].items() if v.get("order_id") != LATE}
stale["expenses"] = {k: v for k, v in stale["expenses"].items() if v.get("batch_id") != LATE + "-pick"}
V2 = dict(stale, **V2); V2["meta"] = {"schema": {"version": 2, "migrated_at": D + "T09:00:00.000Z"}, "backfill": {"done": True}}


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def text(self, body, ctype):
        b = body.encode("utf8"); self.send_response(200); self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();"); return self.text(src[:i] + EXPOSE + src[i + 5:], "text/html")
        if path == "/firebase-config.js":
            return self.text(re.sub(r"owners:\s*\[[^\]]*\]", f'owners: ["{OWNER}"]', (PUB / "firebase-config.js").read_text(encoding="utf8")), "text/javascript")
        return super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)[:300]) if extra and not ok else ""))

NUMS = """() => { const G = window.__GM, D = G.derive(), F = G.finBook(() => true), o = { stock: JSON.stringify(Object.entries(D.st).filter((x) => x[1]).sort()), n: F.T.n, rev: F.T.rev, cost: F.T.cost, net: F.T.net, buy: F.T.buy, opex: F.T.opex };
  for (const w of G.partnerNames()) o["p:" + w] = G.ledgerNet(w); return o; }"""
N_ORD = len(V1["orders"])
def ready(pg):
    pg.wait_for_function(f"window.__GM && window.__GM.S.loaded && window.__GM.S.orders.length >= {max(1, N_ORD - 1)} && window.__GM.S.moves.length > 0", timeout=20000); pg.wait_for_timeout(900)

uploads = []
def drive(route):
    req = route.request
    if "/upload/drive/v3/files" in req.url and req.method == "POST":
        body = req.post_data_buffer; bd = re.search(rb"boundary=([^;]+)", req.headers.get("content-type", "").encode()).group(1)
        parts = [p.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0] for p in body.split(b"--" + bd) if b"\r\n\r\n" in p]
        uploads.append((json.loads(parts[0])["name"], parts[1]))
        return route.fulfill(status=200, content_type="application/json", body=json.dumps({"id": "file%d" % len(uploads), "webViewLink": "https://drive.google.com/file/d/file%d/view" % len(uploads)}))
    return route.fulfill(status=200, content_type="application/json", body='{"files":[]}')


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode, seed in (("旧结构", V1), ("新结构", V2)):
        print("== 从" + mode + "开始")
        uploads.clear()
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        pg = ctx.new_page(); pg.set_default_timeout(10000)
        pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.on("dialog", lambda d: d.accept())
        pg.add_init_script("window.__MOCK_PERSIST = true; window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";" + TOKEN)
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("https://www.googleapis.com/**", drive)
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url and "www.googleapis.com" not in r.request.url else r.fallback())
        pg.goto(BASE + "/index.html"); ready(pg)
        check("用的是" + mode, pg.evaluate("!!window.__fbV2store") == (mode == "新结构"))
        n0 = pg.evaluate(NUMS)

        # 1. 备份
        pg.evaluate("location.hash = '#settings'"); pg.wait_for_timeout(600)
        pg.click("#bk-btn"); pg.wait_for_function("uploadsDone => document.getElementById('toast').textContent.includes('整份数据') || !document.getElementById('bk-msg').hidden", timeout=15000)
        names = [n for n, _ in uploads]
        check("备份存了两份：Excel + 整份数据 JSON", len(uploads) == 2 and names[0].endswith(".xlsx") and names[1].endswith(".json") and "整份数据" in names[1], names + [pg.inner_text("#bk-msg")])
        raw = next((b for n, b in uploads if n.endswith(".json")), b"{}"); bk = json.loads(raw.decode("utf8"))
        check("JSON 里是全部账本记录（旧样子），没有内部字段", bk.get("format") == "fb-jizhang-backup/1" and all(len(bk["data"].get(c, {})) == len(V1.get(c, {})) for c in LEDGER) and '"_u":' not in raw.decode("utf8") and '"_v":' not in raw.decode("utf8"), {c: len(bk.get("data", {}).get(c, {})) for c in LEDGER})
        pg.wait_for_timeout(400)
        check("设置页记下了这份备份", pg.evaluate("(() => { const s = __server('meta').sync; return !!(s && s.files && s.files.data && s.files.data.id && s.files.workbook); })()"))
        f = tmp / ("backup-" + ("v2" if mode == "新结构" else "v1") + ".json"); f.write_bytes(raw)

        # 2. 把云端弄坏
        oid = sorted(bk["data"]["orders"])[0]; tid = sorted(bk["data"]["transfers"])[0] if bk["data"]["transfers"] else None
        pre = "v2_" if mode == "新结构" else ""
        pg.evaluate("""([pre, oid, tid]) => { __remoteWrite(pre + 'orders', oid, null);
          if (tid) { const t = JSON.parse(JSON.stringify(__server(pre + 'transfers')[tid])); for (const l of (t.out || []).concat(t.in || [])) l.unit = 999; __remoteWrite(pre + 'transfers', tid, t); }
          __remoteWrite(pre + 'orders', 'o-junk', { status: 'paid', date: '2026-01-01', at: '2026-01-01T00:00:00Z', lines: [], delivery_fee: 77, note: '假的', payment: '现金' }); }""", [pre, oid, tid])
        pg.wait_for_timeout(900)
        n_bad = pg.evaluate(NUMS)
        check("云端被弄坏了（数字变了）", n_bad != n0)

        # 3. 导入页：只核对 → 恢复
        pg.goto(BASE + "/import.html"); pg.wait_for_timeout(600)
        pg.set_input_files("#f", str(f)); pg.wait_for_function("!document.getElementById('check').disabled", timeout=8000)
        pg.click("#check"); pg.wait_for_function("/✓|✗|读不到/.test(document.getElementById('out').textContent)", timeout=20000)
        out = pg.inner_text("#out")
        check("只核对：看出云端跟备份不一样（缺的、不一样的、多出来的）", "✗" in out and "云端缺 1" in out and "云端多出 1" in out and ("不一样" in out or not tid), out[-300:])
        pg.click("#go"); pg.wait_for_function("/✓|✗|没做完/.test(document.getElementById('out').textContent)", timeout=60000)
        out = pg.inner_text("#out")
        check("恢复：全部记录跟备份逐字段一样", "✓ 恢复好了" in out, out[-400:])
        if mode == "新结构": check("迁移以后才记的那一单也写回旧集合了", pg.evaluate("(o) => { const x = __server('orders')[o]; return !!x && !x._deleted; }", LATE) and "orders：写了 0 条" not in out, out[:200])
        srv_now = pg.evaluate("(cols) => Object.fromEntries(cols.map((c) => [c, Object.fromEntries(Object.entries(__server(c)).filter(([, v]) => !v._deleted).map(([k, v]) => { const x = JSON.parse(JSON.stringify(v)); delete x._u; return [k, x]; }))]))", LEDGER)
        norm = lambda d: json.loads(json.dumps(d, sort_keys=True), object_hook=lambda o: {k: v for k, v in o.items() if v is not None})
        check("云端旧集合 = 备份（自己再比一遍）", norm(srv_now) == norm({c: bk["data"].get(c, {}) for c in LEDGER}), [c for c in LEDGER if norm(srv_now[c]) != norm(bk["data"].get(c, {}))])
        check("数据结构版本回到 1", pg.evaluate("__server('meta').schema.version") == 1)

        # 4. 打开 App：账回来了
        pg.goto(BASE + "/index.html"); ready(pg)
        check("App 用旧结构打开", not pg.evaluate("!!window.__fbV2store"))
        n1 = pg.evaluate(NUMS)
        check("库存、收入、成本、净赚、合伙人账跟备份时一样", n1 == n0, f"{n0} → {n1}")
        # 再升级回新结构
        pg.evaluate("location.hash = '#settings'"); pg.wait_for_selector("#mig-sec:not([hidden])", timeout=8000)
        pg.click("#mig-check"); pg.wait_for_timeout(600)
        check("检查迁移：全部一致", "全部一致" in pg.inner_text("#mig-out"), pg.inner_text("#mig-out")[:200])
        pg.click("#mig-go"); pg.click("#mig-go")
        pg.wait_for_function("window.__fbV2store", timeout=15000); ready(pg)
        n2 = pg.evaluate(NUMS)
        check("升级回新结构后还是一样", n2 == n0, f"{n0} → {n2}")
        check("新结构里没有弄坏时留下的假订单", "o-junk" not in pg.evaluate("Object.entries(__server('v2_orders')).filter(([, v]) => !v._deleted).map(([k]) => k)"))
        ctx.close()

    # 5. 选错文件
    ctx = br.new_context(service_workers="block"); pg = ctx.new_page()
    pg.add_init_script("window.__SEED = {};")
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.goto(BASE + "/import.html")
    bad = tmp / "bad.json"; bad.write_text(json.dumps({"format": "fb-jizhang-changes/1", "changes": []}), encoding="utf8")
    pg.set_input_files("#f", str(bad)); pg.wait_for_timeout(500)
    check("选了别的文件（比如改动清单）：不让恢复", "用不了" in pg.inner_text("#out") and pg.is_disabled("#go"))
    empty = tmp / "empty.json"; empty.write_text(json.dumps({"format": "fb-jizhang-backup/1", "data": {c: {} for c in LEDGER}}), encoding="utf8")
    pg.set_input_files("#f", str(empty)); pg.wait_for_timeout(500)
    check("空的备份：不让恢复（不然会把账清空）", pg.is_disabled("#go"), pg.inner_text("#out"))
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

"""客人少给 / 多给（2026-11-17 Bowen：客人结账时少给了配送费，记下来，下次跟他记单时提醒收回来；多给了下次提醒少收）
- 记一单时「客人少给 / 多给了钱？」→ 少给 $30（配送费没给）存在那一单的 bal 上；没写客户名字不让存（下次没法提醒）
- 下次给同一个人记单（名字不分大小写）：提醒「上次少给你 $30」+「这单一起收回来」，勾上后写「这次实际收 $90（合计 $60 + 上次少给的 $30）」，存了就两清
- 多给：结算预定时记「客人多给了 $20」；下一个预定只提醒不能当场抵；结算那单时勾「这单少收 $20 抵掉」→ 两清
- 预定上就能记（11-17 Bowen：在预定那里点「编辑」要能看到）：卡片标「这单少给 $10」；还没结算不算进这个客人欠的；
  结算时写「这次实际收 $50（合计 $60 − 这单少给的 $10）」，已选好付款方式也先弹出来；结算后下次提醒
- 卖出以后才想起来：编辑那一单补记；客户页显示「少给你 $X」、「不追了」点两下清掉
- 收入、净赚照订单合计算，不受影响；新结构下 bal 照样存得住（迁移成新结构再算回来一字不差）
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_cust_bal.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
V1 = {"items": {"XF-01": {"sku": "XF-01", "series": "Ali", "variant": "Apple", "name": "苹果", "price_aud": 60, "cost_aud": 20, "status": "在售"}},
      "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "苹果", "qty": 50, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货", "cost": 1000}},
      "orders": {}, "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {}}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}

EXPOSE = "\nwindow.__GM = { S };\n})();"  # 测试要读 S：在 index.html 最后那个 })(); 前面挂出来
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();")
            b = (src[:i] + EXPOSE + src[i + 5:]).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        return super().do_GET()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))

go = lambda pg, h: (pg.evaluate(f"location.hash = '#{h}'"), pg.wait_for_timeout(250))
ids = lambda pg: set(pg.evaluate("window.__GM.S.orders.map((x) => x.id)"))
order = lambda pg, oid: pg.evaluate("(id) => window.__GM.S.orders.find((o) => o.id === id)", oid)
bal = lambda pg, name: pg.evaluate("(n) => window.__GM.S.orders.filter((o) => (o.customer || '').trim().toLowerCase() === n.toLowerCase()).reduce((a, o) => a + (o.bal || []).reduce((s, e) => s + e.amt, 0), 0)", name)
txt = lambda pg, sel: pg.evaluate("(s) => { const e = document.querySelector(s); return e && !e.hidden ? e.innerText.replace(/\\s+/g, ' ').trim() : ''; }", sel)

def save(pg):
    pg.wait_for_timeout(250); pg.click("#sheet-save")
    try: pg.wait_for_selector("#sheet", state="hidden", timeout=3000)
    except Exception: pass
    pg.wait_for_timeout(450)

def sale(pg, cust, qty=1, resv=False, fn=None, keep_open=False):
    before = ids(pg); go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
    pg.fill("#f-skuq-0", "苹果"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", str(qty))
    if resv: pg.check("#f-resv")
    else: pg.click('#f-paychips label:has(input[value="现金"])')
    if cust: pg.locator("#f-cust").press_sequentially(cust); pg.wait_for_timeout(150)
    if fn: fn(pg)
    if keep_open: return None
    save(pg); new = sorted(ids(pg) - before)
    return new[0] if new else None

def diff(pg, k, amt, why):
    pg.click("#f-diff-open"); pg.click(f'#f-diff label:has(input[value="{k}"])'); pg.fill("#f-diffamt", str(amt))
    if why in ("配送费没给", "没有零钱", "抹零"): pg.click(f'[data-diffwhy="{why}"]')
    else: pg.fill("#f-diffwhy", why)

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
        print("== " + mode)

        # 1. 少给：没写名字不让存
        sale(pg, "", fn=lambda pg: diff(pg, "1", 30, "配送费没给"), keep_open=True)
        pg.click("#sheet-save"); pg.wait_for_timeout(400)
        check("记少给但没写客户名字：不让存，写明要先写名字", pg.is_visible("#sheet") and "客户名字" in pg.inner_text("#sheet-err"), pg.inner_text("#sheet-err") if pg.is_visible("#sheet-err") else "")
        pg.locator("#f-cust").press_sequentially("Amy"); save(pg)
        o1 = [o for o in pg.evaluate("window.__GM.S.orders") if o.get("customer") == "Amy"]
        check("写上名字就存了：那一单 bal = 少给 $30（配送费没给）", len(o1) == 1 and o1[0].get("bal") and o1[0]["bal"][0]["amt"] == 30 and o1[0]["bal"][0]["why"] == "配送费没给" and o1[0]["bal"][0]["kind"] == "diff", o1[0].get("bal") if o1 else None)
        go(pg, "finance")
        check("收入照订单合计算：$60（少给的 $30 不影响）", "$60" in pg.inner_text("#f-inc"), pg.inner_text("#f-inc"))

        # 2. 下次记单：提醒 + 收回来
        sale(pg, "amy", fn=lambda pg: None, keep_open=True); pg.wait_for_timeout(200)
        r = txt(pg, "#f-balold")
        check("下次给 amy（大小写不同）记单：提醒「上次少给你 $30」，写明哪天、为什么", "上次少给你 $30" in r and "配送费没给" in r and "这单一起收回来" in r, r)
        check("没勾之前：不写「实际收」", txt(pg, "#f-baltot") == "")
        pg.check("#f-baltake"); pg.wait_for_timeout(150)
        check("勾上：这次实际收 $90（合计 $60 + 上次少给的 $30）", txt(pg, "#f-baltot") == "这次实际收 $90（合计 $60 + 上次少给的 $30）", txt(pg, "#f-baltot"))
        save(pg)
        check("存了：amy 两清（$30 − $30 = 0）", bal(pg, "amy") == 0, bal(pg, "amy"))
        sale(pg, "Amy", keep_open=True); pg.wait_for_timeout(150)
        check("两清以后再记单：不再提醒", txt(pg, "#f-balold") == "")
        pg.click("#sheet-close"); pg.wait_for_timeout(250)

        # 3. 多给：结算预定时记；下一个预定只提醒；结算时抵掉
        r1 = sale(pg, "Ben", qty=2, resv=True)
        go(pg, "customers"); pg.evaluate(f"""() => document.querySelector('[data-settle="{r1}"]').click()"""); pg.wait_for_selector("#f-diff-open")
        check("结算预定（选付款方式那一页）也能记少给 / 多给", pg.inner_text("#sheet-title").startswith("结算"))
        pg.click('#sheet label.chip:has(input[value="现金"])'); diff(pg, "-1", 20, "没有零钱"); save(pg)
        check("结算预定时记「客人多给了 $20」：Ben 欠 −20（你欠他）", order(pg, r1)["status"] == "paid" and bal(pg, "Ben") == -20, (order(pg, r1).get("bal"), bal(pg, "Ben")))
        r2 = sale(pg, "ben", resv=True, keep_open=True, fn=lambda pg: pg.click('#f-paychips label:has(input[value="现金"])')); pg.wait_for_timeout(150)
        r = txt(pg, "#f-balold")
        check("下一个预定：提醒「上次多给了你 $20」，不能当场抵（还没付钱）；记少给多给的入口还在", "上次多给了你 $20" in r and "结算的时候" in r and pg.locator("#f-baltake").count() == 0 and pg.is_visible("#f-diff-open"), r)
        save(pg); r2 = sorted(ids(pg) - {o["id"] for o in pg.evaluate("window.__GM.S.orders") if o.get("status") == "paid" or o["id"] == r1})[0]
        go(pg, "customers")
        check("预定卡片上标「上次多给 $20」", "上次多给 $20" in pg.evaluate(f"""() => document.querySelector('[data-settle="{r2}"]').closest('details').innerText"""))
        pg.evaluate(f"""() => document.querySelector('[data-settle="{r2}"]').click()"""); pg.wait_for_timeout(600)
        check("这个预定已经选好付款方式（平时点「结算」直接结掉）：因为 ben 上次多给了，先弹出来提醒", pg.is_visible("#f-baltake") and order(pg, r2)["status"] == "reserved")
        pg.check("#f-baltake"); pg.wait_for_timeout(150)
        check("勾「这单少收 $20 抵掉」→ 这次实际收 $40（合计 $60 − 上次多给的 $20）", txt(pg, "#f-baltot") == "这次实际收 $40（合计 $60 − 上次多给的 $20）", txt(pg, "#f-baltot"))
        save(pg)
        check("存了：Ben 两清", bal(pg, "Ben") == 0, bal(pg, "Ben"))

        # 4. 卖出以后才想起来：编辑那一单补记；客户页显示；不追了
        o3 = sale(pg, "Cara")
        go(pg, "finance"); pg.evaluate(f"""() => document.querySelector('[data-edit-order="{o3}"]').click()"""); pg.wait_for_selector("#f-diff-open")
        diff(pg, "1", 15, "抹零"); save(pg)
        check("编辑已卖出的单补记「少给 $15（抹零）」", (order(pg, o3).get("bal") or [{}])[0].get("amt") == 15, order(pg, o3).get("bal"))
        go(pg, "customers"); pg.fill("#cq", "cara"); pg.wait_for_timeout(250)
        check("客户页 Cara 那一行标「少给你 $15」", "少给你 $15" in pg.inner_text("#c-list"))
        pg.click("#c-list [data-cu]"); pg.wait_for_timeout(250)
        check("点开写明「上次少给你 $15：…抹零」和这单的记录", "上次少给你 $15" in pg.inner_text("#c-list") and "抹零" in pg.inner_text("#c-list") and "少给 $15" in pg.inner_text("#c-list .cu-hist2"))
        pg.click("[data-cu-waive]"); pg.wait_for_timeout(200)
        check("「不追了」点第一下只是问一下（不弹浏览器确认框）", bal(pg, "Cara") == 15 and "再点一下" in pg.inner_text("[data-cu-waive]"))
        pg.click("[data-cu-waive]"); pg.wait_for_timeout(500)
        check("再点一下：Cara 清掉、不再提醒", bal(pg, "Cara") == 0 and "少给你" not in pg.inner_text("#c-list"), bal(pg, "Cara"))
        sale(pg, "Cara", keep_open=True); pg.wait_for_timeout(150)
        check("不追了以后再给 Cara 记单：不提醒", txt(pg, "#f-balold") == "")
        pg.click("#sheet-close"); pg.wait_for_timeout(250)

        # 4b. 预定上记：点预定的「编辑」就能记少给 / 多给
        r4 = sale(pg, "Dan", resv=True, fn=lambda pg: pg.click('#f-paychips label:has(input[value="现金"])'))
        go(pg, "customers"); pg.evaluate(f"""() => document.querySelector('[data-settle="{r4}"]').closest('details').querySelector('[data-edit-order]').click()"""); pg.wait_for_timeout(400)
        check("预定点「编辑」：看得到「客人少给 / 多给了钱？」", pg.is_visible("#f-diff-open"))
        diff(pg, "1", 10, "配送费没给"); pg.wait_for_timeout(150)
        check("编辑预定时填了少给 $10：合计下面马上写「这次实际收 $50（合计 $60 − 这单少给的 $10）」", txt(pg, "#f-baltot") == "这次实际收 $50（合计 $60 − 这单少给的 $10）", txt(pg, "#f-baltot"))
        save(pg)
        o4 = order(pg, r4)
        check("存在预定上：bal = 少给 $10，还是预定", o4["status"] == "reserved" and (o4.get("bal") or [{}])[0].get("amt") == 10, o4.get("bal"))
        go(pg, "customers")
        card = pg.evaluate(f"""() => document.querySelector('[data-settle="{r4}"]').closest('details').innerText""")
        check("预定卡片标「这单少给 $10：配送费没给」", "这单少给 $10" in card and "配送费没给" in card, card[:200])
        pg.fill("#cq", "dan"); pg.wait_for_timeout(250)
        check("还没结算：不算进 Dan 欠你的（客户页 Dan 那一行不标「少给你」）", "上次少给" not in card and "Dan" in pg.inner_text("#c-list") and "少给你" not in pg.inner_text("#c-list"), pg.inner_text("#c-list")[:200])
        pg.fill("#cq", ""); pg.wait_for_timeout(250)
        pg.evaluate(f"""() => document.querySelector('[data-edit-order="{r4}"]').click()"""); pg.wait_for_timeout(400)
        check("再打开编辑：上次填的还在（少给 $10、配送费没给）", pg.is_visible("#f-diff") and pg.input_value("#f-diffamt") == "10" and pg.input_value("#f-diffwhy") == "配送费没给")
        pg.click("#sheet-close"); pg.wait_for_timeout(250)
        pg.evaluate(f"""() => document.querySelector('[data-settle="{r4}"]').click()"""); pg.wait_for_timeout(600)
        check("已选好付款方式的预定点「结算」：因为这单记了少给，先弹出来", pg.is_visible("#sheet") and order(pg, r4)["status"] == "reserved")
        check("结算那页写「这次实际收 $50（合计 $60 − 这单少给的 $10）」", txt(pg, "#f-baltot") == "这次实际收 $50（合计 $60 − 这单少给的 $10）", txt(pg, "#f-baltot"))
        save(pg)
        check("结算后：这单 bal 还在，Dan 欠你 $10", order(pg, r4)["status"] == "paid" and bal(pg, "Dan") == 10, (order(pg, r4).get("bal"), bal(pg, "Dan")))
        sale(pg, "Dan", keep_open=True); pg.wait_for_timeout(150)
        check("下次给 Dan 记单：提醒「上次少给你 $10」", "上次少给你 $10" in txt(pg, "#f-balold"), txt(pg, "#f-balold"))
        pg.click("#sheet-close"); pg.wait_for_timeout(250)

        # 5. 钱的数字不变、刷新后还在
        go(pg, "finance"); pg.click('#period [data-p="all"]'); pg.wait_for_timeout(200)
        tot = pg.evaluate("window.__GM.S.orders.filter((o) => o.status === 'paid').reduce((a, o) => a + o.lines.reduce((s, l) => s + l.qty * l.unit_price, 0) + (o.delivery_fee || 0), 0)")
        check(f"收入 = 订单合计加起来 ${tot:g}（少给多给不改收入）", f"${tot:g}" in pg.inner_text("#f-inc"), (tot, pg.inner_text("#f-inc")))
        # 新结构：页面上的订单（含 bal）整份拿出来 → v2.js 迁移成新结构 → 再算回旧样子，bal 一字不差（刷新后看到的就是这样算出来的）
        if mode == "新结构":
            olds = pg.evaluate("Object.fromEntries(window.__GM.S.orders.map((o) => { const x = Object.assign({}, o); delete x.id; delete x._v; return [o.id, x]; }))")
            (tmp / "rt.json").write_text(json.dumps(dict(V1, orders=olds, movements={}), ensure_ascii=False), encoding="utf8")
            out = subprocess.run(["node", "-e", "const {migrate,project}=require(process.argv[1]);const d=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));const P=project(migrate(d));console.log(JSON.stringify(Object.fromEntries(P.orders.map(o=>[o.id,o.bal||null]))))",
                                  str(PUB / "v2.js"), str(tmp / "rt.json")], capture_output=True, text=True)
            got = json.loads(out.stdout or "{}"); want = {k: v.get("bal") for k, v in olds.items()}
            check("新结构存得住：迁移成新结构再算回来，每一单的 bal 一字不差（" + str(sum(1 for v in want.values() if v)) + " 单有记录）", got == want, out.stderr[:200])
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

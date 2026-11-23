"""换货（2026-11-24 Bowen：合伙人往来要有直接换货，不能每次拆成「他拿我的」+「我拿他的」两笔）
- 合伙人页「记往来 · 点口味」多第三个方向「换货」：下面「我给他的 / 他给我的」两边各点口味（各一个购物车，跟另外两个方向分开）
- 底下一条「换货 · 我给 N 根 ↔ 他给 M 根」+「记换货」→ 换货表单：两边的口味、每根 $（我给的默认进价，他给的默认他的价）、按系列一起改单价（收着）
- 同系列一根抵一根（不算钱）；抵平 → 这笔两清（closed）；不是 0 → 写谁欠谁，算上之前没结的；可以勾「差价当场付了」→ 记一笔结账
- 存法跟「记往来 · 当场换货」一样：一笔 transfers {out, in} + 流水；能撤销
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_xswap.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
D = lambda n: (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=n)).isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
nmz = {"XF-01": "香蕉", "XF-02": "葡萄冰", "XF-03": "粉柠檬", "XF-04": "芒果"}
IN = lambda k, q, c: {"type": "in", "sku": k, "name": nmz[k], "qty": q, "date": D(20), "at": D(20) + "T01:00:00Z", "note": "进货", "cost": q * c}
# 系列价格里的拿货价故意跟进货价不一样（Bar Pro 36 / 进货 30，Ali 45 / 进货 40）：跟合伙人之间默认都按进货价（2026-11-24 Bowen）
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 36), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 36),
                "XF-03": IT("XF-03", "Ali", "Pink Lemon", "粉柠檬", 45), "XF-04": IT("XF-04", "Ali", "Mango", "芒果", 45)},
      "movements": {"in-01": IN("XF-01", 20, 30), "in-03": IN("XF-03", 20, 40),
                    # 以前记过一笔两清的换货（让「合伙人甲」出现在名字里）
                    "t-old-out-XF-01": {"type": "adjust", "sku": "XF-01", "name": "香蕉", "qty": -1, "date": D(10), "at": D(10) + "T02:00:00Z", "transfer_id": "t-old", "note": "合伙人往来：给 合伙人甲"},
                    "t-old-in-XF-02": {"type": "in", "sku": "XF-02", "name": "葡萄冰", "qty": 1, "cost": 30, "date": D(10), "at": D(10) + "T02:00:00Z", "transfer_id": "t-old", "note": "合伙人往来：合伙人甲 给的"}},
      "transfers": {"t-old": {"date": D(10), "at": D(10) + "T02:00:00Z", "partner": "合伙人甲", "out": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit": 30}], "in": [{"sku": "XF-02", "name": "葡萄冰", "qty": 1, "unit": 30}], "note": "", "closed": True}},
      "orders": {}, "expenses": {}, "purchases": {}, "settlements": {}, "customers": {}, "followups": {}}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}
EXPOSE = "\nwindow.__GM = { S, derive, ptBal };\n})();"
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
    results.append(bool(ok)); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))
go = lambda pg, h: (pg.evaluate(f"location.hash = '#{h}'"), pg.wait_for_timeout(350))
S = lambda pg, col: pg.evaluate(f"window.__GM.S.{col}")
stock = lambda pg, sku: pg.evaluate(f"window.__GM.derive().st['{sku}'] || 0")
bal = lambda pg: pg.evaluate("window.__GM.ptBal('合伙人甲')")
def tap(pg, sku, n=1):
    for _ in range(n): pg.click(f'#ptx-tiles [data-padd="{sku}"]'); pg.wait_for_timeout(80)
def side(pg, k): pg.click(f'#ptx-side [data-ps="{k}"]'); pg.wait_for_timeout(150)
def swap_mode(pg):
    go(pg, "partner"); pg.evaluate("document.getElementById('ptx-rec').open = true"); pg.click('#ptx-dir [data-pd="swap"]'); pg.wait_for_timeout(200)
def save(pg):
    pg.wait_for_timeout(200); pg.click("#sheet-save")
    try: pg.wait_for_selector("#sheet", state="hidden", timeout=3000)
    except Exception: pass
    pg.wait_for_timeout(500)
def err(pg): return pg.evaluate("(document.querySelector('#sheet .err, #sheet-err') || {}).textContent || ''")
def newest(pg): return max((t for t in S(pg, "transfers") if t["id"] != "t-old"), key=lambda t: t.get("at") or "", default={})

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

        # 1. 第三个方向「换货」
        go(pg, "partner"); pg.evaluate("document.getElementById('ptx-rec').open = true")
        check("点口味那里三个方向：合伙人拿我的货 / 我跟合伙人拿货 / 换货；折叠标题写了换货", pg.locator("#ptx-dir [data-pd]").all_inner_texts() == ["合伙人拿我的货", "我跟合伙人拿货", "换货"] and "换货" in pg.inner_text("#ptx-rec > summary"))
        check("不是换货时没有「我给他的 / 他给我的」", pg.is_hidden("#ptx-side"))
        tap(pg, "XF-03")  # 先在「合伙人拿我的货」点一根，看跟换货的分开
        swap_mode(pg)
        check("换货：出现「我给他的 / 他给我的」，默认我给他的，只列手上有货的", pg.is_visible("#ptx-side") and pg.get_attribute('#ptx-side [data-ps="o"]', "aria-pressed") == "true" and pg.locator('#ptx-tiles [data-padd="XF-04"]').count() == 0 and "点你给他的口味" in pg.inner_text("#ptx-h"))
        check("换货的购物车跟「合伙人拿我的货」分开（那边点的那根不在这）", pg.is_hidden("#cartbar"))
        tap(pg, "XF-01", 2); tap(pg, "XF-03")
        side(pg, "i")
        check("切到「他给我的」：口味没货的也列（他手上的），我给他的写 3", pg.locator('#ptx-tiles [data-padd="XF-04"]').count() == 1 and "我给他的 · 3" in pg.inner_text("#ptx-side") and "点他给你的口味" in pg.inner_text("#ptx-h"))
        tap(pg, "XF-02", 2); tap(pg, "XF-04")
        cb = pg.inner_text("#cartbar")
        check("底下一条：换货 · 我给 3 根 ↔ 他给 3 根；按钮「记换货」", "换货 · 我给 3 根 ↔ 他给 3 根" in cb.replace("\n", "") and pg.inner_text("#cb-go") == "记换货", cb)

        # 2. 同系列一根抵一根 → 两清
        pg.click("#cb-go"); pg.wait_for_selector("#f-xsum")
        sm = pg.inner_text("#f-xsum")
        check("表单：合伙人默认合伙人甲；同系列一根抵一根 Bar Pro 2 根、Ali 1 根 → 两边抵平，这笔两清", pg.input_value("#f-xwho") == "合伙人甲" and "Bar Pro 2 根" in sm and "Ali 1 根" in sm and "两清" in sm and pg.is_hidden("#f-xpaidbox"), sm)
        check("合伙人名字按钮只出现一次", pg.locator('#sheet [data-pname="合伙人甲"]').count() == 1, pg.locator('#sheet [data-pname="合伙人甲"]').count())
        check("单价默认两边都按你的进货价（Bar Pro $30、Ali $40；不是系列价格里的 36 / 45）", [pg.input_value(f"#f-unit-{x}") for x in ("o0", "o1", "i0", "i1")] == ["30", "40", "30", "40"], [pg.input_value(f"#f-unit-{x}") for x in ("o0", "o1", "i0", "i1")])
        check("表单写明：单价默认按你的进货价（两边一样）：Bar Pro $30（… 进货）· Ali $40", "单价默认按你的进货价（两边一样）：Bar Pro $30（" in pg.inner_text("#f-trhint") and "Ali $40（" in pg.inner_text("#f-trhint"), pg.inner_text("#f-trhint"))
        b0 = bal(pg); save(pg)
        t = newest(pg)
        check("存成一笔往来：out 香蕉×2 粉柠檬×1、in 葡萄冰×2 芒果×1，两清（closed）", sorted((l["sku"], l["qty"]) for l in t.get("out", [])) == [("XF-01", 2), ("XF-03", 1)] and sorted((l["sku"], l["qty"]) for l in t.get("in", [])) == [("XF-02", 2), ("XF-04", 1)] and t.get("closed") is True, t)
        check("库存：香蕉 19→17、粉柠檬 20→19、葡萄冰 1→3、芒果 0→1", [stock(pg, k) for k in ("XF-01", "XF-03", "XF-02", "XF-04")] == [17, 19, 3, 1])
        check("跟合伙人甲还是两清；两边购物车清空", bal(pg) == b0 == 0 and pg.is_hidden("#cartbar"), (b0, bal(pg)))
        go(pg, "partner")
        lg = pg.inner_text("#ptx-log")
        check("往来记录：一行「换货」我给 / 他给，写两清", "换货" in lg and "两清" in lg.split("\n\n")[0] if "\n\n" in lg else ("换货" in lg and "两清" in lg), lg[:200])
        pg.click('#ptx-dir [data-pd="take"]'); pg.wait_for_timeout(200)
        check("回到「合伙人拿我的货」：之前点的那根还在", "合伙人拿 1 根" in pg.inner_text("#cartbar"), pg.inner_text("#cartbar"))
        pg.click("#cb-clear"); pg.click("#cb-clear"); pg.wait_for_timeout(200)

        # 3. 不同系列 → 有差价
        swap_mode(pg); tap(pg, "XF-01", 2); side(pg, "i"); tap(pg, "XF-04")
        pg.click("#cb-go"); pg.wait_for_selector("#f-xsum")
        sm = pg.inner_text("#f-xsum")
        check("Bar Pro 2 根 ↔ Ali 1 根：没有同系列可抵 → 你给 $60 ↔ 他给 $40 → 合伙人甲 欠你 $20", "你给 $60 ↔ 合伙人甲 给你 $40" in sm and "合伙人甲 欠你 $20" in sm and pg.is_visible("#f-xpaidbox"), sm)
        check("「差价当场付了」写明谁给谁", "合伙人甲 当场把差价 $20 给你了" in pg.inner_text("#f-xpaidt"))
        pg.evaluate("document.querySelector('#sheet details.more').open = true")
        pg.fill('#sheet [data-srx="o"][data-sr="Bar Pro"]', "35"); pg.wait_for_timeout(150)
        check("按系列一起改单价：我给的 Bar Pro 每根 $35 → 两根都改，欠你 $30", pg.input_value("#f-unit-o0") == "35" and "合伙人甲 欠你 $30" in pg.inner_text("#f-xsum"), pg.inner_text("#f-xsum"))
        save(pg)
        t = newest(pg)
        check("存了：不是两清（挂着），合伙人甲欠你 $30", not t.get("closed") and not t.get("partner_settlement_id") and bal(pg) == 30, (t, bal(pg)))
        go(pg, "partner")
        check("合伙人页：合伙人甲 欠你 $30", "合伙人甲 欠你" in pg.inner_text("#ptx-bal") and "$30" in pg.inner_text("#ptx-bal"), pg.inner_text("#ptx-bal"))
        # 撤销这笔
        pg.locator('#ptx-log [data-void-xfer="' + t["id"] + '"]').click(); pg.locator('#ptx-log [data-void-xfer="' + t["id"] + '"]').click(); pg.wait_for_timeout(600)
        check("撤销这笔：往来没了、库存回去、又两清", not any(x["id"] == t["id"] for x in S(pg, "transfers")) and stock(pg, "XF-01") == 17 and stock(pg, "XF-04") == 1 and bal(pg) == 0, (stock(pg, "XF-01"), stock(pg, "XF-04"), bal(pg)))

        # 4. 差价当场付了 → 记一笔结账，账上两清
        swap_mode(pg); tap(pg, "XF-01", 2); side(pg, "i"); tap(pg, "XF-04")
        pg.click("#cb-go"); pg.wait_for_selector("#f-xsum")
        pg.check("#f-xpaid"); pg.wait_for_timeout(100)
        pg.click("#sheet-save"); pg.wait_for_timeout(300)
        check("勾了当场付，没选付款方式：拦住", pg.is_visible("#sheet") and "怎么付" in pg.inner_text("#sheet"), pg.inner_text("#sheet")[-120:])
        pg.click('#f-paychips label:has(input[value="现金"])'); save(pg)
        t = newest(pg); st0 = next((x for x in S(pg, "settles") if x["id"] == t.get("partner_settlement_id")), {})
        check("差价当场付清：记一笔结账 合伙人甲 付你 $20（现金），这笔往来挂在那次结账上，账上两清", st0.get("amount") == -20 and st0.get("payment") == "现金" and st0.get("transfer_ids") == [t["id"]] and bal(pg) == 0, (st0, bal(pg)))

        # 4b. 「我跟合伙人拿货」「合伙人拿我的货」也按进货价（以前：我拿他的按系列价格 36，他拿我的按手上货的成本）
        go(pg, "partner"); pg.evaluate("document.getElementById('ptx-rec').open = true"); pg.click('#ptx-dir [data-pd="give"]'); pg.wait_for_timeout(200)
        tap(pg, "XF-02"); pg.click("#cb-go"); pg.wait_for_selector("#f-unit-0")
        check("我跟合伙人拿货：葡萄冰默认 $30（进货价）", pg.input_value("#f-unit-0") == "30", pg.input_value("#f-unit-0"))
        pg.click("#sheet-close"); pg.wait_for_timeout(200); pg.click("#cb-clear"); pg.click("#cb-clear"); pg.wait_for_timeout(200)
        pg.click('#ptx-dir [data-pd="take"]'); pg.wait_for_timeout(200); tap(pg, "XF-03"); pg.click("#cb-go"); pg.wait_for_selector("#f-unit-0")
        check("合伙人拿我的货：粉柠檬默认 $40（进货价）", pg.input_value("#f-unit-0") == "40", pg.input_value("#f-unit-0"))
        pg.click("#sheet-close"); pg.wait_for_timeout(200); pg.click("#cb-clear"); pg.click("#cb-clear"); pg.wait_for_timeout(200)
        go(pg, "inventory"); pg.click("#inv-serprice"); pg.wait_for_selector("#sheet .sp-last")
        check("系列价格里写最近进货：Bar Pro $30、Ali $40", pg.locator("#sheet .sp-last").all_inner_texts()[:2] == [f"最近进货 $30（{int(D(20)[5:7])}月{int(D(20)[8:])}日）", f"最近进货 $40（{int(D(20)[5:7])}月{int(D(20)[8:])}日）"], pg.locator("#sheet .sp-last").all_inner_texts())
        pg.click("#sheet-close"); pg.wait_for_timeout(200)

        # 5. 拦住：一边没选 / 给的比手上多
        swap_mode(pg); tap(pg, "XF-03")
        pg.click("#cb-go"); pg.wait_for_selector("#f-xsum"); pg.click("#sheet-save"); pg.wait_for_timeout(300)
        check("只选了一边：拦住「还没选他给你的口味」", pg.is_visible("#sheet") and "还没选他给你的口味" in pg.inner_text("#sheet"))
        pg.click("#sheet-close"); pg.wait_for_timeout(200)
        # 购物车里直接放 99 根（点格子点不出比库存多的），刷新后（假数据回到种子）再记
        pg.evaluate("() => { sessionStorage.setItem('mk-cartxo-v1', JSON.stringify({ 'XF-03': 99 })); sessionStorage.setItem('mk-cartxi-v1', JSON.stringify({ 'XF-02': 1 })); }")
        pg.reload(); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(400)
        n3 = stock(pg, "XF-03")
        swap_mode(pg); pg.click("#cb-go"); pg.wait_for_selector("#f-xsum"); pg.click("#sheet-save"); pg.wait_for_timeout(300)
        e = pg.inner_text("#sheet-err")
        check("给的比手上多：拦住（写手上几根、最多给几根）", pg.is_visible("#sheet") and f"手上 {n3} 根" in e and f"最多只能给 {n3} 根" in e and stock(pg, "XF-03") == n3, e)
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

"""补货单（2026-11-22 Bowen 重做补货建议）：一次补一个系列 N 盒（一盒 10 根、一个口味），口味看供货商这次有什么
- 卖得多快：最近 8 周、只算有货的日子（断货的日子不算）、一单超过 3 根按 3 根；数据少的往同系列平均拉
- 分档按一盒要几周卖完：卖得好 / 一般 / 偏冷（最多补一盒）/ 很冷（有货满 3 周还卖不动，不补）/ 没卖过（只标出来）；有货不满 14 天标「数据少」
- 补货单：默认 20 盒，没卖过的不勾；勾掉 = 供货商没有；− / ＋ 自己改（改过的不再动）；重新分；粘贴供货商清单只留认出来的；「做成订货单」带进订货单（每盒 10 根）
用编出来的数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_restock.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
import datetime as _dt
D = lambda n: (_dt.date.fromisoformat(TODAY) + _dt.timedelta(days=n)).isoformat()
ITEMS = [("XF-01", "Hot Mango", "热芒果"), ("XF-02", "Grape Ice", "葡萄冰"), ("XF-03", "Slow Mint", "慢薄荷"), ("XF-04", "Dead Kiwi", "死猕猴桃"),
         ("XF-05", "Fresh Peach", "新桃子"), ("XF-06", "Never Lime", "没卖过青柠"), ("XF-07", "Gone Berry", "断货莓"), ("XF-08", "Banana", "香蕉")]
V1 = {"items": {k: IT(k, "Bar Pro", v, n, 30) for k, v, n in ITEMS}, "movements": {}, "expenses": {}, "orders": {},
      "purchases": {}, "settlements": {}, "transfers": {}, "customers": {}, "followups": {}}
def stock_in(sku, day, q):
    b = "b-" + sku + "-" + str(-day); V1["movements"][b + "-" + sku] = {"type": "in", "sku": sku, "name": sku, "qty": q, "date": D(day), "at": D(day) + "T01:00:00Z", "cost": 30 * q, "batch_id": b, "expense_id": b + "-cost", "note": ""}
    V1["expenses"][b + "-cost"] = {"date": D(day), "at": D(day) + "T01:00:00Z", "amount": 30 * q, "category": "进货成本", "note": "进货", "batch_id": b}
NO = [0]
def sell(sku, day, q, who="Amy"):
    NO[0] += 1; oid = f"o-{NO[0]}"
    V1["orders"][oid] = {"status": "paid", "date": D(day), "at": D(day) + "T05:00:00Z", "customer": who, "lines": [{"sku": sku, "name": sku, "qty": q, "unit_price": 60}], "delivery_fee": 0, "payment": "现金", "note": ""}
    V1["movements"][oid + "-" + sku] = {"type": "out", "sku": sku, "name": sku, "qty": q, "date": D(day), "at": D(day) + "T05:00:00Z", "order_id": oid}
# 热芒果：一直有货，每天卖 2 根 → 卖得好
stock_in("XF-01", -50, 110)
for d in range(-48, 0): sell("XF-01", d, 1); sell("XF-01", d, 1, "Ben")
# 葡萄冰：一直有货，每 2 天 1 根，外加一单 10 根（大单按 3 根算）→ 一般
stock_in("XF-02", -50, 50)
for d in range(-48, 0, 2): sell("XF-02", d, 1)
sell("XF-02", -10, 10, "Rob")
# 慢薄荷：一直有货，每 5 天 1 根 → 偏冷
stock_in("XF-03", -50, 20)
for d in range(-48, 0, 5): sell("XF-03", d, 1)
# 死猕猴桃：有货 40 天一根没卖 → 很冷
stock_in("XF-04", -40, 10)
# 新桃子：3 天前到货，卖了 2 根 → 数据少
stock_in("XF-05", -3, 10); sell("XF-05", -2, 1); sell("XF-05", -1, 1)
# 断货莓：8 周前到 6 根，6 天卖完，之后一直没货 → 按有货的 6 天算，卖得快（不能当冷门）
stock_in("XF-07", -50, 6)
for d in range(-50, -44): sell("XF-07", d, 1)
# 香蕉：一直有货，每 2 天 1 根 → 一般
stock_in("XF-08", -50, 40)
for d in range(-48, 0, 2): sell("XF-08", d, 1)
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}
EXPOSE = "\nwindow.__GM = { S };\n})();"
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

go = lambda pg, h: (pg.evaluate(f"location.hash = '#{h}'"), pg.wait_for_timeout(300))
S = lambda pg, col: pg.evaluate(f"window.__GM.S.{col}")
def save(pg):
    pg.wait_for_timeout(200); pg.click("#sheet-save")
    try: pg.wait_for_selector("#sheet", state="hidden", timeout=3000)
    except Exception: pass
    pg.wait_for_timeout(450)
def close(pg): pg.click("#sheet-close"); pg.wait_for_timeout(250)
def rows(pg): return pg.evaluate("[...document.querySelectorAll('#rs-list .rs-row')].map((r) => { let t = r.previousElementSibling; while (t && !t.classList.contains('rs-tier')) t = t.previousElementSibling; return [r.querySelector('.cn').textContent, t ? t.textContent : '', r.querySelector('.dates').textContent]; })")
def plan(pg): return pg.evaluate("Object.fromEntries([...document.querySelectorAll('#rs-rows .rs-prow')].map((r) => [r.querySelector('small').textContent.split(' · ')[0], [r.querySelector('input').checked, Number(r.querySelector('.rs-step b').textContent)]]))")
def total(pg): return pg.inner_text("#rs-total")
def bx(pg, cn, d): pg.locator("#rs-rows .rs-prow").filter(has=pg.locator(f'small:text-matches("^{cn} ")')).locator(f'[data-bx="{d}"]').click(); pg.wait_for_timeout(80)
def have(pg, cn, on): l = pg.locator("#rs-rows .rs-prow").filter(has=pg.locator(f'small:text-matches("^{cn} ")')).locator("input"); (l.check() if on else l.uncheck()); pg.wait_for_timeout(80)

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
        go(pg, "inventory"); pg.evaluate("document.getElementById('rs-sec').open = true"); pg.wait_for_timeout(150)
        R = {cn: (t, d) for cn, t, d in rows(pg)}
        check("热芒果：卖得好（一直有货、每天 1 根）", R["热芒果"][0] == "卖得好", R["热芒果"])
        check("葡萄冰：按被买了几次算，一单 10 根也只算 1 次（24 + 1 = 25 次），一般", "被买 25 次" in R["葡萄冰"][1] and R["葡萄冰"][0] == "一般", R["葡萄冰"])
        check("慢薄荷：偏冷", R["慢薄荷"][0] == "偏冷", R["慢薄荷"])
        check("死猕猴桃：有货 40 天一根没卖 → 很冷", R["死猕猴桃"][0] == "很冷", R["死猕猴桃"])
        check("新桃子：到货 3 天，标「数据少」，最冷只算「一般」", "数据少" in R["新桃子"][1] and R["新桃子"][0] in ("卖得好", "一般"), R["新桃子"])
        check("断货莓：只算有货的 6 天（被买 6 次），数据少 → 不当冷门", "有货 6 天、被买 6 次" in R["断货莓"][1] and R["断货莓"][0] in ("卖得好", "一般") and "数据少" in R["断货莓"][1], R["断货莓"])
        check("没卖过青柠：没卖过", R["没卖过青柠"][0] == "没卖过", R["没卖过青柠"])
        order = [cn for cn, _, _ in rows(pg)]
        check("按档排：卖得好 → 一般 → 偏冷 → 很冷 → 没卖过", order.index("热芒果") < order.index("葡萄冰") < order.index("慢薄荷") < order.index("死猕猴桃") < order.index("没卖过青柠"), order)

        pg.click("#rs-plan"); pg.wait_for_selector("#rs-rows .rs-prow")
        P = plan(pg)
        check("补货单默认 20 盒，分满", "已分 20 / 20 盒 · 200 根" in total(pg), total(pg))
        check("没卖过的默认不勾、0 盒；很冷的勾着但 0 盒（写「很冷，不补」）", P["没卖过青柠"] == [False, 0] and P["死猕猴桃"] == [True, 0] and "很冷，不补" in pg.inner_text("#rs-rows"), P)
        check("偏冷最多 1 盒", P["慢薄荷"][1] <= 1, P["慢薄荷"])
        check("卖得好的热芒果分到的盒数最多", P["热芒果"][1] == max(v[1] for v in P.values()) and P["热芒果"][1] >= 3, P)
        check("断货莓（现在没货）至少 1 盒；不会把一大半压在它一款上", 1 <= P["断货莓"][1] <= 6, P["断货莓"])
        hot0 = P["热芒果"][1]
        have(pg, "热芒果", False)
        P2 = plan(pg)
        check("勾掉热芒果（供货商没有）：0 盒，20 盒分给别的", P2["热芒果"] == [False, 0] and "已分 20 / 20 盒" in total(pg), (P2, total(pg)))
        check("…不会都压到一款上（单款最多 8 盒）", max(v[1] for v in P2.values()) <= 8, P2)
        have(pg, "热芒果", True); bx(pg, "慢薄荷", 1); bx(pg, "慢薄荷", 1)
        P3 = plan(pg)
        check("自己给慢薄荷 + 两下：照你的改（不受偏冷上限），别的少分 → 总数还是 20", P3["慢薄荷"][1] == P["慢薄荷"][1] + 2 and "已分 20 / 20 盒" in total(pg), (P3, total(pg)))
        pg.click("#rs-reset"); pg.wait_for_timeout(100)
        check("重新分：回到自动分的", plan(pg) == P, plan(pg))
        pg.click('[data-rsn="-1"]'); pg.fill("#rs-n", "10"); pg.dispatch_event("#rs-n", "change"); pg.wait_for_timeout(100)
        check("改成补 10 盒：分 10 盒", "已分 10 / 10 盒 · 100 根" in total(pg), total(pg))
        pg.click("#rs-pastebtn"); pg.fill("#rs-paste", "Bar Pro\nBanana\nGrape Ice\nSomething New"); pg.click("#rs-parse"); pg.wait_for_timeout(150)
        P4 = plan(pg)
        check("粘贴供货商清单：只留香蕉、葡萄冰（10 盒分给它们）；没认出的写出来", [k for k, v in P4.items() if v[0]] == ["葡萄冰", "香蕉"] or sorted(k for k, v in P4.items() if v[0]) == ["葡萄冰", "香蕉"], P4)
        check("…没认出的「Something New」列出来", "Something New" in pg.inner_text("#rs-parsed"), pg.inner_text("#rs-parsed"))
        check("…两款一共 10 盒", sum(v[1] for v in P4.values()) == 10, P4)
        want = {k: v[1] * 10 for k, v in P4.items() if v[1]}
        pg.click("#sheet-save"); pg.wait_for_selector("#f-lines .line")
        got = pg.evaluate("Object.fromEntries([...document.querySelectorAll('#f-lines .line')].map((r) => [r.querySelector('.pl-name small, .pl-name b').textContent, Number(r.querySelector('input[id^=f-qty-]').value)]))")
        names = {"Banana": "香蕉", "Grape Ice": "葡萄冰"}
        got2 = {names.get(k, k): v for k, v in got.items()}
        check("「做成订货单」：订货单里就是这两款，每盒 10 根", got2 == want, (got, want))
        save(pg)
        po = S(pg, "purchases")
        check("存了订货单，100 根", len(po) == 1 and sum(l["qty"] for l in po[0]["lines"]) == 100, po)

        # 客人问了、但没货
        go(pg, "inventory"); pg.wait_for_timeout(200)
        check("补货里没货的断货莓旁边有「有人问」；有货的死猕猴桃、没卖过的没有", pg.locator('#rs-list [data-ask="XF-07"]').count() == 1 and pg.locator('#rs-list [data-ask="XF-04"]').count() == 0 and pg.locator('#rs-list [data-ask="XF-06"]').count() == 0)
        pg.evaluate("document.getElementById('rs-sec').open = true"); pg.wait_for_timeout(100)
        pg.click('#rs-plan'); pg.wait_for_selector("#rs-rows .rs-prow")
        lam0 = pg.evaluate("(() => { const r = [...document.querySelectorAll('#rs-rows .rs-prow small')].find((x) => x.textContent.startsWith('断货莓')); return r ? r.textContent : ''; })()")
        close(pg)
        pg.click('#rs-list [data-ask="XF-07"]'); pg.wait_for_timeout(400); pg.click('#rs-list [data-ask="XF-07"]'); pg.wait_for_timeout(400)
        asks = [f for f in S(pg, "followups") if f.get("kind") == "ask"]
        check("点两下：记两笔「有人问」（今天、断货莓、不进跟进）", len(asks) == 2 and all(a["sku"] == "XF-07" and a["date"] == TODAY and a["done"] is True for a in asks), asks)
        check("按钮上写「有人问 2」", "有人问 2" in pg.inner_text('#rs-list [data-ask="XF-07"]'), pg.inner_text('#rs-list [data-ask="XF-07"]'))
        R2 = {cn: (t, d) for cn, t, d in rows(pg)}
        check("补货里写「没货时 2 人问」", "没货时 2 人问" in R2["断货莓"][1], R2["断货莓"])
        pg.click('#rs-plan'); pg.wait_for_selector("#rs-rows .rs-prow")
        lam1 = pg.evaluate("(() => { const r = [...document.querySelectorAll('#rs-rows .rs-prow small')].find((x) => x.textContent.startsWith('断货莓')); return r ? r.textContent : ''; })()")
        import re as _re
        n0 = int(_re.search(r"这批大概卖 (\d+) 根", lam0).group(1)); n1 = int(_re.search(r"这批大概卖 (\d+) 根", lam1).group(1))
        check("补货单：有人问的「这批大概卖」变多", n1 > n0 and "没货时 2 人问" in lam1, (lam0, lam1))
        close(pg)
        pg.click('#inv-tabs [data-it="items"]'); pg.wait_for_timeout(200)
        check("「管理香型」里没货的那一行也有「有人问 2」", "有人问 2" in pg.inner_text('#items [data-ask="XF-07"]'))
        pg.click('.row-main[data-sku="XF-07"]'); pg.wait_for_selector('[data-ask-undo="XF-07"]')
        check("展开写「最近 4 周没货时有 2 次有人问」", "最近 4 周没货时有 2 次有人问" in pg.inner_text("#items"))
        pg.click('[data-ask-undo="XF-07"]'); pg.wait_for_timeout(400)
        check("撤销上一次：剩 1 笔", len([f for f in S(pg, "followups") if f.get("kind") == "ask"]) == 1)
        go(pg, "customers"); pg.wait_for_timeout(200)
        check("「有人问」不出现在要联系的客户、客户名单里", pg.locator("#fu-list .cx-row").count() == 0 and "断货莓" not in pg.inner_text("#c-list"), pg.inner_text("#c-list")[:100])
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

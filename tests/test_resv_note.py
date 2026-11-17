"""预定的备注写在概览上 + 客户资料不再填「区」「从哪来的」（2026-11-17 Bowen）
- 「预定里写了备注（什么时间、什么地方见面），跳到预定概览就看不到」：以前备注只在点开卡片后才显示 → 现在没点开就看得到
- 「客人信息里那种各种区、各种地方没有必要」：记单 / 编辑 / 跟进 / 客户资料都拿掉「区」，记单拿掉「从哪来的」；
  以前填过的照旧留在记录上（编辑不会把它清掉），来源照旧自动记「回头客」
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_resv_note.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 30), "XF-03": IT("XF-03", "Bar Pro", "Blueberry Ice", "蓝莓冰", 30),
                "XF-04": IT("XF-04", "Ali", "Pink Lemon", "粉柠檬", 25)},
      "movements": {f"in-{k}": {"type": "in", "sku": k, "name": k, "qty": 20, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货", "cost": 400} for k in ("XF-01", "XF-02", "XF-03", "XF-04")},
      "orders": {"o-sold": {"status": "paid", "date": TODAY, "at": TODAY + "T02:00:00Z", "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit_price": 60}], "delivery_fee": 0, "payment": "现金", "customer": "Amy", "suburb": "Cooloongup", "source": "帖子"},
                 "o-r1": {"status": "reserved", "date": TODAY, "at": TODAY + "T03:00:00Z", "lines": [{"sku": "XF-02", "name": "葡萄冰", "qty": 2, "unit_price": 60}], "delivery_fee": 0, "payment": None, "customer": "Bob", "note": "周三 6pm Coles 门口见"},
                 "o-r2": {"status": "reserved", "date": TODAY, "at": TODAY + "T04:00:00Z", "lines": [{"sku": "XF-03", "name": "蓝莓冰", "qty": 1, "unit_price": 60}], "delivery_fee": 0, "payment": None, "customer": None, "note": "Kim"},
                 "o-r3": {"status": "reserved", "date": TODAY, "at": TODAY + "T05:00:00Z", "lines": [{"sku": "XF-03", "name": "蓝莓冰", "qty": 1, "unit_price": 60}], "delivery_fee": 0, "payment": None, "customer": "Amy", "note": ""}},
      "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {},
      "customers": {"c_amy": {"name": "Amy", "key": "amy", "type": "retail", "suburb": "Cooloongup", "contact": None, "note": None}}, "followups": {}}
for k in ("XF-01", "XF-02", "XF-03", "XF-04"): V1["movements"][f"in-{k}"]["name"] = V1["items"][k]["name"]
V1["movements"]["o-sold-XF-01"] = {"type": "out", "sku": "XF-01", "name": "香蕉", "qty": 1, "date": TODAY, "at": TODAY + "T02:00:00Z", "order_id": "o-sold"}
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
def chips_ok(pg):  # 付款方式是一排小标签、有现金+转账、没有下拉框
    return pg.locator("#sheet #f-paychips input[name=f-payr]").count() == 5 and pg.locator('#sheet #f-paychips input[value="现金+转账"]').count() == 1 and pg.locator("#sheet select#f-pay").count() == 0
def mix(pg, cash, other=None):
    pg.click('#f-paychips label:has(input[value="现金+转账"])'); pg.wait_for_timeout(120)
    pg.fill("#f-paycash", str(cash))
    if other: pg.select_option("#f-payother", other)
    pg.wait_for_timeout(150)

def card(pg, oid):  # 预定卡片（没点开）
    return pg.locator(f'#resv details.rv:has([data-settle="{oid}"])')
def order(pg, oid): return [x for x in S(pg, "orders") if x["id"] == oid][0]

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

        # 1. 预定概览上看得到备注
        go(pg, "customers")
        c1 = card(pg, "o-r1")
        check("Bob 的预定没点开：备注「周三 6pm Coles 门口见」看得到", c1.locator("summary .rv-note").is_visible() and c1.locator("summary .rv-note").inner_text() == "周三 6pm Coles 门口见" and not c1.evaluate("(d) => d.open"))
        c1.locator("summary").click(); pg.wait_for_timeout(200)
        check("点开以后备注不重复写第二遍", c1.inner_text().count("周三 6pm Coles 门口见") == 1, c1.inner_text().count("周三 6pm Coles 门口见"))
        check("没写客人名字、备注当名字的（Kim）：不再重复一行备注", card(pg, "o-r2").locator(".rv-note").count() == 0 and "Kim" in card(pg, "o-r2").locator("summary").inner_text())
        check("没写备注的预定：没有空的备注框", card(pg, "o-r3").locator(".rv-note").count() == 0)
        check("预定卡片上不再写区（Amy · Cooloongup）", "Cooloongup" not in card(pg, "o-r3").inner_text())

        # 2. 编辑预定：备注那一块直接打开，改了概览马上跟着变
        pg.evaluate("""() => document.querySelector('[data-edit-order="o-r1"]').click()"""); pg.wait_for_selector("#f-note", state="attached")
        check("编辑有备注的预定：「更多」直接展开，备注看得到", pg.is_visible("#f-note") and pg.input_value("#f-note") == "周三 6pm Coles 门口见")
        check("「更多」里没有「区」「从哪来的」了", pg.locator("#sheet #f-sub, #sheet #f-src").count() == 0 and "区" not in pg.inner_text("#f-more-sum"), pg.inner_text("#f-more-sum"))
        pg.fill("#f-note", "周四 7pm 改到 Rockingham 火车站"); save(pg)
        go(pg, "customers")
        check("改了备注：概览上马上是新的", card(pg, "o-r1").locator("summary .rv-note").inner_text() == "周四 7pm 改到 Rockingham 火车站")

        # 3. 编辑以前填过区 / 来源的单：不会被清掉
        pg.evaluate("""() => document.querySelector('[data-edit-order="o-r3"]').click()"""); pg.wait_for_selector("#f-note", state="attached")
        check("没备注没跟进的预定：「更多」照旧收着", not pg.evaluate("document.getElementById('f-more').open"))
        pg.click("#f-more-sum"); pg.fill("#f-note", "Amy 周五下班后"); save(pg)
        o3 = order(pg, "o-r3")
        check("Amy 的预定存了备注，来源自动「回头客」", o3.get("note") == "Amy 周五下班后" and o3.get("source") == "回头客", {k: o3.get(k) for k in ("note", "source", "suburb")})
        go(pg, "finance"); pg.evaluate("""() => document.querySelector('[data-edit-order="o-sold"]').click()"""); pg.wait_for_selector("#f-note", state="attached")
        check("改已卖出的单：折叠只剩「下次跟进」，没有区 / 来源框", pg.locator("#sheet #f-sub, #sheet #f-src").count() == 0 and pg.locator("#sheet summary", has_text="下次跟进").count() == 1)
        pg.fill("#f-note", "改一下备注"); save(pg)
        o = order(pg, "o-sold")
        check("以前填过的区、来源还在记录上（Cooloongup、帖子）", o.get("suburb") == "Cooloongup" and o.get("source") == "帖子" and o.get("note") == "改一下备注", {k: o.get(k) for k in ("suburb", "source", "note")})

        # 4. 新记一单：新客人不写来源，老客人自动「回头客」
        for who, want in (("Zed", None), ("amy", "回头客")):
            before = {x["id"] for x in S(pg, "orders")}
            go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
            pg.fill("#f-skuq-0", "香蕉"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1")
            pg.click('#f-paychips label:has(input[value="现金"])')
            pg.locator("#f-cust").press_sequentially(who); pg.wait_for_timeout(150)
            check(f"记一单（{who}）：没有区 / 来源框", pg.locator("#sheet #f-sub, #sheet #f-src").count() == 0)
            save(pg)
            if pg.is_visible("#sheet"): print("   弹窗还开着：", pg.inner_text("#sheet-err")[:200])
            new = [x for x in S(pg, "orders") if x["id"] not in before]
            check(f"{who} 存好：来源 = {want}", len(new) == 1 and new[0].get("source") == want and not new[0].get("suburb"), new and {k: new[0].get(k) for k in ("customer", "source", "suburb")})

        # 5. 跟进、客户资料：没有区；客户资料里以前的区不会被清掉
        go(pg, "customers"); pg.click("#cu-fu-new"); pg.wait_for_selector("#f-cust")
        check("记跟进：没有「区」", pg.locator("#sheet #f-sub").count() == 0 and "区" not in pg.inner_text("#sheet .sheet-card, #sheet"))
        close(pg)
        pg.evaluate("""() => { const b = [...document.querySelectorAll('[data-cu]')].find((x) => /Amy/.test(x.innerText)); b.click(); }"""); pg.wait_for_timeout(300)
        pg.evaluate("""() => document.querySelector('[data-cu-edit]').click()"""); pg.wait_for_selector("#f-ccontact")
        check("客户资料：没有「区」框", pg.locator("#sheet #f-csub").count() == 0)
        pg.fill("#f-ccontact", "FB: Amy W"); save(pg)
        cu = [x for x in S(pg, "customers") if x["id"] == "c_amy"][0]
        check("客户资料存了联系方式，以前的区还留着", cu.get("contact") == "FB: Amy W" and cu.get("suburb") == "Cooloongup", {k: cu.get(k) for k in ("contact", "suburb")})
        check("客户列表 Amy 那行不再写区", "Cooloongup" not in pg.inner_text("#cu-view") if pg.locator("#cu-view").count() else True)
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

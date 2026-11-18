"""预定的交货时间单独一栏 + 预定按时间排（2026-11-18 Bowen：时间别写在备注里，放在客户下面；预定页按时间排好）
- 记预定 / 编辑预定：客户下面「什么时候交货（见面）」：今天 / 明天 / 后天 / 选日期 + 几点（都可以不填；只填几点 = 今天）；记卖出时不出现
- 订单字段 meet_date / meet_time；预定卡片上写「今天 18:00」「明天 15:00」「已过 · 11月17日 10:00」，没定的写「11月17日 记 · 没定时间」
- 预定列表：定了时间的按时间从早到晚（过了的在最上面），没定时间的在后面
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_meet.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
DD = lambda n: (datetime.date.fromisoformat(TODAY) + datetime.timedelta(days=n)).isoformat()
def RES(oid, who, n, md=None, mt=None):
    o = {"status": "reserved", "date": DD(-1), "at": DD(-1) + "T0%d:00:00Z" % n, "customer": who, "payment": None, "delivery_fee": 0, "note": "",
         "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit_price": 30}]}
    if md is not None: o["meet_date"] = DD(md)
    if mt: o["meet_time"] = mt
    return oid, o
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30)},
      "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 40, "date": DD(-2), "at": DD(-2) + "T00:30:00Z", "note": "进货", "cost": 1000}},
      "orders": dict([RES("r-none", "Amy", 1), RES("r-tmr", "Bob", 2, 1, "15:00"), RES("r-tonight", "Cat", 3, 0, "18:00"), RES("r-late", "Dan", 4, -1, "10:00"), RES("r-today", "Eve", 5, 0)]),
      "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {}}
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

def order(pg, oid): return next((x for x in S(pg, "orders") if x["id"] == oid), {})
def cards(pg): return pg.evaluate("""[...document.querySelectorAll('#resv details.rv')].map((d) => [d.querySelector('[data-settle]').dataset.settle, d.querySelector('.l-date').innerText.replace(/\\s+/g, ' ').trim()])""")
def fmt(d): x = datetime.date.fromisoformat(d); return f"{x.month}月{x.day}日"

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
        go(pg, "customers"); C = cards(pg)
        check("按交货时间排：过了的 → 今天 18:00 → 今天（没写几点）→ 明天 15:00 → 没定时间的", [c[0] for c in C] == ["r-late", "r-tonight", "r-today", "r-tmr", "r-none"], [c[0] for c in C])
        want = {"r-late": "预定已过 · " + fmt(DD(-1)) + " 10:00", "r-tonight": "预定今天 18:00", "r-today": "预定今天", "r-tmr": "预定明天 15:00", "r-none": "预定" + fmt(DD(-1)) + " 记 · 没定时间"}
        check("卡片上写交货时间（不是记单那天）", dict(C) == want, dict(C))

        # 记卖出：不出现；勾「只是预定」才出现，在客户下面
        before = {x["id"] for x in S(pg, "orders")}
        go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
        pg.fill("#f-skuq-0", "香蕉"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1")
        check("记卖出：没有交货时间这一栏；备注直接放出来，「更多：日期、下次跟进」收着", pg.is_hidden("#f-meet") and pg.is_visible("#f-note") and pg.is_visible("#f-more") and "日期、下次跟进" in pg.inner_text("#f-more-sum"))
        pg.check("#f-resv"); pg.wait_for_timeout(100)
        check("勾「只是预定」：「更多」（日期、下次跟进）不要了，只剩备注", pg.is_hidden("#f-more") and pg.is_visible("#f-note"))
        check("勾「只是预定」：出现，就在客户那一栏下面", pg.is_visible("#f-meet") and pg.evaluate("(() => { const c = document.getElementById('f-cust').closest('.field'); let n = c.nextElementSibling; while (n && n.offsetParent === null) n = n.nextElementSibling; return n && n.id; })()") == "f-meet")
        pg.locator("#f-cust").press_sequentially("Fay")
        pg.click('#f-md label:has(input[value="1"])'); pg.fill("#f-mtime", "16:30"); save(pg)
        new = [x for x in S(pg, "orders") if x["id"] not in before]
        check("存了：明天 16:30", len(new) == 1 and new[0].get("meet_date") == DD(1) and new[0].get("meet_time") == "16:30", new and {k: new[0].get(k) for k in ("meet_date", "meet_time", "status")})
        go(pg, "customers"); C = cards(pg)
        check("新预定排在「明天 15:00」后面、没定时间的前面", [c[0] for c in C][3:5] == ["r-tmr", new[0]["id"]] if new else False, [c[0] for c in C])

        # 只填几点 = 今天；记卖出不存时间
        before = {x["id"] for x in S(pg, "orders")}
        go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
        pg.fill("#f-skuq-0", "香蕉"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1"); pg.check("#f-resv")
        pg.fill("#f-mtime", "20:00"); save(pg)
        n2 = [x for x in S(pg, "orders") if x["id"] not in before]
        check("只填几点没选哪天：当成今天", n2 and n2[0].get("meet_date") == TODAY and n2[0].get("meet_time") == "20:00", n2 and {k: n2[0].get(k) for k in ("meet_date", "meet_time")})
        before = {x["id"] for x in S(pg, "orders")}
        go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
        pg.fill("#f-skuq-0", "香蕉"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1"); pg.click('#f-paychips label:has(input[value="现金"])'); save(pg)
        n3 = [x for x in S(pg, "orders") if x["id"] not in before]
        check("记卖出：不存交货时间", n3 and "meet_date" not in n3[0] and n3[0].get("status") == "paid", n3 and n3[0])

        # 编辑预定：带出来，可以改、可以清掉
        go(pg, "customers"); pg.evaluate("""() => document.querySelector('[data-edit-order="r-tmr"]').click()"""); pg.wait_for_selector("#f-meet")
        check("编辑 Bob 的预定：「明天」选着、15:00", pg.is_visible("#f-meet") and pg.is_checked('#f-md input[value="1"]') and pg.input_value("#f-mtime") == "15:00")
        pg.click('#f-md label:has(input[value="d"])'); pg.fill("#f-mdate", DD(5)); pg.fill("#f-mtime", "11:00"); save(pg)
        o = order(pg, "r-tmr")
        check("改成选日期 5 天后 11:00", o.get("meet_date") == DD(5) and o.get("meet_time") == "11:00", {k: o.get(k) for k in ("meet_date", "meet_time")})
        pg.evaluate("""() => document.querySelector('[data-edit-order="r-tonight"]').click()"""); pg.wait_for_selector("#f-meet")
        pg.click('#f-md label:has(input[value="0"])'); pg.fill("#f-mtime", ""); save(pg)
        o = order(pg, "r-tonight")
        check("再点一下「今天」取消、清掉几点：不定时间，排到后面", o.get("meet_date") is None and o.get("meet_time") is None and cards(pg)[-1][0] in ("r-tonight", "r-none"), {k: o.get(k) for k in ("meet_date", "meet_time")})
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

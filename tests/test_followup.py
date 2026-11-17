"""跟进重做 + 按客人的节奏自动提醒 + 客户买过什么竖着排（2026-11-18 Bowen）
- 跟进只能「已发信息 / 不用跟了」一次：客人说下次再说就没法往后排 → 每条跟进多一个「往后排」：这次怎么说的 + 下次哪天（明天 / 3 天后 / 一周后 / 两周后 / 选日期 / 不定），联系记录留着
- 不知道几号跟进：记跟进默认「不定」，一直留在列表里
- 「这个客人每几天来一次，时间到了 App 自己提醒我」：客户资料「大概多久买一次」；没设就按他自己的记录（买过 3 天以上，间隔取中位数）。到日子出现在「要联系的客户」里，写他的节奏、常买的现在有没有货、你写的备注
- 客户点开「买过什么」：日期一行，下面每个系列几根，再下面每个口味竖着排（跟合伙人对账单一样）
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_followup.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
D = lambda n: (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=n)).isoformat()
def sold(oid, who, n, lines):
    return oid, {"status": "paid", "date": D(n), "at": D(n) + "T02:00:00Z", "customer": who, "payment": "现金", "delivery_fee": 0, "note": "",
                 "lines": [{"sku": k, "name": nmz[k], "qty": q, "unit_price": 30} for k, q in lines]}
nmz = {"XF-01": "香蕉", "XF-02": "葡萄冰", "XF-03": "蓝莓冰", "XF-04": "粉柠檬"}
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 30), "XF-03": IT("XF-03", "Bar Pro", "Blueberry Ice", "蓝莓冰", 30),
                "XF-04": IT("XF-04", "Ali", "Pink Lemon", "粉柠檬", 25)},
      "movements": {f"in-{k}": {"type": "in", "sku": k, "name": nmz[k], "qty": 40, "date": D(30), "at": D(30) + "T01:00:00Z", "note": "进货", "cost": 1000} for k in nmz},
      "orders": dict([
          # Amy：14、9、4 天前各买一次 → 大概 5 天一次，明天该来 → 今天就提醒
          sold("o-a1", "Amy", 14, [("XF-01", 2), ("XF-04", 1)]), sold("o-a2", "Amy", 9, [("XF-01", 1)]), sold("o-a3", "Amy", 4, [("XF-02", 2), ("XF-01", 1), ("XF-04", 2)]),
          # Bob：只买过 2 次，看不出节奏 → 不自动提醒
          sold("o-b1", "Bob", 20, [("XF-02", 1)]), sold("o-b2", "Bob", 18, [("XF-02", 1)]),
          # Cat：买过 3 次、节奏 5 天，可是有预定 → 不提醒
          sold("o-c1", "Cat", 14, [("XF-03", 1)]), sold("o-c2", "Cat", 9, [("XF-03", 1)]), sold("o-c3", "Cat", 4, [("XF-03", 1)]),
          # Dan：只买过 1 次，你在资料里设了每 3 天 → 提醒
          sold("o-d1", "Dan", 3, [("XF-04", 3)]),
          # Eve：买过 3 次、节奏 2 天（最少按 3 天），可是 60 天没来了、又不是你设的 → 不提醒
          sold("o-e1", "Eve", 64, [("XF-01", 1)]), sold("o-e2", "Eve", 62, [("XF-01", 1)]), sold("o-e3", "Eve", 60, [("XF-01", 1)]),
          ("o-c-r", {"status": "reserved", "date": TODAY, "at": TODAY + "T05:00:00Z", "customer": "Cat", "payment": None, "delivery_fee": 0, "note": "", "lines": [{"sku": "XF-03", "name": "蓝莓冰", "qty": 1, "unit_price": 30}]}),
      ]),
      "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {},
      "customers": {"c_dan": {"name": "Dan", "key": "dan", "type": "retail", "note": "很热情，买得多", "every": 3}},
      "followups": {"fu-kim": {"customer": "Kim", "wants": [{"sku": "XF-02", "name": "葡萄冰", "qty": 2}], "note": "一盒葡萄冰", "date": D(1), "done": False, "created_at": D(5) + "T01:00:00Z"}}}
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

def rows(pg): return pg.evaluate("[...document.querySelectorAll('#fu-list .lrow')].map((r) => r.innerText)")
def row(pg, who): return next((r for r in rows(pg) if ("\n" + who + "\n") in ("\n" + r + "\n") or r.split("\n")[1:2] == [who] or (" " + who) in r.split("\n")[1]), "")
def cust(pg, cid): return next((x for x in S(pg, "customers") if x["id"] == cid), {})
def fu(pg, fid): return next((x for x in S(pg, "followups") if x["id"] == fid), {})
def pick_when(pg, v): pg.click(f'#f-when label:has(input[value="{v}"])'); pg.wait_for_timeout(80)

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
        go(pg, "customers")
        names = [r.split("\n")[1] for r in rows(pg)]
        check("要联系的客户：Kim（跟进）、Amy（按记录 5 天一次）、Dan（你设的每 3 天）", set(names) == {"Kim", "Amy", "Dan"}, names)
        check("不提醒：Bob（只买过 2 次）、Cat（已经有预定）、Eve（60 天没来、不是你设的）", not ({"Bob", "Cat", "Eve"} & set(names)), names)
        a = row(pg, "Amy")
        check("Amy：写他的节奏和上次哪天", "按记录大概 5 天买一次（买过 3 次）" in a and "4 天前" in a, a)
        check("Amy：常买的按根数排，写现在有没有货", "常买：Banana Buzz ×4 有 40、Pink Lemon ×3 有 40、Grape Ice ×2 有 40" in a, a)
        d = row(pg, "Dan")
        check("Dan：「你设的每 3 天一次」+ 你写的「很热情，买得多」", "你设的每 3 天一次" in d and "很热情，买得多" in d, d)

        # 1. 跟进往后排
        pg.click('[data-fu-later="fu-kim"]'); pg.wait_for_selector("#f-lwhat")
        check("跟进「往后排」：有 明天 / 3 天后 / 一周后 / 两周后 / 不定 / 选日期", pg.locator('#f-when input[name="f-whenr"]').count() == 6 and pg.is_checked('#f-when input[value="3"]'))
        pg.fill("#f-lwhat", "他说下周再要"); pick_when(pg, "7"); save(pg)
        f = fu(pg, "fu-kim"); want = (datetime.date.fromisoformat(TODAY) + datetime.timedelta(days=7)).isoformat()
        check("存了：日期改到一周后，联系记录记一笔「他说下周再要」", f.get("date") == want and (f.get("touches") or [{}])[-1].get("what") == "他说下周再要" and not f.get("done"), {k: f.get(k) for k in ("date", "touches", "done")})
        k = row(pg, "Kim")
        check("列表上写下次哪天、上次联系说了什么", "上次联系" in k and "他说下周再要" in k, k)
        pg.click('[data-fu-sent="fu-kim"]'); pg.wait_for_timeout(400)
        check("再点「已发信息」：等回复，也记一笔", (fu(pg, "fu-kim").get("touches") or [{}])[-1].get("what") == "发了信息" and fu(pg, "fu-kim").get("contacted_at") == TODAY)
        pg.click('[data-fu-later="fu-kim"]'); pg.wait_for_selector("#f-lwhat"); pick_when(pg, "d"); pg.fill("#f-whend", D(-10)); save(pg)
        f = fu(pg, "fu-kim")
        check("等回复的也能往后排（选日期）：日期改了、不再是「等回复」，记录有 3 笔", f.get("date") == D(-10) and not f.get("contacted_at") and len(f.get("touches") or []) == 3, {k: f.get(k) for k in ("date", "contacted_at")})
        pg.click('[data-fu-later="fu-kim"]'); pg.wait_for_selector("#f-lwhat"); pick_when(pg, ""); save(pg)
        check("往后排选「不定」：没日期，还留在列表里", fu(pg, "fu-kim").get("date") is None and "没定日期" in row(pg, "Kim"))

        # 2. 新记跟进：默认不定
        pg.click("#cu-fu-new"); pg.wait_for_selector("#f-cust")
        check("记跟进：日期默认「不定」，不用选日历", pg.is_checked('#f-when input[value=""]') and pg.is_hidden("#f-whend"))
        pg.locator("#f-cust").press_sequentially("Zoe"); pg.fill("#f-funote", "问问还要不要芒果"); save(pg)
        z = next((x for x in S(pg, "followups") if x.get("customer") == "Zoe"), {})
        check("存了：没日期", z and z.get("date") is None and not z.get("done"), z)

        # 3. 自动提醒：往后排 / 不用提醒
        pg.click('[data-au-later="c_amy"]'); pg.wait_for_selector("#f-lwhat")
        check("Amy「联系过了 · 往后排」：默认「按他的节奏（5 天后）」，没有「不定」", pg.is_checked('#f-when input[value="r"]') and "5 天后" in pg.inner_text("#f-when") and pg.locator('#f-when input[value=""]').count() == 0)
        pg.fill("#f-lwhat", "发了新口味"); save(pg)
        c = cust(pg, "c_amy")
        check("记在 Amy 的资料上：下次 5 天后，联系记录一笔；这次先不在列表里", c.get("next") == (datetime.date.fromisoformat(TODAY) + datetime.timedelta(days=5)).isoformat() and (c.get("touches") or [{}])[-1].get("what") == "发了新口味" and "Amy" not in [r.split("\n")[1] for r in rows(pg)], {k: c.get(k) for k in ("next", "touches")})
        pg.click('[data-au-off="c_dan"]'); pg.wait_for_timeout(400)
        check("Dan「不用提醒他」：资料 every = 0，不在列表里；你写的备注还在", cust(pg, "c_dan").get("every") == 0 and cust(pg, "c_dan").get("note") == "很热情，买得多" and "Dan" not in [r.split("\n")[1] for r in rows(pg)], (cust(pg, "c_dan"), [r.split("\n")[1] for r in rows(pg)]))

        # 4. 客户资料：大概多久买一次
        pg.evaluate("""() => { const b = [...document.querySelectorAll('[data-cu]')].find((x) => /Amy/.test(x.innerText)); b.click(); }"""); pg.wait_for_timeout(300)
        det = pg.inner_text(".row .detail:not([hidden])")
        check("Amy 点开：写节奏和下次大概哪天", "按记录大概 5 天买一次" in det and "下次大概" in det, det[:200])
        hist = pg.evaluate("[...document.querySelectorAll('.row .detail:not([hidden]) .ch-o')].map((o) => [...o.children].map((x) => x.className + '|' + x.innerText.replace(/\\n/g, ' ')))")
        first = hist[0] if hist else []
        check("买过什么：最近一单在最上面，日期 + 金额一行", first and first[0].startswith("ch-d|") and "$150" in first[0], first)
        check("下面按系列：Bar Pro 3 根（葡萄冰 ×2、香蕉 ×1），Ali 2 根（粉柠檬 ×2），每个口味一行", [x.split("|")[0] for x in first[1:6]] == ["ch-s", "ch-l", "ch-l", "ch-s", "ch-l"] and "Bar Pro" in first[1] and "3 根" in first[1] and "Ali" in first[4] and "2 根" in first[4], first)
        check("一共写成系列：Bar Pro 6 根 · Ali 3 根", "一共 Bar Pro 6 根 · Ali 3 根" in det.replace("\n", " "), det[:300])
        pg.evaluate("""() => document.querySelector('.row .detail:not([hidden]) [data-cu-edit]').click()"""); pg.wait_for_selector("#f-every")
        check("编辑资料：「大概多久买一次」默认「按他的记录（大概 5 天）」", pg.is_checked('#f-every input[value=""]') and "大概 5 天" in pg.inner_text("#f-every"))
        pg.click('#f-every label:has(input[value="n"])'); pg.fill("#f-everyn", "10"); save(pg)
        c = cust(pg, "c_amy")
        check("自己填 10 天：存 every 10；联系记录还在，往后排的日期按新节奏重算", c.get("every") == 10 and c.get("touches") and not c.get("next"), {k: c.get(k) for k in ("every", "next", "touches")})
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

"""「今天」页（2026-11-23 Bowen）+ 记卖出拿掉「更多」+ 不追的钱算进收入
- 今天找谁：App 自己挑最多 5 个，按「可能性 × 平时一单多少钱」排（规则和回测见 index.html todayPicks 上面的注释）
  只买过一次 1–4 根：第 7–13 天；8 根以上：第 14–28 天；买过 3 天以上：到自己的节奏；有预定 / 资料里「不用提醒」的不列；
  手动记的跟进想要的口味到货了排最前；发了 → 3 天内在「等回复」；3 天没下单再列一次（减半）；问过两次不再列；约好以后再问的在「以后要找的」
- 复制消息（英文；名字里有中文就写中文）；发了 / 没发撤销；库存页最上面一行「今天 交货 N 单 · 找 N 个人」；导航「客户」改叫「今天」；不再贴「重点」
- 记卖出表单没有「更多：日期、下次跟进」：日期 = 今天；编辑有跟进的预定，跟进照旧保留
- 不追的钱：多给「送我的」算多收入，少给不追 / 「不追了」算少收入；收款照旧按实收
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_today.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
D = lambda n: (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=n)).isoformat()
nmz = {"XF-01": "香蕉", "XF-02": "葡萄冰", "XF-03": "蓝莓冰", "XF-04": "粉柠檬"}
def sold(oid, who, n, lines, price=30, **kw):
    return oid, dict({"status": "paid", "date": D(n), "at": D(n) + "T02:00:00Z", "customer": who, "payment": "现金", "delivery_fee": 0, "note": "",
                      "lines": [{"sku": k, "name": nmz[k], "qty": q, "unit_price": price} for k, q in lines]}, **kw)
TOUCH = lambda n, what="发了信息": {"date": D(n), "what": what}
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 10), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 10), "XF-03": IT("XF-03", "Bar Pro", "Blueberry Ice", "蓝莓冰", 10),
                "XF-04": IT("XF-04", "Ali", "Pink Lemon", "粉柠檬", 10)},
      "movements": {f"in-{k}": {"type": "in", "sku": k, "name": nmz[k], "qty": 60, "date": D(40), "at": D(40) + "T01:00:00Z", "note": "进货", "cost": 600} for k in nmz},
      "orders": dict([
          sold("o-amy", "Amy", 9, [("XF-01", 3)]),                                   # 第一次 3 根、9 天前 $90 → 0.21 × 90 = 18.9
          sold("o-ben", "Ben", 3, [("XF-01", 3)]),                                   # 才 3 天 → 不列
          sold("o-cal", "Cal", 9, [("XF-02", 10)]),                                  # 一次 10 根、9 天 → 还早（14–28 天）
          sold("o-dee1", "Dee", 15, [("XF-03", 2)]), sold("o-dee2", "Dee", 10, [("XF-03", 2)]), sold("o-dee3", "Dee", 5, [("XF-03", 2)]),  # 5 天一次 → 0.5 × 60 = 30
          sold("o-eli", "Eli", 9, [("XF-01", 2)]),                                   # 有预定 → 不列
          ("o-eli-r", {"status": "reserved", "date": D(1), "at": D(1) + "T05:00:00Z", "customer": "Eli", "payment": None, "delivery_fee": 0, "note": "老地方", "meet_date": TODAY, "meet_time": "18:00",
                       "lines": [{"sku": "XF-02", "name": "葡萄冰", "qty": 2, "unit_price": 30}], "follow_up": {"date": D(-2), "note": "问问要不要蓝莓", "done": False}}),
          sold("o-fay", "Fay", 9, [("XF-01", 2)]),                                   # 资料里「不用提醒」→ 不列
          sold("o-gus", "Gus", 10, [("XF-02", 2)], price=150, bal=[{"amt": -10, "why": "没零钱找", "kind": "diff", "gift": True, "date": D(10)}]),  # 0.21 × 300 = 63；多给 $10 送我的
          sold("o-hal", "Hal", 8, [("XF-01", 2)]),                                   # 昨天发了 → 等回复
          sold("o-ivy", "Ivy", 12, [("XF-01", 2)]),                                  # 4 天前发了没回 → 再列一次，减半 6.3
          sold("o-jon", "Jon", 11, [("XF-01", 2)]),                                  # 发了两次 → 不列
          sold("o-lou", "Lou", 9, [("XF-01", 2)]),                                   # 约好三天后再问 → 以后要找的
          sold("o-wf", "王芳", 9, [("XF-04", 2)], price=35),                         # 0.21 × 70 = 14.7，中文消息
          sold("o-pat", "Pat", 9, [("XF-01", 2)], bal=[{"amt": 5, "why": "没有零钱", "kind": "diff", "gift": True, "date": D(9)}]),   # 12.6；少给 $5 不追
          sold("o-qui", "Quinn", 9, [("XF-01", 2)], bal=[{"amt": 20, "why": "配送费没给", "kind": "diff", "date": D(9)}, {"amt": -20, "why": "不追了", "kind": "waive", "date": D(2)}]),  # 12.6；后来不追了 $20
          sold("o-mo1", "Mo", 20, [("XF-01", 1)]), sold("o-mo2", "Mo", 8, [("XF-01", 1)]),   # 12 天前发了，4 天后下单 → 「7 天内下单 1 / 1」
      ]),
      "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {},
      "customers": {"c_amy": {"name": "Amy", "key": "amy", "type": "retail", "place": "IGA"},
                    "c_fay": {"name": "Fay", "key": "fay", "type": "retail", "every": 0},
                    "c_hal": {"name": "Hal", "key": "hal", "type": "retail", "touches": [TOUCH(1)]},
                    "c_ivy": {"name": "Ivy", "key": "ivy", "type": "retail", "touches": [TOUCH(4)]},
                    "c_jon": {"name": "Jon", "key": "jon", "type": "retail", "touches": [TOUCH(8), TOUCH(4)]},
                    "c_lou": {"name": "Lou", "key": "lou", "type": "retail", "next": D(-3), "touches": [TOUCH(2, "他说下周")]},
                    "c_mo": {"name": "Mo", "key": "mo", "type": "retail", "touches": [TOUCH(12)]}},
      "followups": {"fu-kim": {"customer": "Kim", "wants": [{"sku": "XF-02", "name": "葡萄冰", "qty": 2}], "note": "", "date": D(1), "done": False, "created_at": D(5) + "T01:00:00Z"}}}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}
EXPOSE = "\nwindow.__GM = { S, todayPicks };\n})();"
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
def save(pg):
    pg.wait_for_timeout(200); pg.click("#sheet-save")
    try: pg.wait_for_selector("#sheet", state="hidden", timeout=3000)
    except Exception: pass
    pg.wait_for_timeout(450)
def picks(pg): return pg.evaluate("[...document.querySelectorAll('#fu-list > .fu2 .fu-l1 b')].map((b) => b.textContent)")
def fold(pg, cls): return pg.evaluate(f"[...document.querySelectorAll('#fu-list .{cls} .fu2 .fu-l1 b')].map((b) => b.textContent)")
def row(pg, who): return pg.locator("#fu-list .fu2").filter(has=pg.locator(f'.fu-l1 b:text-is("{who}")')).first
def cust(pg, cid): return next((x for x in S(pg, "customers") if x["id"] == cid), {})
def clip(pg): return pg.evaluate("navigator.clipboard.readText()")
TOTAL = sum(sum(l["qty"] * l["unit_price"] for l in o["lines"]) for o in V1["orders"].values() if o["status"] == "paid")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN", permissions=["clipboard-read", "clipboard-write"])
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
        print("== " + mode)

        # 1. 库存页最上面一行 + 导航
        go(pg, "inventory")
        st = pg.inner_text("#td-strip")
        check("库存页快速下单上面一行：今天 交货 1 单 · 找 5 个人", pg.is_visible("#td-strip") and "交货 1 单" in st and "找 5 个人" in st, st)
        check("那一行在快速下单上面", pg.evaluate("(() => { const a = document.getElementById('td-strip'), b = document.getElementById('qo-sec'); return !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING); })()"))
        check("导航「客户」改叫「今天」，角标 6（交货 1 + 找 5）", pg.inner_text("#nav-cu").replace("\n", "").endswith("今天") and pg.inner_text("#cu-badge") == "6", pg.inner_text("#nav-cu"))
        pg.click("#td-strip"); pg.wait_for_timeout(400)
        check("点那一行到「今天」页", pg.evaluate("location.hash") == "#customers" and pg.inner_text("#view-title") == "今天")

        # 2. 今天找谁：挑谁、怎么排
        check("最多 5 个，按可能带来的钱排：Kim（想要的到货了）、Gus、Dee、Amy、王芳", picks(pg) == ["Kim", "Gus", "Dee", "Amy", "王芳"], picks(pg))
        check("还可以找：Pat、Quinn、Ivy（4 天前发过没回，减半排后面）", fold(pg, "fu-more") == ["Pat", "Quinn", "Ivy"], fold(pg, "fu-more"))
        check("等回复：Hal（昨天发的）", fold(pg, "fu-wait") == ["Hal"], fold(pg, "fu-wait"))
        check("以后要找的：Lou（约好三天后再问）", fold(pg, "fu-later") == ["Lou"], fold(pg, "fu-later"))
        allnames = picks(pg) + fold(pg, "fu-more") + fold(pg, "fu-wait") + fold(pg, "fu-later")
        check("不列：Ben（才 3 天）、Cal（一次 10 根还早）、Eli（有预定）、Fay（不用提醒）、Jon（问过两次）、Mo（还没到）", not set(allnames) & {"Ben", "Cal", "Eli", "Fay", "Jon", "Mo"}, allnames)
        t = row(pg, "Gus").inner_text()
        check("每行：为什么找他 + 平时一单多少；复制消息 / 发了 不用点开", "买过一次 2 根 · 10 天前" in t and "平时一单 $300" in t and row(pg, "Gus").locator("[data-td-copy]").is_visible() and row(pg, "Gus").locator("[data-td-sent]").is_visible(), t)
        check("Ivy 写「4 天前发过，没回」", "4 天前发过，没回" in pg.evaluate("[...document.querySelectorAll('#fu-list .fu-more .fu2')].map((r) => r.textContent).join('|')"))
        check("Dee 写自己的节奏", "平时 5 天左右买一次 · 上次 5 天前" in row(pg, "Dee").inner_text(), row(pg, "Dee").inner_text())
        check("不再贴「重点」（今天找谁、预定卡片）", pg.locator("#fu-list .tag-vip, #resv .tag-vip").count() == 0)
        check("发了以后 7 天内下单：1 / 2 次（Mo 下了，Jon 8 天前那次没下）· 还有 3 次没满 7 天（Hal、Ivy、Jon）", pg.inner_text("#td-stat") == "发了信息的，7 天内下单 1 / 2 次 · 还有 3 次没满 7 天", pg.inner_text("#td-stat"))

        # 3. 复制消息
        row(pg, "Amy").locator("[data-td-copy]").click(); pg.wait_for_timeout(300)
        m = clip(pg)
        check("Amy 的消息：英文、常买的口味有货、见面地点", m.startswith("Hi Amy!") and "Bar Pro Banana Buzz" in m and "IGA" in m, m)
        check("点复制不会展开那一条", not pg.evaluate("[...document.querySelectorAll('#fu-list .fu2')].find((r) => r.querySelector('.fu-l1 b').textContent === 'Amy').open"))
        row(pg, "王芳").locator("[data-td-copy]").click(); pg.wait_for_timeout(300)
        m = clip(pg)
        check("名字是中文就写中文：王芳 你好！… 粉柠檬", m.startswith("王芳 你好！") and "粉柠檬" in m, m)
        row(pg, "Kim").locator("[data-td-copy]").click(); pg.wait_for_timeout(300)
        m = clip(pg)
        check("Kim 想要的葡萄冰到货了：消息里说到货了", "Grape Ice" in m and "back in stock" in m, m)

        # 4. 发了 → 等回复；撤销
        row(pg, "Amy").locator("[data-td-sent]").click(); pg.wait_for_timeout(600)
        tc = cust(pg, "c_amy").get("touches") or []
        check("Amy 发了：资料里记一笔「发了信息」，挪到「等回复」，Pat 补上来", tc and tc[-1] == {"date": TODAY, "what": "发了信息"} and "Amy" in fold(pg, "fu-wait") and picks(pg) == ["Kim", "Gus", "Dee", "王芳", "Pat"], (tc, picks(pg), fold(pg, "fu-wait")))
        pg.evaluate("[...document.querySelectorAll('#fu-list .fu-wait')].forEach((d) => d.open = true)"); pg.wait_for_timeout(100)
        row(pg, "Amy").locator("[data-td-unsent]").click(); pg.wait_for_timeout(600)
        check("没发，撤销：那一笔去掉，Amy 回到今天找谁", not (cust(pg, "c_amy").get("touches") or []) and "Amy" in picks(pg), (cust(pg, "c_amy"), picks(pg)))
        row(pg, "Kim").locator("[data-td-sent]").click(); pg.wait_for_timeout(600)
        f = next(x for x in S(pg, "followups") if x["id"] == "fu-kim")
        check("手动记的跟进 Kim 发了：contacted_at 今天、记一笔，挪到等回复", f.get("contacted_at") == TODAY and (f.get("touches") or [{}])[-1].get("what") == "发了信息" and "Kim" in fold(pg, "fu-wait"), f)

        # 5. 记卖出：没有「更多」，日期 = 今天
        go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
        check("记卖出没有「更多：日期、下次跟进」", pg.locator("#sheet #f-more, #sheet #f-date, #sheet #f-fu, #sheet #f-funote").count() == 0)
        pg.fill("#f-skuq-0", "蓝莓"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1"); pg.locator("#f-cust").press_sequentially("Zed"); pg.click('#f-paychips label:has(input[value="现金"])'); save(pg)
        if pg.is_visible("#sheet"): print("   表单没关：", pg.evaluate("[...document.querySelectorAll('#sheet .err, #sheet-err, #sheet [role=alert], .toast')].map(e => e.id + ':' + e.textContent).join(' | ')"))
        z = next((x for x in S(pg, "orders") if x.get("customer") == "Zed"), {})
        check("记下来的日期是今天", z.get("date") == TODAY, z.get("date"))
        go(pg, "customers")
        pg.evaluate("""() => document.querySelector('[data-edit-order="o-eli-r"]').click()"""); pg.wait_for_selector("#f-note", state="attached")
        pg.fill("#f-note", "老地方 7 点"); save(pg)
        e = next(x for x in S(pg, "orders") if x["id"] == "o-eli-r")
        check("编辑有跟进的预定：跟进照旧留着，日期不变", e.get("note") == "老地方 7 点" and (e.get("follow_up") or {}).get("note") == "问问要不要蓝莓" and e.get("date") == D(1), {k: e.get(k) for k in ("note", "follow_up", "date")})

        # 6. 不追的钱算进收入
        go(pg, "finance"); pg.click('#period [data-p="all"]'); pg.wait_for_timeout(400)
        inc = pg.inner_text("#f-inc"); exp_inc = TOTAL + 60 - 15  # Zed 那单 $60（售价）；Gus 多给 +10、Pat 少给 −5、Quinn 不追了 −20
        check(f"收入 = 订单合计 + 多给 10 − 少给 5 − 不追了 20 = ${exp_inc}", inc.replace(",", "") == f"${exp_inc}", inc)
        stmt = pg.evaluate("document.getElementById('f-stmt').textContent")
        check("利润表：客人多给（送我的）$10、少给不追了 −$25", "客人多给（送我的）$10" in stmt and "少给不追了−$25" in stmt, stmt[:300])
        sers = pg.inner_text("#f-sers")
        check("收入下面写「少给不追 −$15」", "少给不追 −$15" in sers, sers)
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

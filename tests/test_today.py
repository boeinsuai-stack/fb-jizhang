"""客户页重做（2026-11-24 Bowen：客户板块混乱几乎没帮助）+ 记卖出拿掉「更多」+ 不追的钱算进收入
- 导航：库存 · 预定 · 订货 · 财务 · 客户 · 合伙人；设置挪到标题右上角；预定单独一页
- 客户页三个标签：要找 / 等回复 / 约好以后，一次看一个，按钮直接摆出来（复制消息 · 发了 · 过几天 · 不跟了）
  要找只有三种：到货了、约好今天（没定日子的手动跟进 = 你记的）、该补货（买过 2 天以上的老客到节奏，最多 5 个，按平时一单多少钱排）
  只买过一次的新客不再列；想要的口味没到货的在「约好以后 · 等到货」，到货那天回到要找
- 下面「找客人」：没打字列最近 8 个，打字搜；点一下弹出他的资料（买过什么、记一单 / 记预定 / 编辑资料）
- 库存页最上面一行：「交货 N 单 ›」到预定页、「要找 N 个人 ›」到客户页
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
nmz = {"XF-01": "香蕉", "XF-02": "葡萄冰", "XF-03": "蓝莓冰", "XF-04": "粉柠檬", "XF-05": "芒果"}
def sold(oid, who, n, lines, price=30, **kw):
    return oid, dict({"status": "paid", "date": D(n), "at": D(n) + "T02:00:00Z", "customer": who, "payment": "现金", "delivery_fee": 0, "note": "",
                      "lines": [{"sku": k, "name": nmz[k], "qty": q, "unit_price": price} for k, q in lines]}, **kw)
TOUCH = lambda n, what="发了信息": {"date": D(n), "what": what}
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 10), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 10), "XF-03": IT("XF-03", "Bar Pro", "Blueberry Ice", "蓝莓冰", 10),
                "XF-04": IT("XF-04", "Ali", "Pink Lemon", "粉柠檬", 10), "XF-05": IT("XF-05", "Ali", "Mango", "芒果", 10)},
      "movements": {f"in-{k}": {"type": "in", "sku": k, "name": nmz[k], "qty": 60, "date": D(40), "at": D(40) + "T01:00:00Z", "note": "进货", "cost": 600} for k in nmz if k != "XF-05"},  # 芒果没货
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
          sold("o-wes", "Wes", 9, [("XF-04", 2)], price=35),                         # 只买过一次 → 不列
          # 老客（买过 2 天，隔 7 天，上次 7 天前）→ 该补货，按平时一单多少钱排，最多 5 个：Rae 100、Tia 90、Sky 80、王芳 70、Dee 60；Vic 50 排不上
          sold("o-rae1", "Rae", 14, [("XF-01", 2)], price=50), sold("o-rae2", "Rae", 7, [("XF-01", 2)], price=50),
          sold("o-tia1", "Tia", 14, [("XF-01", 2)], price=45), sold("o-tia2", "Tia", 7, [("XF-01", 2)], price=45),
          sold("o-sky1", "Sky", 14, [("XF-01", 2)], price=40), sold("o-sky2", "Sky", 7, [("XF-01", 2)], price=40),
          sold("o-wf1", "王芳", 14, [("XF-04", 2)], price=35), sold("o-wf2", "王芳", 7, [("XF-04", 2)], price=35),
          sold("o-vic1", "Vic", 14, [("XF-01", 2)], price=25), sold("o-vic2", "Vic", 7, [("XF-01", 2)], price=25),
          sold("o-pat", "Pat", 9, [("XF-01", 2)], bal=[{"amt": 5, "why": "没有零钱", "kind": "diff", "gift": True, "date": D(9)}]),   # 12.6；少给 $5 不追
          sold("o-qui", "Quinn", 9, [("XF-01", 2)], bal=[{"amt": 20, "why": "配送费没给", "kind": "diff", "date": D(9)}, {"amt": -20, "why": "不追了", "kind": "waive", "date": D(2)}]),  # 12.6；后来不追了 $20
          sold("o-mo1", "Mo", 20, [("XF-01", 1)]), sold("o-mo2", "Mo", 8, [("XF-01", 1)]),   # 12 天前发了，4 天后下单 → 「7 天内下单 1 / 1」
      ]),
      "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {},
      "customers": {"c_amy": {"name": "Amy", "key": "amy", "type": "retail", "place": "IGA"}, "c_rae": {"name": "Rae", "key": "rae", "type": "retail", "place": "IGA"},
                    "c_fay": {"name": "Fay", "key": "fay", "type": "retail", "every": 0},
                    "c_hal": {"name": "Hal", "key": "hal", "type": "retail", "touches": [TOUCH(1)]},
                    "c_ivy": {"name": "Ivy", "key": "ivy", "type": "retail", "touches": [TOUCH(4)]},
                    "c_jon": {"name": "Jon", "key": "jon", "type": "retail", "touches": [TOUCH(8), TOUCH(4)]},
                    "c_lou": {"name": "Lou", "key": "lou", "type": "retail", "next": D(-3), "touches": [TOUCH(2, "他说下周")]},
                    "c_mo": {"name": "Mo", "key": "mo", "type": "retail", "touches": [TOUCH(12)]}},
      "followups": {"fu-kim": {"customer": "Kim", "wants": [{"sku": "XF-02", "name": "葡萄冰", "qty": 2}], "note": "", "date": D(1), "done": False, "created_at": D(5) + "T01:00:00Z"},  # 到货了
                    "fu-nia": {"customer": "Nia", "wants": [{"sku": "XF-05", "name": "芒果", "qty": 2}], "note": "", "date": None, "done": False, "created_at": D(3) + "T01:00:00Z"},  # 芒果没货 → 等到货
                    "fu-oli": {"customer": "Oli", "wants": [], "note": "问问要不要两盒", "date": None, "done": False, "created_at": D(3) + "T01:00:00Z"},  # 你记的
                    "fu-pia": {"customer": "Pia", "wants": [], "note": "他说过几天", "date": D(2), "done": False, "created_at": D(6) + "T01:00:00Z"}}}  # 约好前天
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
def names(pg): return pg.evaluate("[...document.querySelectorAll('#fu-list .cx-row .cx-who')].map((b) => b.textContent)")
def tags(pg): return pg.evaluate("[...document.querySelectorAll('#fu-list .cx-row')].map((r) => (r.querySelector('.cx-tag') || {}).textContent || '')")
def row(pg, who): return pg.locator("#fu-list .cx-row").filter(has=pg.locator(f'.cx-who:text-is("{who}")')).first
def tab(pg, t): pg.click(f'#cx-tabs [data-cx="{t}"]'); pg.wait_for_timeout(250)
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

        MD = lambda n: f"{int(D(n)[5:7])}月{int(D(n)[8:])}日"
        # 1. 导航、库存页最上面一行
        go(pg, "inventory")
        nav = pg.evaluate("[...document.querySelectorAll('nav.switch a')].map((a) => a.innerText.replace(/\\s|\\d/g, ''))")
        check("底部导航：库存 · 预定 · 订货 · 财务 · 客户 · 合伙人（设置挪到右上角）", nav == ["库存", "预定", "订货", "财务", "客户", "合伙人"] and pg.is_visible("header #nav-set"), nav)
        st = pg.evaluate("document.getElementById('td-strip').textContent")
        check("库存页上面一行：交货 1 单 › · 要找 8 个人 ›", "交货 1 单" in st and "要找 8 个人" in st and pg.locator("#td-strip a[href='#reserve']").count() == 1 and pg.locator("#td-strip a[href='#customers']").count() == 1, st)
        check("那一行在快速下单上面", pg.evaluate("(() => { const a = document.getElementById('td-strip'), b = document.getElementById('qo-sec'); return !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING); })()"))
        check("角标：预定 1（今天交货）、客户 8（要找）", pg.inner_text("#rv-badge") == "1" and pg.inner_text("#cu-badge") == "8", (pg.inner_text("#rv-badge"), pg.inner_text("#cu-badge")))
        pg.click("#td-strip a[href='#reserve']"); pg.wait_for_timeout(400)
        check("点「交货」到预定页：只有预定", pg.inner_text("#view-title") == "预定" and pg.locator("#rv-view [data-settle='o-eli-r']").count() == 1 and pg.locator("#rv-view .tag-vip").count() == 0)
        go(pg, "inventory"); pg.click("#td-strip a[href='#customers']"); pg.wait_for_timeout(400)
        check("点「要找」到客户页，标题「客户」，右上角「＋ 记要找的人」", pg.evaluate("location.hash") == "#customers" and pg.inner_text("#view-title") == "客户" and pg.is_visible("#hd-fu"))

        # 2. 要找：只有三种，按 到货了 → 约好 → 你记的 → 该补货
        check("要找：Kim（到货了）、Pia（约好）、Oli（你记的）、Rae、Tia、Sky、王芳、Dee（该补货，最多 5 个，按一单多少钱）", names(pg) == ["Kim", "Pia", "Oli", "Rae", "Tia", "Sky", "王芳", "Dee"], names(pg))
        check("标签：到货了 / 约好 X月X日 / 你记的 / 该补货", tags(pg) == ["到货了", "约好 " + MD(2), "你记的"] + ["该补货"] * 5, tags(pg))
        check("标签上的数字：要找 8", pg.inner_text("#cx-n-find") == "8")
        t = row(pg, "Rae").inner_text()
        check("Rae：为什么找他 + 一单多少；四个按钮直接摆出来", "买过 2 次 · 上次 7 天前" in t and "一单 $100" in t and all(row(pg, "Rae").locator(f"[{a}]").is_visible() for a in ("data-td-copy", "data-td-sent", "data-td-later", "data-td-off")), t)
        check("Dee 写自己的节奏", "平时 5 天左右买一次 · 上次 5 天前" in row(pg, "Dee").inner_text(), row(pg, "Dee").inner_text())
        check("Kim 想要的写现在有几根", "现在有" in row(pg, "Kim").inner_text(), row(pg, "Kim").inner_text())
        tab(pg, "wait"); w = names(pg)
        check("等回复：Hal，写哪天发的；按钮 他要了 · 记预定 / 过几天 / 没发", w == ["Hal"] and MD(1) + " 发的" in row(pg, "Hal").inner_text() and row(pg, "Hal").locator("[data-au-resv]").is_visible() and row(pg, "Hal").locator("[data-td-unsent]").is_visible(), (w, row(pg, "Hal").inner_text()))
        tab(pg, "later"); l = names(pg)
        check("约好以后：Lou（约好的日子）、Nia（等到货）", l == ["Lou", "Nia"] and tags(pg)[1] == "等到货", (l, tags(pg)))
        check("Lou 写上次联系的日子和说法", "上次联系 " + MD(2) + "：他说下周" in row(pg, "Lou").inner_text(), row(pg, "Lou").inner_text())
        allnames = l + w; tab(pg, "find"); allnames += names(pg)
        check("不列：只买过一次的（Amy、Gus、Wes…）、Ben、Cal、Eli（有预定）、Fay（不用提醒）、Jon（问过两次）、Mo（还没到）、Vic（第 6 个老客）", not set(allnames) & {"Amy", "Gus", "Wes", "Pat", "Quinn", "Ivy", "Ben", "Cal", "Eli", "Fay", "Jon", "Mo", "Vic"}, allnames)

        # 3. 复制消息
        row(pg, "Rae").locator("[data-td-copy]").click(); pg.wait_for_timeout(300)
        m = clip(pg)
        check("Rae 的消息：英文、常买的口味有货、见面地点", m.startswith("Hi Rae!") and "Bar Pro Banana Buzz" in m and "IGA" in m, m)
        row(pg, "王芳").locator("[data-td-copy]").click(); pg.wait_for_timeout(300)
        m = clip(pg)
        check("名字是中文就写中文：王芳 你好！… 粉柠檬", m.startswith("王芳 你好！") and "粉柠檬" in m, m)
        row(pg, "Kim").locator("[data-td-copy]").click(); pg.wait_for_timeout(300)
        m = clip(pg)
        check("Kim 想要的葡萄冰到货了：消息里说到货了", "Grape Ice" in m and "back in stock" in m, m)

        # 4. 发了 → 等回复；没发撤销
        row(pg, "Rae").locator("[data-td-sent]").click(); pg.wait_for_timeout(600)
        tc = cust(pg, "c_rae").get("touches") or []
        check("Rae 发了：资料里记一笔「发了信息」，离开要找，Vic 补上来", tc and tc[-1] == {"date": TODAY, "what": "发了信息"} and "Rae" not in names(pg) and "Vic" in names(pg), (tc, names(pg)))
        tab(pg, "wait")
        check("Rae 在等回复，写今天发的", names(pg) == ["Rae", "Hal"] and MD(0) + " 发的" in row(pg, "Rae").inner_text(), names(pg))
        row(pg, "Rae").locator("[data-td-unsent]").click(); pg.wait_for_timeout(600)
        check("没发：那一笔去掉，Rae 回到要找", not (cust(pg, "c_rae").get("touches") or []) and names(pg) == ["Hal"], (cust(pg, "c_rae"), names(pg)))
        tab(pg, "find")
        row(pg, "Kim").locator("[data-td-sent]").click(); pg.wait_for_timeout(600)
        f = next(x for x in S(pg, "followups") if x["id"] == "fu-kim")
        check("手动记的 Kim 发了：contacted_at 今天、记一笔，挪到等回复", f.get("contacted_at") == TODAY and (f.get("touches") or [{}])[-1].get("what") == "发了信息" and "Kim" not in names(pg), f)

        # 5. 过几天 → 约好以后
        row(pg, "Dee").locator("[data-td-later]").click(); pg.wait_for_selector("#f-lwq")
        opts = pg.evaluate("[...document.querySelectorAll('#f-when label')].map((l) => l.textContent.trim())")
        check("过几天：明天 / 3 天后 / 一周后 / 选日期，默认 3 天后；他怎么说的 4 个", opts == ["明天", "3 天后", "一周后", "选日期"] and pg.is_checked('input[name="f-whenr"][value="3"]') and pg.locator("#f-lwq [data-lw]").count() == 4, opts)
        pg.click('#f-lwq [data-lw="他说下周"]'); pg.click('#f-when label:has(input[value="7"])'); save(pg)
        dee = next(x for x in S(pg, "customers") if x.get("name") == "Dee")
        check("Dee 记下：下次 一周后、说法「他说下周」，到约好以后", dee.get("next") == D(-7) and dee["touches"][-1] == {"date": TODAY, "what": "他说下周"} and "Dee" not in names(pg), dee)
        tab(pg, "later")
        check("约好以后按日子：Lou、Dee、Nia（等到货排最后）", names(pg) == ["Lou", "Dee", "Nia"], names(pg))

        # 6. 改日子：只改哪天，不多记一笔
        row(pg, "Lou").locator("[data-td-date]").click(); pg.wait_for_selector("#f-when")
        pg.click('#f-when label:has(input[value="1"])'); save(pg)
        lou = next(x for x in S(pg, "customers") if x["id"] == "c_lou")
        check("改日子 Lou → 明天；联系记录不变", lou.get("next") == D(-1) and len(lou.get("touches") or []) == 1, lou)

        # 7. 不跟了：点两下
        tab(pg, "find")
        b = row(pg, "Oli").locator("[data-td-off]"); b.click(); pg.wait_for_timeout(150)
        check("不跟了：第一下只是问「确定不跟了？」", b.inner_text() == "确定不跟了？" and not next(x for x in S(pg, "followups") if x["id"] == "fu-oli").get("done"))
        b.click(); pg.wait_for_timeout(500)
        check("再点：手动记的 Oli 关掉", next(x for x in S(pg, "followups") if x["id"] == "fu-oli").get("done") is True and "Oli" not in names(pg))
        b = row(pg, "Tia").locator("[data-td-off]"); b.click(); pg.wait_for_timeout(150); b.click(); pg.wait_for_timeout(500)
        tia = next(x for x in S(pg, "customers") if x.get("name") == "Tia")
        check("老客 Tia 不跟了：记一笔「不跟了」（不是永远不提醒），哪个标签都没有", tia["touches"][-1] == {"date": TODAY, "what": "不跟了"} and tia.get("every") is None and "Tia" not in names(pg) and pg.inner_text("#cx-n-later") == "3", tia)

        # 8. 等到货的到货了 → 回到要找
        pg.evaluate("(m) => window.__remoteWrite(m, 'in-mango', { type: 'in', sku: 'XF-05', name: '芒果', qty: 10, date: '" + TODAY + "', at: '" + TODAY + "T01:00:00Z', note: '进货', cost: 100 })", "v2_movements" if mode == "新结构" else "movements")
        pg.wait_for_timeout(800)
        check("芒果到货：Nia 回到要找，标「到货了」", names(pg)[:1] == ["Nia"] and tags(pg)[0] == "到货了", (names(pg), tags(pg)))

        # 9. 找客人 + 他的资料
        check("找客人：没打字列最近 8 个", pg.locator("#c-list .cx-c").count() == 8 and "打名字找" in pg.inner_text("#c-list"))
        pg.fill("#cq", "gus"); pg.wait_for_timeout(250)
        check("打 gus：只剩 Gus", pg.evaluate("[...document.querySelectorAll('#c-list .cx-c b')].map((b) => b.textContent)") == ["Gus"])
        pg.click("#c-list .cx-c"); pg.wait_for_timeout(300)
        sh = pg.inner_text("#sheet")
        check("点一下弹出 Gus 的资料：买过什么、记一单 / 记预定 / 编辑资料，只有「关闭」", pg.inner_text("#sheet-title") == "Gus" and "多给 $10" in sh and pg.locator("#sheet [data-cu-sale]").count() == 1 and pg.locator("#sheet [data-cu-edit]").count() == 1 and not pg.is_visible("#sheet-save"), sh[:200])
        pg.click("#sheet [data-cu-edit]"); pg.wait_for_selector("#f-ccontact")
        check("从资料里点「编辑资料」打开资料表单", pg.inner_text("#sheet-title") == "客户资料 · Gus")
        pg.click("#sheet [data-close]"); pg.fill("#cq", "")
        row(pg, "Rae").locator(".cx-who").click(); pg.wait_for_timeout(300)
        check("要找里点名字也弹出他的资料", pg.inner_text("#sheet-title") == "Rae"); pg.click("#sheet [data-close]")
        pg.click("#hd-fu"); pg.wait_for_selector("#f-cust")
        check("右上角「＋ 记要找的人」", pg.inner_text("#sheet-title") == "记要找的人"); pg.click("#sheet [data-close]")
        pg.click("header #nav-set"); pg.wait_for_timeout(300)
        check("右上角设置 → 设置页", pg.inner_text("#view-title") == "设置" and not pg.is_visible("#hd-fu"))

        # 10. 记卖出：没有「更多」，日期 = 今天
        go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
        check("记卖出没有「更多：日期、下次跟进」", pg.locator("#sheet #f-more, #sheet #f-date, #sheet #f-fu, #sheet #f-funote").count() == 0)
        pg.fill("#f-skuq-0", "蓝莓"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1"); pg.locator("#f-cust").press_sequentially("Zed"); pg.click('#f-paychips label:has(input[value="现金"])'); save(pg)
        if pg.is_visible("#sheet"): print("   表单没关：", pg.evaluate("[...document.querySelectorAll('#sheet .err, #sheet-err, #sheet [role=alert], .toast')].map(e => e.id + ':' + e.textContent).join(' | ')"))
        z = next((x for x in S(pg, "orders") if x.get("customer") == "Zed"), {})
        check("记下来的日期是今天", z.get("date") == TODAY, z.get("date"))
        go(pg, "reserve")
        pg.evaluate("""() => document.querySelector('[data-edit-order="o-eli-r"]').click()"""); pg.wait_for_selector("#f-note", state="attached")
        pg.fill("#f-note", "老地方 7 点"); save(pg)
        e = next(x for x in S(pg, "orders") if x["id"] == "o-eli-r")
        check("编辑有跟进的预定：跟进照旧留着，日期不变", e.get("note") == "老地方 7 点" and (e.get("follow_up") or {}).get("note") == "问问要不要蓝莓" and e.get("date") == D(1), {k: e.get(k) for k in ("note", "follow_up", "date")})

        # 11. 不追的钱算进收入
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

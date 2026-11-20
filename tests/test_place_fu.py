"""要联系的客户重排 + 重点客户 + 见面地点（2026-11-21 Bowen）
- 要联系的客户：手动跟进和自动提醒合成一个列表，按日子从早到晚（过了的最上面），没定日子的在后面，三天以后的收进「以后」；有预定 / 记跟进以后又买过的不列
- 每条默认收起（哪天 · 谁 · 为什么），点开才有四个按钮：记预定 / 联系过了 / 不用跟了 / 改；「联系过了」有常用说法一点就填
- 重点客户：一次买过 8 根以上的零售客（批发不算），客户资料可以手动勾 / 取消；没有自己节奏的买完两周提醒；客户页「重点客户」最久没买的在上面
- 见面地点：标题「地点」→ 每个地点写好发给客人的话，点「复制」；客户资料「一般在哪见面」「一般几点方便联系」；
  记预定写了客人名字自动带上；预定卡片写「暂未确定时间」「下午 4–6 点联系」、有「复制地点」；新地点自动进地点库、客人自动打上标签；改名字跟着改
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_place_fu.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
D = lambda n: (datetime.date.fromisoformat(TODAY) + datetime.timedelta(days=n)).isoformat()
def PAID(oid, who, d, q): return (oid, {"status": "paid", "date": d, "at": d + "T03:00:00Z", "customer": who, "lines": [{"sku": "XF-01", "name": "香蕉", "qty": q, "unit_price": 60}], "delivery_fee": 0, "payment": "现金", "note": ""})
def FU(fid, who, d, note, created): return (fid, {"customer": who, "wants": [], "note": note, "date": d, "done": False, "created_at": created + "T02:00:00Z"})
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 30)},
      "movements": {"m-in": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 200, "date": D(-30), "at": D(-30) + "T01:00:00Z", "cost": 6000, "note": "进货"}},
      "orders": dict([PAID("o-b1", "Ben", D(-17), 1), PAID("o-b2", "Ben", D(-12), 1), PAID("o-b3", "Ben", D(-7), 1), PAID("o-c1", "Cat", D(-20), 10), PAID("o-h1", "Hal", D(-20), 50), PAID("o-g1", "Gus", D(-2), 1),
                      ("o-f1", {"status": "reserved", "date": D(-1), "at": D(-1) + "T03:00:00Z", "customer": "Fay", "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 2, "unit_price": 60}], "delivery_fee": 0, "payment": "", "note": ""})]),
      "followups": dict([FU("fu-a", "Amy", D(-3), "要一盒 Ali", D(-6)), FU("fu-d", "Dan", None, "葡萄冰到货告诉他", D(-4)), FU("fu-e", "Eve", D(5), "下周问", D(-1)), FU("fu-k", "Kit", D(1), "明天问", D(-1)), FU("fu-l", "Lou", D(2), "后天问", D(-1)), FU("fu-f", "Fay", D(-1), "问一下", D(-3)), FU("fu-g", "Gus", D(-4), "过几天", D(-5))]),
      "customers": {"c_hal": {"name": "Hal", "key": "hal", "type": "wholesale", "created_at": D(-20) + "T00:00:00Z"}},
      "expenses": {}, "purchases": {}, "settlements": {}, "transfers": {}}
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
def cust(pg, n): return next((c for c in S(pg, "customers") if c.get("name") == n), {})
def order(pg, oid): return next((x for x in S(pg, "orders") if x["id"] == oid), {})
def fu_names(pg): return pg.evaluate("[...document.querySelectorAll('#fu-list > .fu2 > summary .fu-l1 b')].map((b) => b.innerText)")
def fold_names(pg): return pg.evaluate("[...document.querySelectorAll('#fu-list .fu-later .fu2 > summary .fu-l1 b')].map((b) => b.textContent)")
def row(pg, n): return pg.locator("#fu-list .fu2").filter(has=pg.locator(f'.fu-l1 b:text-is("{n}")'))
def resv(pg, who, extra=None):
    go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0"); pg.check("#f-resv")
    pg.fill("#f-skuq-0", "香蕉"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1")
    pg.fill("#f-cust", who); pg.dispatch_event("#f-cust", "change"); pg.wait_for_timeout(200)
    if extra: extra()
def fmt(d): x = datetime.date.fromisoformat(d); return f"{x.month}月{x.day}日"

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=URL.rsplit("/", 1)[0])
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
        print("== " + mode)
        go(pg, "customers"); pg.wait_for_timeout(300)
        names = fu_names(pg)
        check("离今天近的在上面：Kit（明天）→ Lou（后天）→ Ben（按节奏，已过 2 天）→ Amy（已过 3 天）→ Cat（重点，已过 6 天）→ Dan（没定日子）", names == ["Kit", "Lou", "Ben", "Amy", "Cat", "Dan"], names)
        check("三天以后的收进「以后」：Eve", fold_names(pg) == ["Eve"] and "以后要找的 · 1 个" in pg.inner_text("#fu-list .fu-later > summary"), fold_names(pg))
        check("有预定的 Fay、记跟进以后又买了的 Gus 不列", "Fay" not in names and "Gus" not in names)
        lbl = pg.evaluate("[...document.querySelectorAll('#fu-list > .fu2 .fu-when')].map((x) => x.innerText)")
        check("日子写「明天 / 后天 / 已过 2 天 / 已过 3 天 / 已过 6 天 / 没定日期」", lbl == ["明天", "后天", "已过 2 天", "已过 3 天", "已过 6 天", "没定日期"], lbl)
        c1 = row(pg, "Cat").first
        check("Cat 标「重点」，写「一次买过 10 根」", c1.locator(".tag-vip").count() == 1 and "一次买过 10 根" in c1.locator(".fu-why").inner_text(), c1.inner_text())
        check("收起时看不到按钮", not c1.locator("[data-au-resv]").is_visible())
        c1.locator("summary").click(); pg.wait_for_timeout(200)
        bt = c1.locator(".l-actions button").all_inner_texts()
        check("点开：记预定 / 联系过了 / 不用跟了 / 改", bt == ["记预定", "联系过了", "不用跟了", "改"], bt)
        ab = row(pg, "Amy").first; ab.locator("summary").click(); pg.wait_for_timeout(150)
        bt2 = ab.locator(".l-actions button").all_inner_texts()
        check("手动记的跟进也是这四个", bt2 == ["记预定", "联系过了", "不用跟了", "改"], bt2)

        # 联系过了：常用说法一点就填，3 天后再提醒
        c1.locator("[data-au-later]").click(); pg.wait_for_selector("#f-lwq")
        pg.click('#f-lwq [data-lw="发了信息没回"]'); pg.check('input[name="f-whenr"][value="3"]'); save(pg)
        cp = cust(pg, "Cat")
        check("Cat：下次 3 天后，记一笔「发了信息没回」", cp.get("next") == D(3) and (cp.get("touches") or [{}])[-1].get("what") == "发了信息没回", (cp.get("next"), cp.get("touches")))
        check("Cat 挪到「以后」（3 天后，还没到前两天）", fu_names(pg) == ["Kit", "Lou", "Ben", "Amy", "Dan"] and "Cat" in fold_names(pg), (fu_names(pg), fold_names(pg)))
        row(pg, "Amy").first.locator("summary").click(); pg.wait_for_timeout(150)
        row(pg, "Amy").first.locator("[data-fu-done]").click(); pg.wait_for_timeout(500)
        fa = next(x for x in S(pg, "followups") if x["id"] == "fu-a")
        check("Amy 不用跟了 → 这条关掉", fa.get("done") is True and fu_names(pg) == ["Kit", "Lou", "Ben", "Dan"], (fa.get("done"), fu_names(pg)))
        # 「以后」里的到了前两天自己出来：把 Eve 改成后天
        pg.evaluate("window.__GM.S.followups.find((f) => f.id === 'fu-e').date = '" + D(2) + "'"); go(pg, "inventory"); go(pg, "customers")
        check("「以后」里的 Eve 到了前两天，自己出来排在上面（后天那一档）", fu_names(pg)[:3] == ["Kit", "Eve", "Lou"] and "Eve" not in fold_names(pg), (fu_names(pg), fold_names(pg)))

        # 重点客户
        pg.click('[data-cs="vip"]'); pg.wait_for_timeout(250)
        vn = pg.evaluate("[...document.querySelectorAll('#c-list .cu-name .name')].map((x) => x.innerText)")
        check("「重点客户」：只有 Cat（Hal 是批发、Ben 每次 1 根都不算）", vn == ["Cat"], vn)
        check("写「一次最多 10 根」", "一次最多 10 根" in pg.inner_text("#c-list"))
        pg.click('#c-list [data-cu]'); pg.wait_for_timeout(200); pg.click('#c-list [data-cu-edit]'); pg.wait_for_selector("#f-cvip")
        check("客户资料：「重点客户」已勾（一次买过 10 根）", pg.is_checked("#f-cvip") and "一次买过 10 根" in pg.inner_text("#sheet-form"))
        pg.uncheck("#f-cvip"); save(pg)
        check("取消勾选 → 存 vip:false，不在重点客户里", cust(pg, "Cat").get("vip") is False and "还没有重点客户" in pg.inner_text("#c-list"), (cust(pg, "Cat").get("vip"), pg.inner_text("#c-list")[:80]))
        check("也不再按「重点」提醒", "Cat" not in fold_names(pg) + fu_names(pg), fold_names(pg))
        pg.click('[data-cs="recent"]'); pg.wait_for_timeout(200)

        # 地点
        check("客户页标题右边有「地点」", pg.is_visible("#hd-place"))
        pg.click("#hd-place"); pg.wait_for_timeout(250)
        check("还没有地点时写怎么用", "还没有地点" in pg.inner_text("#sheet-form") and not pg.is_visible("#sheet-save"))
        pg.click("#pl-new"); pg.wait_for_selector("#f-plname"); pg.fill("#f-plname", "Coles 停车场"); pg.fill("#f-pltext", "地址：1 Test St, Success\n停在 Coles 门口那排"); save(pg)
        pl = S(pg, "places")
        check("存进地点库", pl == [{"name": "Coles 停车场", "text": "地址：1 Test St, Success\n停在 Coles 门口那排"}], pl)
        pg.wait_for_selector("[data-pl-copy]")
        check("存完回到地点列表", pg.locator('[data-pl-copy="Coles 停车场"]').count() == 1)
        pg.click('[data-pl-copy="Coles 停车场"]'); pg.wait_for_timeout(300)
        clip = pg.evaluate("navigator.clipboard.readText()")
        check("点「复制」= 复制写好的那段话", clip == "地址：1 Test St, Success\n停在 Coles 门口那排", clip)
        close(pg)

        # 客户资料：一般在哪见面、几点方便联系
        pg.fill("#cq", "Ben"); pg.wait_for_timeout(250); pg.click('#c-list [data-cu]'); pg.wait_for_timeout(200); pg.click('#c-list [data-cu-edit]'); pg.wait_for_selector("#f-cpl")
        pg.check('input[name="f-cplr"][value="Coles 停车场"]'); pg.fill("#f-cfrom", "16:00"); pg.fill("#f-cto", "18:00"); save(pg)
        bp = cust(pg, "Ben")
        check("Ben 打上地点、联系时间", bp.get("place") == "Coles 停车场" and bp.get("call") == "16:00-18:00", bp)
        check("Ben 在客户列表上有地点标签、点开写「一般 下午 4–6 点 联系」", "Coles 停车场" in pg.inner_text("#c-list") and "下午 4–6 点" in pg.inner_text("#c-list"), pg.inner_text("#c-list")[:200])
        pg.fill("#cq", ""); pg.wait_for_timeout(200)
        br_ = row(pg, "Ben").first
        check("跟进列表里 Ben 也写着地点和「下午 4–6 点联系」", "Coles 停车场" in br_.inner_text() and "下午 4–6 点联系" in br_.inner_text(), br_.inner_text())

        # 记预定：写了 Ben 自动带上
        resv(pg, "Ben")
        got = (pg.evaluate("(document.querySelector('input[name=f-plr]:checked') || {}).value"), pg.input_value("#f-cfrom"), pg.input_value("#f-cto"))
        check("记预定写 Ben：地点、联系时间自动带上", got == ("Coles 停车场", "16:00", "18:00"), got)
        save(pg)
        ob = next(o for o in S(pg, "orders") if o.get("customer") == "Ben" and o.get("status") == "reserved")
        check("预定上存了地点、联系时间，没有几点", ob.get("place") == "Coles 停车场" and ob.get("call_win") == "16:00-18:00" and not ob.get("meet_time"), ob)
        go(pg, "customers")
        card = pg.locator("#resv details.rv").filter(has=pg.locator('b:text-is("Ben")')).first
        ct = card.inner_text()
        check("预定卡片：「今天 · 暂未确定时间」「下午 4–6 点联系」「Coles 停车场」", "今天 · 暂未确定时间" in ct and "下午 4–6 点联系" in ct and "Coles 停车场" in ct, ct)
        card.locator("summary").click(); pg.wait_for_timeout(150)
        pg.evaluate("navigator.clipboard.writeText('')")
        card.locator("[data-copy-place]").click(); pg.wait_for_timeout(300)
        check("预定点开「复制地点」= 复制那段话", pg.evaluate("navigator.clipboard.readText()") == "地址：1 Test St, Success\n停在 Coles 门口那排")

        # 新客人 + 新地点：进地点库、客人打上标签
        def newpl():
            pg.click("#f-pladd"); pg.fill("#f-plnew", "Murdoch 站"); pg.fill("#f-mtime", "15:30")
        resv(pg, "Ivy", newpl); save(pg)
        check("新地点进地点库（还没写地址）", [x["name"] for x in S(pg, "places")] == ["Coles 停车场", "Murdoch 站"], S(pg, "places"))
        check("新客人 Ivy 自动打上「Murdoch 站」", cust(pg, "Ivy").get("place") == "Murdoch 站", cust(pg, "Ivy"))
        go(pg, "customers")
        ci = pg.locator("#resv details.rv").filter(has=pg.locator('b:text-is("Ivy")')).first.inner_text()
        check("定了几点的卡片写「今天 15:30」，不写「暂未确定」", "今天 15:30" in ci and "暂未确定" not in ci, ci)

        # 改名字：客人标签、还没结算的预定跟着改；删地点
        pg.click("#hd-place"); pg.wait_for_selector("[data-pl-edit]")
        check("没写地址的写「还没写地址」", "还没写地址" in pg.inner_text("#sheet-form"))
        pg.click('[data-pl-edit="Coles 停车场"]'); pg.wait_for_selector("#f-plname"); pg.fill("#f-plname", "Coles"); save(pg)
        check("改名字：Ben 的标签、预定跟着改", cust(pg, "Ben").get("place") == "Coles" and order(pg, ob["id"]).get("place") == "Coles" and S(pg, "places")[0]["name"] == "Coles", (cust(pg, "Ben").get("place"), order(pg, ob["id"]).get("place")))
        pg.click('[data-pl-edit="Murdoch 站"]'); pg.wait_for_selector("#f-pldel"); pg.click("#f-pldel"); pg.click("#f-pldel"); pg.wait_for_timeout(500)
        check("删掉地点（两下）", [x["name"] for x in S(pg, "places")] == ["Coles"], S(pg, "places"))
        close(pg)
        go(pg, "inventory")
        check("库存页标题右边也有「地点」", pg.is_visible("#hd-place") and pg.is_visible("#inv-copy"))
        go(pg, "finance")
        check("财务页没有「地点」", not pg.is_visible("#hd-place"))
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

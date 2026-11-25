"""合伙人对账：抵掉的下次不再出现（2026-11-25 Bowen：同系列抵掉以后，下次对账单不用再出现，底下留一条抵掉了哪几个口味的记录；以后再加东西，抵过的不要再出现）
- 按日期先后一根一根抵（同系列，不管单价）：新加的货只跟还没抵掉的抵，以前抵掉的不变
- 对账单明细只列没抵掉的；按系列只写抵完还剩的（照各自的价）；最下面「抵掉的」：哪天、哪个系列、几根、两边各是哪几个口味
- 复制给合伙人的文字一样；结账单上全部抵掉的往来标「（已抵掉）」
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_offset_fifo.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
W = "合伙人甲"
D = lambda n: (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=n)).isoformat()
L = lambda sku, n, q, u: {"sku": sku, "name": n, "qty": q, "unit": u}
TR = lambda tid, n, hh, out, inn: (tid, {"date": D(n), "at": D(n) + "T%02d:00:00Z" % hh, "partner": W, "out": out, "in": inn, "note": ""})
V1 = {"items": {"BP-1": IT("BP-1", "Bar Pro", "Grape", "葡萄", 30), "BP-2": IT("BP-2", "Bar Pro", "Banana", "香蕉", 30), "BP-3": IT("BP-3", "Bar Pro", "Mango", "芒果", 30), "AL-1": IT("AL-1", "Ali", "Mint", "薄荷", 30)},
      "movements": {"in-%d" % k: {"type": "in", "sku": s_, "name": s_, "qty": 20, "date": D(9), "at": D(9) + "T00:30:00Z", "note": "进货", "cost": 600} for k, s_ in enumerate(["BP-1", "BP-2", "BP-3", "AL-1"])},
      # 3 天前：你拿他 Bar Pro 3 根（葡萄 2、香蕉 1）@36；前天：他拿你 Bar Pro 芒果 2 根 @34 → 抵掉 2 根，剩你拿他的香蕉 1 根
      "transfers": dict([TR("t-1", 3, 1, [], [L("BP-1", "Grape", 2, 36), L("BP-2", "Banana", 1, 36)]), TR("t-2", 2, 1, [L("BP-3", "Mango", 2, 34)], [])]),
      "orders": {}, "expenses": {}, "purchases": {}, "settlements": {}, "customers": {}, "followups": {}}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}
EXPOSE = "\nwindow.__GM = { S, ledgerSheet, statementText, partnerItems, openXfers, openPOs, pendingPicks };\n})();"
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

def T(pg, sel): return pg.evaluate(f"[...document.querySelectorAll('{sel}')].map((e) => e.innerText.replace(/\\s+/g, ' ').trim())")
def mx(pg): return pg.evaluate("[...document.querySelectorAll('#sheet .lg-sec')].filter((e) => e.querySelector('.lg-sh .lg-k.k-in, .lg-sh .lg-k.k-out')).map((e) => e.innerText.replace(/\\s+/g, ' '))")
def ledger(pg):
    if pg.is_visible("#sheet"): pg.click("#sheet-close"); pg.wait_for_timeout(250)
    pg.evaluate(f"window.__GM.ledgerSheet('{W}')"); pg.wait_for_timeout(350)
MD = lambda n: f"{int(D(n)[5:7])}月{int(D(n)[8:])}日"

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode, data in (("旧结构", V1), ("新结构", V2)):
        print("==", mode)
        col = "v2_transfers" if mode == "新结构" else "transfers"
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth")
        ctx.add_init_script("window.__SEED = " + json.dumps(data, ensure_ascii=False) + ";")
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        for x in ("**/firebase-auth-compat.js", "**/firebase-firestore-compat.js"): pg.route(x, lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL + "#partner"); pg.wait_for_timeout(1800)

        # 1. 抵掉的不在明细里，最下面有记录
        ledger(pg)
        check("前天抵掉 2 根：明细只剩你拿他的香蕉 ×1", mx(pg) == ["调入 从" + W + "拿的货 " + MD(3) + " Bar Pro Banana ×1"], mx(pg))
        off = T(pg, "#sheet .lg-off li")
        check("最下面「抵掉的」：" + MD(2) + " Bar Pro 抵掉 2 根（你拿他 Grape ×2 / 他拿你 Mango ×2）", off == [MD(2) + " · Bar Pro 抵掉 2 根", "你拿他：Grape ×2", "他拿你：Mango ×2"], off)
        check("按系列只剩：你欠他 Bar Pro 1 根 $36", T(pg, "#sheet .lg-sr") == ["Bar Pro 你欠他 1 根 $36"], T(pg, "#sheet .lg-sr"))

        # 2. 今天他又拿了 Ali 1 根（别的系列）：以前抵掉的还是不出现
        pg.evaluate(f"window.__remoteWrite('{col}', 't-3', {json.dumps(dict(TR('t-3', 0, 1, [L('AL-1', 'Mint', 1, 50)], [])[1]), ensure_ascii=False)})"); pg.wait_for_timeout(600)
        ledger(pg)
        m = mx(pg)
        check("加了别的东西：明细是 香蕉 ×1（你拿他）+ 薄荷 ×1（他拿你），葡萄、芒果不再出现", len(m) == 2 and "Banana ×1" in m[0] and "Ali Mint ×1" in m[1] and "Grape" not in " ".join(m) and "Mango" not in " ".join(m), m)
        check("抵掉的记录不变", T(pg, "#sheet .lg-off li") == off, T(pg, "#sheet .lg-off li"))

        # 3. 今天他再拿 Bar Pro 3 根 @35：先跟还没抵掉的香蕉 1 根抵，剩 2 根照它自己的价 $35
        pg.evaluate(f"window.__remoteWrite('{col}', 't-4', {json.dumps(dict(TR('t-4', 0, 2, [L('BP-3', 'Mango', 3, 35)], [])[1]), ensure_ascii=False)})"); pg.wait_for_timeout(600)
        ledger(pg)
        off2 = T(pg, "#sheet .lg-off li")
        check("新抵掉的加一条：今天 Bar Pro 抵掉 1 根（香蕉 ×1 / 芒果 ×1），前天那条不变", off2[:3] == off and off2[3:] == [MD(0) + " · Bar Pro 抵掉 1 根", "你拿他：Banana ×1", "他拿你：Mango ×1"], off2)
        m = mx(pg)
        check("明细只剩他拿你的：芒果 ×2、薄荷 ×1（你拿他的全抵掉了）", len(m) == 1 and "Bar Pro Mango ×2" in m[0] and "Ali Mint ×1" in m[0], m)
        sr = T(pg, "#sheet .lg-sr")
        check("剩下的照各自的价：Bar Pro 他欠你 2 根 $70（@35）、Ali 1 根 $50", sr == ["Bar Pro 他欠你 2 根 $70", "Ali 他欠你 1 根 $50"], sr)
        check("合计：" + W + " 欠你 $120", W + " 欠你 $120" in pg.inner_text("#sheet .lg-sum"), pg.inner_text("#sheet .lg-sum"))
        txt = pg.evaluate(f"window.__GM.statementText(window.__GM.partnerItems('{W}'), 'T', null, window.__GM.openXfers('{W}'), window.__GM.openPOs('{W}'), window.__GM.pendingPicks('{W}'))")
        check("复制给他的文字：明细只有没抵掉的，最后列已经抵掉的", "Grape" not in txt.split("【已经抵掉的")[0] and "【已经抵掉的 · 同系列一根抵一根，不算钱】" in txt and MD(2) + "  Bar Pro 抵掉 2 根\n  我拿你：Grape ×2\n  你拿我：Mango ×2" in txt, txt)

        # 4. 结账：全部抵掉的那两笔标「已抵掉」，结完对账单清空
        pg.click("#sheet-save"); pg.wait_for_selector("#f-net"); pg.wait_for_timeout(300)
        lab = T(pg, "#sheet .picks label")
        check("结账单上全部抵掉的往来标「（已抵掉）」：3 天前、前天那两笔", sum("（已抵掉）" in x for x in lab) == 2 and all("（已抵掉）" not in x for x in lab if "Mint" in x), lab)
        check("结账金额 = " + W + " 给你 $120", "给你 $120" in pg.inner_text("#f-net"), pg.inner_text("#f-net"))
        save(pg)
        st = pg.evaluate("window.__GM.S.transfers.map((t) => t.partner_settlement_id || '')")
        check("四笔往来都结了", len(st) == 4 and all(st), st)
        pg.evaluate(f"window.__GM.ledgerSheet('{W}')"); pg.wait_for_timeout(300)
        check("结完对账单没东西了", not pg.is_visible("#sheet") or "对账单" not in pg.inner_text("#sheet-title"))
        check("没有报错", not errs, errs)
        ctx.close()
    br.close()
srv.shutdown()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

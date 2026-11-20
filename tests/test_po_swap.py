"""订货单「换货」：没到的那部分换成别的口味 / 别的系列（2026-11-20 Bowen：订的货有些没到，供货人会换成别的系列或口味）
- 订货单还没到齐时有「换货」按钮；上面填换掉几根（只能换还没到的），下面填换成什么（任何口味，或只知道系列），每根成本默认 = 换掉那几根的平均
- 保存：订货单 lines 换掉的减掉（没到过的减到 0 拿掉，到过的留着）、加上换成的（已有同一口味 / 系列就合并）；total 重算；旧结构付款那笔支出跟着改；已到货的成本不动
- 订货单上写「11月20日 换货：A ×10 → B ×6、C ×4」；在途、登记到货跟着变
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_po_swap.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
IT2 = lambda sku, ser, v, n, c: (sku, IT(sku, ser, v, n, c))
V1 = {"items": dict([IT2("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30), IT2("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 30), IT2("XF-03", "Bar Pro", "Mango Ice", "芒果冰", 30), IT2("XF-04", "Ali", "Pink Lemon", "粉柠檬", 25)]),
      "movements": {"p-1-r1-XF-01": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 4, "date": TODAY, "at": TODAY + "T02:00:00Z", "po_id": "p-1", "po_line": "XF-01", "receipt_id": "r1", "cost": 120, "note": "订货到货"}},
      "purchases": {"p-1": {"date": TODAY, "at": TODAY + "T01:00:00Z", "note": "", "supplier": "合伙人甲", "paid": True, "paid_date": TODAY, "total": 725,
                            "lines": [{"sku": "XF-01", "name": "香蕉", "series": "Bar Pro", "qty": 10, "unit_cost": 30}, {"sku": "XF-02", "name": "葡萄冰", "series": "Bar Pro", "qty": 10, "unit_cost": 30},
                                      {"series": "Ali", "sku": None, "name": "Ali（口味到货再分）", "qty": 5, "unit_cost": 25}]}},
      "expenses": {"p-1-pay": {"date": TODAY, "at": TODAY + "T01:00:00Z", "amount": 725, "category": "进货成本", "note": "订货", "po_id": "p-1"}},
      "orders": {}, "settlements": {}, "transfers": {}, "customers": {}, "followups": {}}
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

def po(pg): return next(x for x in S(pg, "purchases") if x["id"] == "p-1")
def L(p): return {(l.get("sku") or "series:" + l["series"]): (l["qty"], l.get("unit_cost")) for l in p["lines"]}
def swap(pg): go(pg, "purchases"); pg.click('[data-swap-po="p-1"]'); pg.wait_for_selector("#f-swq")
def out_(pg, i, q): pg.locator(".sw-out").nth(i).fill(str(q))
def in_(pg, sel, q): pg.fill(f'#f-swin .sw-in[{sel}]', str(q))

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
        go(pg, "purchases")
        check("还没到齐的订货单有「换货」", pg.locator('[data-swap-po="p-1"]').count() == 1)
        swap(pg)
        rows = pg.evaluate("[...document.querySelectorAll('.sw-out')].map((x) => x.closest('.al-row').innerText.replace(/\\s+/g, ' ').trim())")
        check("换掉的只列还没到的：香蕉还没到 6、葡萄冰 10、Ali 系列 5", len(rows) == 3 and "还没到 6 根" in rows[0] and "还没到 10 根" in rows[1] and "还没到 5 根" in rows[2], rows)
        out_(pg, 0, 7); in_(pg, 'data-sku="XF-03"', 7); save(pg)
        check("换掉的比还没到的多：不让存", pg.is_visible("#sheet") and "还没到" in pg.inner_text("#sheet-err"), pg.inner_text("#sheet-err") if pg.is_visible("#sheet-err") else "")
        close(pg)

        # 葡萄冰 10 根 → 芒果冰 6 + Ali 粉柠檬 4（换了系列）
        swap(pg); out_(pg, 1, 10); in_(pg, 'data-sku="XF-03"', 6); pg.fill("#f-swq", "pink"); in_(pg, 'data-sku="XF-04"', 4); pg.wait_for_timeout(150)
        check("每根成本默认 = 换掉那几根的平均 $30；写「换掉 10 根 → 换成 10 根」", pg.input_value("#f-swcost") == "30" and "换掉 10 根 → 换成 10 根" in pg.inner_text("#f-swsum"), (pg.input_value("#f-swcost"), pg.inner_text("#f-swsum")))
        save(pg)
        P = po(pg)
        check("订货单：葡萄冰拿掉，芒果冰 6、粉柠檬 4（$30），香蕉、Ali 系列不动", L(P) == {"XF-01": (10, 30), "XF-03": (6, 30), "XF-04": (4, 30), "series:Ali": (5, 25)}, L(P))
        check("金额不变 $725；换货记录一笔", P.get("total") == 725 and len(P.get("swaps") or []) == 1 and P["swaps"][0]["out"][0]["qty"] == 10, (P.get("total"), P.get("swaps")))
        txt = pg.inner_text("#po-list")
        check("订货单上写「换货：Grape Ice ×10 → Pink Lemon ×4、Mango Ice ×6」", "换货：Grape Ice ×10 → Pink Lemon ×4、Mango Ice ×6" in txt.replace("\n", " "), [l for l in txt.splitlines() if "换货" in l])

        # 香蕉没到的 6 根里换 2 根成 Ali 系列（口味到货再分），每根 $25
        swap(pg)
        n_out = pg.locator(".sw-out").count()
        out_(pg, 0, 2); in_(pg, 'data-ser="Ali"', 2); pg.fill("#f-swcost", "25"); pg.wait_for_timeout(150)
        check("单价改了：写「订货单金额 少 $10」", "少 $10" in pg.inner_text("#f-swsum"), pg.inner_text("#f-swsum"))
        save(pg); P = po(pg)
        check("香蕉 10 → 8（到过 4 根的留着）；Ali 系列 5 + 2 = 7 根 $25；金额 $715", L(P) == {"XF-01": (8, 30), "XF-03": (6, 30), "XF-04": (4, 30), "series:Ali": (7, 25)} and P.get("total") == 715, (L(P), P.get("total")))
        mv = next(m for m in S(pg, "moves") if m.get("po_id") == "p-1")
        check("已经到货的 4 根香蕉成本不动（$120）", mv.get("cost") == 120, mv.get("cost"))
        if mode == "旧结构":
            ex = next(x for x in S(pg, "expenses") if x.get("po_id") == "p-1")
            check("付款那笔支出跟着改成 $715", ex.get("amount") == 715, ex.get("amount"))
        else:
            ex = [x for x in S(pg, "expenses") if x.get("po_id") == "p-1"]
            check("新结构：订货的支出现算 = $715", ex and ex[0].get("amount") == 715, ex)

        # 登记到货跟着变
        go(pg, "purchases"); pg.click('[data-rcv="p-1"]'); pg.wait_for_timeout(500)
        rc = pg.inner_text("#sheet-form")
        check("登记到货：有芒果冰 0/6、粉柠檬 0/4，没有葡萄冰", "0/6" in rc and "0/4" in rc and "Grape Ice" not in rc, rc[:300])
        close(pg)
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

"""体检用的场景工具：在 390px 手机尺寸下点 App 真界面，每做一步就把 App 里的记录倒出来，
① 用 recalc.py 独立重算，跟 App 自己算的逐项比；② 查守恒；③ 跟「现实里应该是多少」比（场景自己写明）。
旧结构、v2 各跑一遍。"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib, re
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import recalc as RC

REPO = pathlib.Path(os.environ.get("REPO", str(pathlib.Path(__file__).resolve().parents[2])))
PUB = REPO / "public"
MOCK = (REPO / "tests" / "mockfb.js").read_text(encoding="utf8")
GOLD = (REPO / "tests" / "golden.py").read_text(encoding="utf8")
EXPOSE = re.search(r'EXPOSE = """(.*?)"""', GOLD, re.S).group(1)
COLLECT = re.search(r'COLLECT = r"""(.*?)"""', GOLD, re.S).group(1)
TZ = datetime.timezone(datetime.timedelta(hours=8))
TODAY = datetime.datetime.now(TZ).date()
D = lambda n=0: (TODAY - datetime.timedelta(days=n)).isoformat()
A, B = "合伙人甲", "合伙人乙"


def item(sku, ser, en, cost=30, price=60):
    return sku, {"sku": sku, "series": ser, "variant": en, "name": en, "price_aud": price, "cost_aud": cost, "status": "在售"}


def base_seed(stock=None):
    """Bar Pro: XF-01 XF-02 XF-05（成本 30）；Ali: XF-03 XF-04（成本 50）。默认 XF-01 有 10 根、XF-03 有 4 根，其他没货"""
    stock = stock if stock is not None else {"XF-01": 10, "XF-03": 4}
    it = dict([item("XF-01", "Bar Pro", "Banana Buzz"), item("XF-02", "Bar Pro", "Grape Ice"), item("XF-05", "Bar Pro", "Peach Ice"),
               item("XF-03", "Ali", "Cool Mint", 50, 90), item("XF-04", "Ali", "Lemon Tea", 50, 90)])
    mv, ex = {}, {}
    d = D(5)
    for sku, q in stock.items():
        c = it[sku]["cost_aud"] * q
        mv[f"b-0-{sku}"] = {"type": "in", "sku": sku, "name": it[sku]["name"], "qty": q, "cost": c, "date": d, "at": d + "T01:00:00Z", "batch_id": "b-0", "expense_id": "b-0-cost", "note": "进货"}
    if mv: ex["b-0-cost"] = {"date": d, "at": d + "T01:00:00Z", "amount": sum(m["cost"] for m in mv.values()), "category": "进货成本", "note": "进货", "batch_id": "b-0"}
    # 以前找甲、乙各拿过一次货（已结账），这样「找谁拿」有两个名字可选
    od = D(4)
    orders, sett = {}, {}
    for k, w in enumerate((A, B)):
        oid = f"o-old-{k}"
        orders[oid] = {"status": "paid", "date": od, "at": od + f"T0{k+1}:00:00Z", "lines": [{"sku": "XF-02", "name": "Grape Ice", "qty": 1, "unit_price": 60}], "delivery_fee": 0, "note": "", "payment": "现金", "pick_from": w, "partner_settlement_id": f"s-old-{k}"}
        mv[oid + "-XF-02"] = {"type": "out", "sku": "XF-02", "name": "Grape Ice", "qty": 1, "date": od, "at": od + f"T0{k+1}:00:00Z", "order_id": oid}
        mv[oid + "-pick-XF-02"] = {"type": "in", "sku": "XF-02", "name": "Grape Ice", "qty": 1, "cost": 30, "date": od, "at": od + f"T0{k+1}:00:00Z", "order_id": oid, "batch_id": oid + "-pick", "expense_id": oid + "-pick-cost", "note": "按单向合伙人拿货"}
        ex[oid + "-pick-cost"] = {"date": od, "at": od + f"T0{k+1}:00:00Z", "amount": 30, "category": "进货成本", "note": "按单拿货 Grape Ice ×1", "batch_id": oid + "-pick"}
        sett[f"s-old-{k}"] = {"date": od, "at": od + f"T0{k+3}:00:00Z", "order_ids": [oid], "transfer_ids": [], "po_ids": [], "qty": {"Bar Pro": 1}, "amount": 30, "paid": 30, "partner": w, "payment": "现金", "note": ""}
    return {"items": it, "movements": mv, "expenses": ex, "orders": orders, "settlements": sett, "transfers": {}, "purchases": {}, "customers": {}, "followups": {}, "meta": {"backfill": {"done": True}}}


def to_v2(seed):
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "v1.json").write_text(json.dumps(seed, ensure_ascii=False), encoding="utf8")
    subprocess.run(["node", str(REPO / "tests" / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
    v2 = json.loads((tmp / "v2.json").read_text(encoding="utf8"))
    v2["meta"] = {"schema": {"version": 2, "migrated_at": D(1) + "T05:00:00.000Z"}, "backfill": {"done": True}}
    return v2


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();")
            b = (src[:i] + EXPOSE + src[i + 5:]).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        return super().do_GET()


_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=_srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{_srv.server_address[1]}/index.html"

STATE = """() => { const S = window.__GM.S, pick = (a) => Object.fromEntries(a.map((x) => [x.id, x]));
  return JSON.parse(JSON.stringify({ items: pick(S.items), movements: pick(S.moves), orders: pick(S.orders), expenses: pick(S.expenses), purchases: pick(S.purchases), transfers: pick(S.transfers), settlements: pick(S.settles), customers: pick(S.customers), followups: pick(S.followups) })); }"""


class App:
    def __init__(self, br, seed, mode, name=""):
        self.mode, self.name, self.fails, self.steps = mode, name, [], 0
        self.ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN", has_touch=True, is_mobile=True, device_scale_factor=2)
        self.ctx.add_init_script("window.__SEED=" + json.dumps(to_v2(seed) if mode == "v2" else seed, ensure_ascii=False) + ";")
        pg = self.pg = self.ctx.new_page(); self.errs = []; pg.set_default_timeout(6000)
        pg.on("pageerror", lambda e: self.errs.append(str(e) + " @ " + " < ".join(l.strip()[:60] for l in (e.stack or "").split("\n")[1:4])))
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.items.length > 0 && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
        assert bool(pg.evaluate("!!window.__fbV2store")) == (mode == "v2"), "结构模式不对"

    # ---- 检查
    def state(self): return self.pg.evaluate(STATE)
    def ev(self, js, *a): return self.pg.evaluate(js, *a)
    def net(self, w): return self.ev("(w) => window.__GM.ledgerNet(w)", w)   # > 0 = 应付他
    def stock(self, sku): return self.ev("(k) => window.__GM.derive().st[k] || 0", sku)
    def fin(self): return self.ev("() => window.__GM.finBook(() => true).T")

    def audit(self, label, truth=None):
        """truth = {'应付': {人: 钱}, '库存': {sku: 根}, '收入': x, '成本': x} 现实里应该是多少"""
        self.steps += 1
        self.pg.wait_for_timeout(250)
        st = self.state(); Dd = {c: [dict(v, id=k) for k, v in sorted(r.items())] for c, r in st.items()}
        R = RC.recalc(Dd); bad = []
        for name, good, info in RC.invariants(Dd, R):
            if not good: bad.append("守恒：" + name + " " + str(info)[:260])
        G = self.pg.evaluate(COLLECT)
        df = RC.compare(R, G)
        if df: bad.append("独立重算跟 App 不一致：" + str(df[:4]))
        if truth:
            for w, v in (truth.get("应付") or {}).items():
                got = self.net(w)
                if abs(got - v) > 0.005: bad.append(f"应付{w}：现实 {v:g}，App 写 {got:g}")
            for sku, v in (truth.get("库存") or {}).items():
                got = self.stock(sku)
                if got != v: bad.append(f"库存 {sku}：现实 {v:g}，App 写 {got:g}")
            T = G["T"]
            for k, key in (("收入", "rev"), ("成本", "cost"), ("净赚", "net")):
                if k in truth and abs(T[key] - truth[k]) > 0.005: bad.append(f"{k}：现实 {truth[k]:g}，App 写 {T[key]:g}")
        if self.errs: bad.append("页面报错：" + "; ".join(self.errs[:2])); self.errs = []
        tag = f"[{self.name}·{self.mode}] {label}"
        if bad:
            if any("脱单" in x for x in bad):
                for m in Dd["movements"]:
                    if str(m.get("batch_id") or "").endswith("-pick") and not m.get("order_id"):
                        oid = m["batch_id"][:-5]; o = next((o for o in Dd["orders"] if o["id"] == oid), None)
                        print("      [查] 流水", m["id"], "partner", m.get("partner"), "note", m.get("note"), "| 订单", o and {k: o.get(k) for k in ("status", "pick_from", "partner_settlement_id", "partner_settlements", "pick_split")}, "| 结账单里有它的", [(x["id"], x.get("partner")) for x in Dd["settlements"] if oid in (x.get("order_ids") or [])])
            self.fails.append((label, bad)); print("❌ " + tag)
            for b in bad: print("      " + b)
        else: print("✅ " + tag)
        return not bad

    # ---- 动作（都走界面）
    def go(self, h): self.pg.evaluate(f"location.hash = '#{h}'"); self.pg.wait_for_timeout(250)

    def save(self, twice=True):
        pg = self.pg
        pg.evaluate("() => document.querySelectorAll('.toast').forEach((t) => { t.hidden = true; })"); pg.wait_for_timeout(300)
        pg.click("#sheet-save")
        try: pg.wait_for_selector("#sheet", state="hidden", timeout=1500)
        except Exception:
            if twice and pg.is_visible("#sheet-save") and not pg.evaluate("!!document.querySelector('#sheet .err')"): pg.click("#sheet-save")
            try: pg.wait_for_selector("#sheet", state="hidden", timeout=4000)
            except Exception:
                msg = pg.evaluate("() => { const e = document.querySelector('#sheet .err, #sheet [role=alert]'); return (e ? e.textContent : '') + ' | ' + [...document.querySelectorAll('.toast')].map(t => t.textContent).join('/'); }")
                raise RuntimeError("弹窗没关：" + msg)
        pg.wait_for_timeout(450)

    def toast(self): return self.pg.evaluate("() => document.getElementById('toast').textContent")

    def ids(self, k="orders"): return set(self.ev(f"window.__GM.S.{k}.map((x) => x.id)"))

    def _lines(self, lines):
        pg = self.pg
        for k, (name, qty) in enumerate(lines):
            if k: pg.click("#f-addline")
            pg.fill(f"#f-skuq-{k}", name); pg.press(f"#f-skuq-{k}", "Enter")
            if qty != 1: pg.fill(f"#f-qty-{k}", str(qty))

    def sale(self, lines, who=None, resv=False, cust=None, split=None, pay="现金"):
        """lines = [(口味英文名, 根数)]；返回新订单号"""
        pg = self.pg; before = self.ids()
        self.go("finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
        self._lines(lines)
        if resv: pg.check("#f-resv")
        else: pg.check(f'input[name="f-payr"][value="{pay}"]')
        if cust: pg.fill("#f-cust", cust)
        if who is not None and pg.is_visible("#f-pfrom"): pg.fill("#f-pfrom", who); pg.dispatch_event("#f-pfrom", "change")
        if split: split(pg)
        if pg.is_visible("#f-lumpon") and pg.is_checked("#f-lumpon"): pg.uncheck("#f-lumpon")
        self.save()
        new = sorted(self.ids() - before)
        return new[0] if new else None

    def void(self, oid, page="finance"):
        self.go(page); self.pg.wait_for_timeout(200)
        self.pg.evaluate("() => document.querySelectorAll('details').forEach((d) => d.open = true)"); self.pg.wait_for_timeout(200)
        n = self.pg.evaluate(f"""() => {{ const b = [...document.querySelectorAll('[data-void-order="{oid}"]')][0]; if (!b) return 0; b.click(); b.click(); return 1; }}""")
        if not n: raise RuntimeError("找不到撤销按钮 " + oid)
        self.pg.wait_for_timeout(700)

    def open_ledger(self, w):
        self.go("finance"); self.pg.click(f'#f-owe [data-lg-open="{w}"]'); self.pg.wait_for_selector("#sheet .lg-sum", timeout=4000)

    def picked(self, w, oid):
        """对账单「预定」里点「已拿到」"""
        self.open_ledger(w)
        self.pg.evaluate(f"""() => {{ const b = document.querySelector('#sheet [data-lg="picked"][data-id="{oid}"]'); b.click(); b.click(); }}""")
        self.pg.wait_for_timeout(900); self.close_sheet()

    def close_sheet(self):
        if self.pg.is_visible("#sheet"): self.pg.click("#sheet-close"); self.pg.wait_for_timeout(300)

    def settle_partner(self, w, only=None, paid=None):
        """合伙人页「结账」。only(pg) 可以改勾选"""
        pg = self.pg; self.go("partner"); pg.click(f'#ptx-bal [data-ptx-settle="{w}"]'); pg.wait_for_selector("#f-net", timeout=4000)
        if only: only(pg); pg.wait_for_timeout(200)
        txt = pg.inner_text("#f-net")
        if paid is not None: pg.fill("#f-paid", str(paid))
        before = self.ids("settles"); self.save()
        new = sorted(self.ids("settles") - before)
        return (new[0] if new else None), txt

    def unsettle(self, sid):
        self.go("partner"); self.pg.wait_for_timeout(200)
        n = self.pg.evaluate(f"""() => {{ const b = document.querySelector('[data-unsettle="{sid}"]'); if (!b) return 0; b.click(); b.click(); return 1; }}""")
        if not n: raise RuntimeError("找不到撤销结账按钮 " + sid)
        self.pg.wait_for_timeout(700)

    def edit_resv(self, oid, fn):
        self.go("customers"); self.pg.evaluate(f"""() => document.querySelector('[data-edit-order="{oid}"]').click()"""); self.pg.wait_for_selector("#f-skuq-0")
        fn(self.pg); self.save()

    def settle_resv(self, oid, pay="现金"):
        pg = self.pg; self.go("customers")
        pg.evaluate(f"""() => document.querySelector('[data-settle="{oid}"]').click()"""); pg.wait_for_timeout(400)
        if pg.is_visible("#sheet"):
            if pg.is_visible("#f-pay"): pg.select_option("#f-pay", pay)
            elif pg.locator(f"#sheet input[value='{pay}']").count(): pg.locator(f"#sheet input[value='{pay}']").first.check()
            self.save()
        else:
            pg.evaluate(f"""() => {{ const b = document.querySelector('[data-settle="{oid}"]'); if (b) b.click(); }}"""); pg.wait_for_timeout(700)

    def xfer(self, kind, who, out=(), inn=(), paid_now=None):
        """记往来。kind = take（他拿走）/ give（他给我）/ swap；行 = (口味, 根数, 单价)"""
        pg = self.pg; before = self.ids("transfers")
        self.go("partner"); pg.evaluate("document.getElementById('ptx-xfer').click()"); pg.wait_for_selector("#f-xwho")
        pg.fill("#f-xwho", who); pg.check(f'input[name="f-xk"][value="{kind}"]', force=True); pg.wait_for_timeout(150)
        n = [2]
        def side(lines, first, addbtn):
            for j, (name, qty, unit) in enumerate(lines):
                if j == 0: k = first
                else: pg.click(addbtn); k = n[0]; n[0] += 1
                pg.fill(f"#f-skuq-{k}", name); pg.press(f"#f-skuq-{k}", "Enter"); pg.fill(f"#f-qty-{k}", str(qty)); pg.fill(f"#f-unit-{k}", str(unit))
        side(out, 0, "#f-add-o"); side(inn, 1, "#f-add-i")
        if paid_now: pg.check("#f-xpaid"); pg.select_option("#f-pay", paid_now)
        txt = pg.inner_text("#f-xsum"); self.save()
        new = sorted(self.ids("transfers") - before)
        return (new[0] if new else None), txt

    def void_xfer(self, tid):
        self.go("partner"); self.pg.wait_for_timeout(200)
        n = self.pg.evaluate(f"""() => {{ const b = [...document.querySelectorAll('[data-void-xfer="{tid}"]')].find((x) => x.offsetParent) || document.querySelector('[data-void-xfer="{tid}"]'); if (!b) return 0; b.click(); b.click(); return 1; }}""")
        if not n: raise RuntimeError("找不到撤销往来按钮 " + tid)
        self.pg.wait_for_timeout(700)

    def xprice(self, w, fn):
        """对账单「改单价」"""
        self.open_ledger(w); self.pg.click('#sheet [data-lg="xprice"]'); self.pg.wait_for_selector("#f-xu-0")
        fn(self.pg); txt = self.pg.inner_text("#f-xsum"); self.save(); self.close_sheet(); return txt

    def po_new(self, supplier, series=None, flav=(), paid=False):
        pg = self.pg; before = self.ids("purchases")
        self.go("purchases"); pg.click("#po-new"); pg.wait_for_selector("#f-supplier")
        pg.fill("#f-supplier", supplier)
        sers = self.ev("() => [...document.querySelectorAll('#sheet fieldset.pser legend')].map((l) => l.textContent.replace('（口味到货再分）', ''))")
        for sr, (q, c) in (series or {}).items():
            k = sers.index(sr); pg.fill(f"#f-sq-{k}", str(q)); pg.fill(f"#f-sc-{k}", str(c))
        if flav:
            pg.evaluate("() => { document.querySelector('#sheet details.fold').open = true; }")
            for k, (name, q, c) in enumerate(flav):
                pg.click("#f-addline"); pg.fill(f"#f-skuq-{k}", name); pg.press(f"#f-skuq-{k}", "Enter"); pg.fill(f"#f-qty-{k}", str(q)); pg.fill(f"#f-ucost-{k}", str(c))
        pg.click(f'#f-paidseg [data-paid="{1 if paid else 0}"]')
        self.save()
        return sorted(self.ids("purchases") - before)[0]

    def po_receive(self, pid, flav=None, alloc=None):
        pg = self.pg; self.go("purchases"); pg.evaluate("() => { const f = document.getElementById('po-filter'); if (f) { const b = f.querySelector('[data-f=\"all\"]'); if (b) b.click(); } }")
        pg.evaluate(f"""() => document.querySelector('[data-rcv="{pid}"]').click()"""); pg.wait_for_selector("#f-units")
        for k, q in enumerate(flav or []): pg.fill(f"#f-rq-{k}", str(q))
        for sku, q in (alloc or {}).items(): pg.fill(f'#sheet .al-q[data-sku="{sku}"]', str(q))
        self.save()

    def shot(self, name):
        p = pathlib.Path(__file__).resolve().parent / "shots"; p.mkdir(exist_ok=True)
        self.pg.screenshot(path=str(p / (name + ".png")))

    def close(self): self.ctx.close()


def run(scenarios, modes=("旧", "v2")):
    """scenarios = [(名字, seed 函数, 场景函数(app))]"""
    fails = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        for name, mk, fn in scenarios:
            for mode in modes:
                app = App(br, mk(), mode, name)
                try: fn(app)
                except Exception as e:
                    print(f"💥 [{name}·{mode}] 场景没跑完：{str(e)[:300]}"); app.fails.append(("场景没跑完", [str(e)[:300]]))
                    try: app.shot(f"fail-{name}-{mode}")
                    except Exception: pass
                fails += [(name, mode, l, b) for l, b in app.fails]
                app.close()
        br.close()
    print(f"\n{'全部通过' if not fails else '有问题 %d 处' % len(fails)}")
    return fails

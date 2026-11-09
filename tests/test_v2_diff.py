"""差分测试：同一份数据、同一串操作，旧版（v1）做一遍、新版（v2，只存源头）做一遍，
每一步之后比较 App 看到的全部记录（订单、流水、支出、订货、往来、结账），必须逐条一样；
并检查 v2 存下来的只有源头（没有出库/拿货/往来流水、没有进货成本支出这些复制品）。
用法：python3 tests/test_v2_diff.py <旧 fixture.json> <v2 种子.json>（真实数据放仓库外面；v2 种子用 tests/v2_seed.js 生成）
时间固定、随机数固定，所以两边生成的编号一样。合伙人名字从数据里读，不写进代码。"""
import os, datetime, functools, http.server, json, re, sys, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
FIX1, FIX2 = (json.loads(pathlib.Path(a).read_text(encoding="utf8")) for a in sys.argv[1:3])
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive, partnerNames };\n})();"
SEEDRAND = "(() => { let s = 20261110; Math.random = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; }; })();"


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();")
            body = (src[:i] + EXPOSE + src[i + 5:]).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        return super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
STATE = """() => { const S = window.__GM.S, o = {};
  for (const k of ["orders", "moves", "expenses", "purchases", "transfers", "settles"]) o[k] = Object.fromEntries(S[k].map((x) => { const y = Object.assign({}, x); delete y._v; delete y.by_at; return [x.id, y]; }));
  return o; }"""
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))


def open_page(b, seed, t):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
    pg = ctx.new_page()
    pg.clock.set_fixed_time(t)
    pg.on("pageerror", lambda e: print("   页面报错：", e))
    pg.add_init_script(SEEDRAND + "window.__SEED=" + json.dumps(seed, ensure_ascii=False) + ";")
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(URL)
    pg.wait_for_function("window.__GM && window.__GM.S.orders.length > 50 && window.__GM.S.moves.length > 50", timeout=20000)
    pg.wait_for_timeout(800)
    return pg


def compare(step, a, b):
    A, B = a.evaluate(STATE), b.evaluate(STATE)
    bad = []
    for k in A:
        for i in sorted(set(A[k]) | set(B[k])):
            x, y = A[k].get(i), B[k].get(i)
            if x != y:
                if not x or not y: bad.append(f"{k}/{i} {'旧版有新版没有' if x else '新版多出来'}")
                else: bad.append(f"{k}/{i} " + "; ".join(f"{f}: {json.dumps(x.get(f), ensure_ascii=False)[:50]} → {json.dumps(y.get(f), ensure_ascii=False)[:50]}" for f in sorted(set(x) | set(y)) if x.get(f) != y.get(f)))
    check(step + "：旧版和新版看到的记录逐条一样", not bad, f"{len(bad)} 处：" + " | ".join(bad[:3]) if bad else "")
    # 新版存下来的只有源头
    v2m = b.evaluate("Object.keys(__server('v2_movements'))"); v2e = b.evaluate("Object.keys(__server('v2_expenses'))")
    dup_m = [i for i in v2m if re.match(r"^(o-.*|p-.*|t-.*|swap-.*)$", i) and not b.evaluate(f"!!__server('v2_movements')['{i}']._deleted")]
    # 复制品的编号：拿货支出 …-pick-cost、订货付款 …-pay、早期整批进货 b-…-cost（手动记的支出是独立的事，可以是任何分类）
    dup_e = [i for i in v2e if re.search(r"(-pick-cost|-pay)$|^b-.*-cost$", i) and not b.evaluate(f"!!__server('v2_expenses')['{i}']._deleted")]
    check(step + "：新版没有存复制品", not dup_m and not dup_e, f"流水 {dup_m[:3]} 支出 {dup_e[:3]}" if dup_m or dup_e else "")
    return A


def both(a, b, fn):
    fn(a); fn(b)
    a.wait_for_timeout(400); b.wait_for_timeout(400)


def stock_sku(pg, want_zero):
    return pg.evaluate("""(z) => { const st = window.__GM.derive().st; const it = window.__GM.S.items.filter((i) => i.status === "在售" && i.variant && !i.generic);
      const x = it.find((i) => z ? !(st[i.sku] > 0) : st[i.sku] >= 2); return x ? x.variant : null; }""", want_zero)


def save(pg):
    # 时钟固定住了，提示条不会自己消失；提示条可能压在保存按钮上 → 测试里先去掉
    pg.evaluate("() => document.querySelectorAll('.toast').forEach((t) => t.remove())")
    pg.wait_for_timeout(300)  # 「回头客」提示打字时就出来（feat：不再等失焦，第一下保存不会点空）
    pg.click("#sheet-save")
    try:
        try: pg.wait_for_selector("#sheet", state="hidden", timeout=1500)
        except Exception:  # App 的二次确认（比如重复下单提醒）：再按一次
            if pg.is_visible("#sheet-save") and not pg.evaluate("!!document.querySelector('#sheet .err')"): pg.click("#sheet-save")
            pg.wait_for_selector("#sheet", state="hidden", timeout=4000)
    except Exception:
        print("   弹窗没关：", pg.evaluate("() => { const e = document.querySelector('#sheet .err, #sheet [role=alert]'); return (e ? e.textContent : '') + ' | 提示: ' + [...document.querySelectorAll('.toast')].map(t => t.textContent).join('/') + ' | 不合格: ' + [...document.querySelectorAll('#sheet-form :invalid')].map(x => x.id + ':' + x.validationMessage).join(',') + ' | 按钮: ' + document.querySelector('#sheet-save').disabled + '/' + document.querySelector('#sheet-save').textContent + ' | ' + document.querySelector('#sheet-title').textContent + ' | 字段: ' + [...document.querySelectorAll('#sheet input, #sheet select')].filter(x => x.offsetParent).map(x => x.id + '=' + x.value).join(', '); }"))
        raise


def new_ids(before, pg, k="orders"):
    return sorted(set(pg.evaluate(f"window.__GM.S.{k}.map((x) => x.id)")) - set(before))


T0 = datetime.datetime(2026, 11, 10, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    A, B = open_page(br, FIX1, T0), open_page(br, FIX2, T0)
    compare("打开（迁移后）", A, B)
    partner = A.evaluate("window.__GM.partnerNames()[0]")
    have, none = stock_sku(A, False), stock_sku(A, True)
    print(f"   用的口味：有货 {have!r}，缺货 {none!r}")

    # 1 卖出（有货）
    ids0 = A.evaluate("window.__GM.S.orders.map((x) => x.id)")
    def sale_stock(pg):
        pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(200); pg.click("#fin-sale")
        pg.fill("#f-skuq-0", have); pg.press("#f-skuq-0", "Enter"); pg.select_option("#f-pay", "现金"); save(pg)
    both(A, B, sale_stock); compare("1 卖出（有货）", A, B)
    o_sold = new_ids(ids0, A); print("   新订单", o_sold)

    # 2 卖出（缺货，找合伙人拿）
    ids0 = A.evaluate("window.__GM.S.orders.map((x) => x.id)")
    def sale_pick(pg):
        pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(200); pg.click("#fin-sale"); pg.fill("#f-skuq-0", none); pg.press("#f-skuq-0", "Enter"); pg.select_option("#f-pay", "现金")
        if pg.is_visible("#f-pfrom"): pg.fill("#f-pfrom", partner)
        save(pg)
    both(A, B, sale_pick); compare("2 卖出（缺货，找合伙人拿）", A, B)

    # 3 预定（缺货）
    ids0 = A.evaluate("window.__GM.S.orders.map((x) => x.id)")
    def reserve(pg):
        pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(200); pg.click("#fin-sale"); pg.fill("#f-skuq-0", none); pg.press("#f-skuq-0", "Enter"); pg.check("#f-resv")
        if pg.is_visible("#f-pfrom"): pg.fill("#f-pfrom", partner)
        pg.fill("#f-cust", "测试客人")
        if pg.is_visible("#f-lumpon") and pg.is_checked("#f-lumpon"): pg.uncheck("#f-lumpon")  # 回头客会自动勾「整单总价」
        save(pg)
    both(A, B, reserve); compare("3 预定（缺货）", A, B)
    r1 = new_ids(ids0, A)[0]

    # 4 编辑预定：换口味 + 加一行
    def edit_resv(pg):
        pg.evaluate("location.hash = '#customers'"); pg.wait_for_timeout(200)
        pg.evaluate(f"""() => document.querySelector('[data-edit-order="{r1}"]').click()""")
        pg.fill("#f-skuq-0", have); pg.press("#f-skuq-0", "Enter"); pg.click("#f-addline"); pg.fill("#f-skuq-1", none); pg.press("#f-skuq-1", "Enter")
        if pg.is_visible("#f-pfrom"): pg.fill("#f-pfrom", partner)
        save(pg)
    both(A, B, edit_resv); compare("4 编辑预定（换口味、加一行）", A, B)

    # 5 结算预定
    def settle_resv(pg):
        pg.evaluate(f"""() => document.querySelector('[data-settle="{r1}"]').click()"""); pg.wait_for_selector("#sheet")
        if pg.is_visible("#f-pay"): pg.select_option("#f-pay", "现金")
        elif pg.locator("#sheet input[value='现金']").count(): pg.locator("#sheet input[value='现金']").first.check()
        save(pg)
    both(A, B, settle_resv); compare("5 结算预定", A, B)

    # 6 再预定一单，然后取消预定
    ids0 = A.evaluate("window.__GM.S.orders.map((x) => x.id)")
    both(A, B, reserve); r2 = new_ids(ids0, A)[0]
    def void(pg, oid):
        pg.evaluate(f"""() => {{ const b = [...document.querySelectorAll('[data-void-order="{oid}"]')][0]; b.click(); b.click(); }}""")
    both(A, B, lambda pg: (pg.evaluate("location.hash = '#customers'"), pg.wait_for_timeout(200), void(pg, r2)))
    compare("6 取消预定", A, B)

    # 7 撤销刚才那笔卖出
    both(A, B, lambda pg: (pg.evaluate("location.hash = '#finance'"), pg.wait_for_timeout(300), pg.evaluate("() => document.querySelectorAll('details').forEach((d) => d.open = true)"), pg.wait_for_timeout(200), void(pg, o_sold[0])))
    compare("7 撤销一笔卖出", A, B)

    # 8 记一笔支出
    def expense(pg):
        pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(200); pg.click("#fin-exp"); pg.fill("#f-amt", "12.5"); pg.fill("#f-note", "油费"); save(pg)
    both(A, B, expense); compare("8 记一笔支出", A, B)
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

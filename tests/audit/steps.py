"""数 5 个常用动作要点几下、填几个框、滑几屏（390×844，真实数据，v2）。用法：python3 steps.py <旧 fixture.json>"""
import sys, json
from harness import *
FX = json.load(open(sys.argv[1], encoding="utf8")); FX["meta"] = {"backfill": {"done": True}}

class Counter:
    def __init__(s, a): s.a, s.pg, s.taps, s.fills, s.scrolls, s.log = a, a.pg, 0, 0, 0, []
    def _see(s, sel):
        loc = s.pg.locator(sel).first; loc.wait_for(state="attached", timeout=5000)
        box = loc.bounding_box(); vh = 844
        nav = s.pg.evaluate("() => { const n = document.querySelector('nav.tabbar, .tabbar, #tabbar, nav'); const c = document.getElementById('cartbar'); return (n ? n.getBoundingClientRect().height : 0) + (c && !c.hidden ? c.getBoundingClientRect().height : 0); }")
        if not box or box["y"] < 0 or box["y"] + box["height"] > vh - (0 if s.pg.is_visible("#sheet") else nav):
            s.scrolls += 1; loc.scroll_into_view_if_needed(); s.pg.wait_for_timeout(150)
        return loc
    def tap(s, sel, what): s._see(sel).click(); s.taps += 1; s.log.append("点 " + what); s.pg.wait_for_timeout(350)
    def fill(s, sel, v, what): l = s._see(sel); l.click(); l.fill(v); s.taps += 1; s.fills += 1; s.log.append("填 " + what); s.pg.wait_for_timeout(200)
    def done(s, name):
        print(f"{name}：点 {s.taps} 下，其中填 {s.fills} 个框，要滑 {s.scrolls} 次\n     " + " → ".join(s.log)); r = (name, s.taps, s.fills, s.scrolls); s.taps = s.fills = s.scrolls = 0; s.log = []; return r

def scen(a):
    pg = a.pg; c = Counter(a); res = []
    have = a.ev("() => { const G = window.__GM, st = G.derive().st; return G.S.items.filter((i) => !i.generic && st[i.sku] > 1).map((i) => i.sku)[0]; }")
    none = a.ev("() => document.querySelector('#qo-tiles .tile.out [data-add]') ? document.querySelector('#qo-tiles .tile.out [data-add]').dataset.add : null")
    a.go("inventory"); pg.wait_for_timeout(400); a.shot("c0-inventory")
    # 1 卖一单（有货）
    c.tap(f'#qo-tiles [data-add="{have}"]', "口味格子"); c.tap("#cb-go", "下单"); pg.wait_for_selector("#sheet-save"); a.shot("c1-sale-form")
    info = pg.evaluate("() => ({ pay: document.getElementById('f-pay') ? document.getElementById('f-pay').value : null, h: document.getElementById('sheet-form').scrollHeight, focus: document.activeElement && document.activeElement.id, req: [...document.querySelectorAll('#sheet-form :required')].map((x) => x.id) })")
    print("   下单表：", info)
    if not info["pay"]: c.tap("#f-pay", "付款方式"); pg.select_option("#f-pay", "现金"); c.taps += 1; c.log.append("选 现金")
    c.tap("#sheet-save", "保存"); pg.wait_for_timeout(900)
    if pg.is_visible("#sheet-save"): print("   还要再点一次：", pg.inner_text("#sheet-err") if pg.is_visible("#sheet-err") else pg.inner_text("#sheet-save")); c.tap("#sheet-save", "再保存")
    res.append(c.done("① 卖一单（有货）"))
    # 2 卖一单（缺货找合伙人拿）
    a.go("inventory"); pg.wait_for_timeout(300)
    c.tap(f'#qo-tiles [data-add="{none}"]', "没货的口味格子"); c.tap("#cb-go", "下单"); pg.wait_for_selector("#sheet-save"); a.shot("c2-pick-form")
    print("   找谁拿：", pg.evaluate("() => document.getElementById('f-pfrom') && !document.getElementById('f-pfrom-wrap').hidden ? document.getElementById('f-pfrom').value : '(没显示)'"))
    if not pg.evaluate("document.getElementById('f-pay').value"): c.tap("#f-pay", "付款方式"); pg.select_option("#f-pay", "现金"); c.taps += 1; c.log.append("选 现金")
    c.tap("#sheet-save", "保存"); pg.wait_for_timeout(900)
    if pg.is_visible("#sheet-save"): c.tap("#sheet-save", "再保存")
    res.append(c.done("② 卖一单（缺货找合伙人拿）"))
    # 3 记预定，再结算
    a.go("inventory"); pg.wait_for_timeout(300); before = a.ids()
    c.tap(f'#qo-tiles [data-add="{have}"]', "口味格子"); c.tap("#cb-resv", "预定"); pg.wait_for_selector("#sheet-save"); a.shot("c3-resv-form")
    c.tap("#sheet-save", "保存"); pg.wait_for_timeout(900)
    if pg.is_visible("#sheet-save"): print("   预定保存被拦：", pg.inner_text("#sheet-err") if pg.is_visible("#sheet-err") else ""); c.fill("#f-cust", "客人", "客户名"); c.tap("#sheet-save", "保存"); pg.wait_for_timeout(900)
    oid = sorted(a.ids() - before)[0]
    c.tap('nav [data-view="customers"], [href="#customers"]', "底部「客户」"); pg.wait_for_timeout(300); a.shot("c3-customers")
    opener = pg.evaluate(f"""() => {{ const b = document.querySelector('[data-settle="{oid}"]'); const d = b.closest('details'); if (d && !d.open) {{ d.querySelector('summary').setAttribute('data-op', '1'); return 'summary'; }} return b.offsetParent ? '' : 'hidden:' + (b.closest('[hidden]') ? b.closest('[hidden]').id || b.closest('[hidden]').className : '?'); }}""")
    print("   预定卡片：", opener or "按钮直接可见")
    if opener == "summary": c.tap('summary[data-op="1"]', "点开预定卡片")
    c.tap(f'[data-settle="{oid}"]', "结算"); pg.wait_for_timeout(500)
    if pg.is_visible("#sheet"):
        a.shot("c3-settle-form")
        if pg.locator("#sheet input[name='f-payr'][value='现金']").count(): c.tap("#sheet input[name='f-payr'][value='现金']", "现金")
        elif pg.is_visible("#f-pay"): c.tap("#f-pay", "付款方式"); pg.select_option("#f-pay", "现金"); c.taps += 1; c.log.append("选 现金")
        c.tap("#sheet-save", "结算"); pg.wait_for_timeout(900)
    else: c.tap(f'[data-settle="{oid}"]', "再点一次确认"); pg.wait_for_timeout(900)
    res.append(c.done("③ 记预定 + 结算"))
    # 4 记往来（合伙人拿走我的货）
    c.tap('nav [data-view="partner"], [href="#partner"]', "底部「合伙人」"); pg.wait_for_timeout(400); a.shot("c4-partner")
    # 4 记往来：合伙人拿走我 1 根
    info = pg.evaluate("() => ({ open: !!(document.querySelector('#ptx-tiles') && document.querySelector('#ptx-tiles').offsetParent), ids: [...document.querySelectorAll('#view-partner [id], section[data-view=partner] [id]')].map((x) => x.id).slice(0, 40) })")
    print("   合伙人页：", info)
    return res, c

def scen_wrap(a):
    r = scen(a); a.result = r
run([("步数", lambda: FX, scen_wrap)], modes=("v2",))

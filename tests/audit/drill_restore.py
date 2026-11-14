"""备份恢复演练：云端清空 → 用中转站的整份数据 JSON 导入（import.html）→ 打开 App → 跟原来的账逐项比。
用法：python3 drill_restore.py <中转站 最新数据.json> <原数据算出的 golden.json>"""
import os, sys, json, functools, http.server, threading, pathlib, re
from playwright.sync_api import sync_playwright
REPO = pathlib.Path(__file__).resolve().parents[2]; PUB = REPO / "public"
MOCK = (REPO / "tests" / "mockfb.js").read_text(encoding="utf8")
GOLD = (REPO / "tests" / "golden.py").read_text(encoding="utf8")
EXPOSE = re.search(r'EXPOSE = """(.*?)"""', GOLD, re.S).group(1); COLLECT = re.search(r'COLLECT = r"""(.*?)"""', GOLD, re.S).group(1)
relay = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf8")); gold = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf8"))

class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();"); b = (src[:i] + EXPOSE + src[i + 5:]).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        return super().do_GET()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB))); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

def page(ctx):
    pg = ctx.new_page(); pg.set_default_timeout(15000)
    pg.on("pageerror", lambda e: print("   页面报错：", str(e)[:200]))
    for pat in ("**/firebase-app-compat.js",): pg.route(pat, lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    for pat in ("**/firebase-auth-compat.js", "**/firebase-firestore-compat.js"): pg.route(pat, lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url and "firebase-" not in r.request.url else r.fallback())
    return pg

def drill(name, bundle, tmp):
    print("== " + name)
    f = tmp / "bundle.json"; f.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf8")
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__MOCK_PERSIST = 1; window.__SEED = window.__SEED || {};")
        pg = page(ctx)
        pg.on("dialog", lambda d: d.accept())
        pg.goto(BASE + "/import.html"); pg.wait_for_timeout(800)
        pg.set_input_files("#f", str(f)); pg.wait_for_function("!document.getElementById('go').disabled", timeout=8000)
        pg.click("#go"); pg.wait_for_function("/✓|✗/.test(document.getElementById('out').textContent)", timeout=60000)
        out = pg.inner_text("#out"); print("   导入页最后说：", out.strip().split("\n")[-1][:120])
        bad = [l for l in out.split("\n") if "不一致" in l or "缺" in l]
        if bad: print("   导入页报对不上的：", " | ".join(x[:70] for x in bad[:4]))
        cols = pg.evaluate("() => Object.fromEntries(Object.entries(window.__store).map(([c, m]) => [c, m.size]))")
        print("   云端现在有的集合：", cols)
        pg.goto(BASE + "/index.html")
        try:
            pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(2500)
            n = pg.evaluate("() => ({ orders: window.__GM.S.orders.length, moves: window.__GM.S.moves.length, v2: !!window.__fbV2store })")
            print("   打开 App：", n)
            if n["orders"]:
                G = pg.evaluate(COLLECT)
                same = all(json.dumps(G[k], sort_keys=True) == json.dumps(gold[k], sort_keys=True) for k in ("st", "T", "days", "partners", "settled"))
                print("   " + ("✅ 恢复后的账跟原来逐项一样（库存/每天/合伙人/结账）" if same else "❌ 恢复后的账跟原来不一样"))
            else: print("   ❌ App 里是空的")
        except Exception as e: print("   ❌ App 没打开：", str(e)[:150])
        br.close()

import tempfile
tmp = pathlib.Path(tempfile.mkdtemp())
# 1. 直接把中转站文件原样喂给导入页（用户最可能的做法）
drill("中转站文件原样导入", relay, tmp)
# 2. 只取里面的 data
drill("只取 data 那一层导入", relay["data"], tmp)
# 3. 取 data，去掉 meta/schema（让 App 回到旧结构读）
d3 = json.loads(json.dumps(relay["data"])); d3.get("meta", {}).pop("schema", None)
drill("取 data + 去掉数据结构版本标记", d3, tmp)

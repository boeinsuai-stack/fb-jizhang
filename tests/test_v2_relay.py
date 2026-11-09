"""中转站差分测试：同一份数据、同一份「Claude改动」文件，旧版（v1）和新版（v2）各走一遍
  ① App 自动上传 最新数据.json → 两边上传的旧样子数据必须一样（by_at 不比）
  ② 提示条「查看并确认」→ 写入 → App 里全部记录两边一样；v2 只写了源头
  ③ 撤销 → 两边都回到原样
Google Drive 用 page.route 在内存里模拟；授权：预先放一个没过期的 token（不用登录弹窗）。
用法：python3 tests/test_v2_relay.py <旧 fixture.json> <v2 种子.json>（真实数据放仓库外面）"""
import os, datetime, functools, hashlib, http.server, json, re, sys, threading, pathlib, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
FIX1, FIX2 = (json.loads(pathlib.Path(a).read_text(encoding="utf8")) for a in sys.argv[1:3])
# 真实数据库里一次性的「补记录人」早就做过（meta/backfill.done）；种子里补上这个标记，不然旧版会在测试里再补一遍
for F in (FIX1, FIX2): F.setdefault("meta", {})["backfill"] = {"done": True}
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S };\n})();"
OWNER = hashlib.sha256(b"test@example.com").hexdigest()
TOKEN = "localStorage.setItem('fb-gtoken', JSON.stringify({ t: 'tok', exp: Date.now() + 3600e3, sc: 'https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly' }));"
SEEDRAND = "(() => { let s = 7; Math.random = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; }; })();"


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def send_text(self, body, ct):
        b = body.encode("utf8"); self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();"); return self.send_text(src[:i] + EXPOSE + src[i + 5:], "text/html; charset=utf-8")
        if path == "/firebase-config.js":
            src = re.sub(r"owners:\s*\[[^\]]*\]", f'owners: ["{OWNER}"]', (PUB / "firebase-config.js").read_text(encoding="utf8")); return self.send_text(src, "text/javascript")
        return super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))


class Drive:
    """内存里的 Google Drive：文件夹、文件、列表查询、上传、下载"""
    def __init__(self): self.files = {}; self.n = 0
    def add(self, name, parent=None, folder=False, content=None, created=None):
        self.n += 1; fid = "f%d" % self.n
        self.files[fid] = {"id": fid, "name": name, "parents": [parent] if parent else [], "folder": folder, "content": content, "createdTime": created or "2026-11-10T02:%02d:00Z" % self.n}
        return fid
    def find(self, q):
        out = []
        for f in self.files.values():
            ok = True
            for m in re.finditer(r"name\s*=\s*'([^']*)'", q): ok &= f["name"] == m.group(1)
            for m in re.finditer(r"name contains '([^']*)'", q): ok &= m.group(1) in f["name"]
            for m in re.finditer(r"'([^']*)' in parents", q): ok &= m.group(1) in f["parents"]
            if "mimeType='application/vnd.google-apps.folder'" in q: ok &= f["folder"]
            if ok: out.append(f)
        return sorted(out, key=lambda f: f["createdTime"], reverse=True)
    def handle(self, route):
        req = route.request; self.log = getattr(self, "log", []); self.log.append(req.method + " " + urllib.parse.unquote(req.url)[30:150])
        req = route.request; u = urllib.parse.urlparse(req.url); qs = urllib.parse.parse_qs(u.query); path = u.path
        js = lambda o: route.fulfill(status=200, content_type="application/json", body=json.dumps(o, ensure_ascii=False))
        m = re.match(r"^/drive/v3/files/([^/]+)$", path)
        if m and req.method == "GET": f = self.files.get(m.group(1)); return route.fulfill(status=200 if f else 404, content_type="application/json", body=f["content"] if f else "{}")
        if path == "/drive/v3/files" and req.method == "GET": return js({"files": [{"id": f["id"], "name": f["name"], "createdTime": f["createdTime"]} for f in self.find(qs.get("q", [""])[0])]})
        if path == "/drive/v3/files" and req.method == "POST":
            meta = json.loads(req.post_data or "{}"); return js({"id": self.add(meta.get("name"), (meta.get("parents") or [None])[0], meta.get("mimeType", "").endswith("folder"))})
        if path == "/upload/drive/v3/files" and req.method == "POST":
            body = req.post_data_buffer; bd = re.search(rb"boundary=([^;]+)", req.headers.get("content-type", "").encode()).group(1)
            parts = [p.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0] for p in body.split(b"--" + bd) if b"\r\n\r\n" in p]
            meta = json.loads(parts[0]); return js({"id": self.add(meta["name"], (meta.get("parents") or [None])[0], content=parts[1].decode("utf8"))})
        m = re.match(r"^/upload/drive/v3/files/([^/]+)$", path)
        if m and req.method == "PATCH": self.files[m.group(1)]["content"] = req.post_data; return js({"id": m.group(1)})
        return route.fulfill(status=404, body="{}")


def run(seed, label):
    D = Drive(); fold = D.add("FB 记账中转站", folder=True)
    # Claude 改动：改一个口味的价格、改一张订单的备注、删一条盘点流水、新增一笔手动支出
    it_id = sorted(FIX1["items"])[0]; it = FIX1["items"][it_id]
    od_id = sorted(FIX1["orders"])[5]; od = FIX1["orders"][od_id]
    mv_id = next(k for k in FIX1["movements"] if k.startswith("m-")); mv = FIX1["movements"][mv_id]
    ch = [{"col": "items", "id": it_id, "op": "set", "data": dict(it, price_aud=(it.get("price_aud") or 0) + 5), "base": it},
          {"col": "orders", "id": od_id, "op": "set", "data": dict(od, note="Claude 改的备注"), "base": od},
          {"col": "movements", "id": mv_id, "op": "delete", "data": None, "base": mv},
          {"col": "expenses", "id": "e-20261110-claude1", "op": "set", "data": {"date": "2026-11-10", "amount": 8, "category": "油费", "note": "Claude 加的"}, "base": None}]
    D.add("Claude改动-20261110-0300.json", fold, content=json.dumps({"format": "fb-jizhang-changes/1", "id": "c-test-1", "created_at": "2026-11-10T03:00:00Z", "based_on": None, "supersedes": None,
          "count": len(ch), "summary": ["测试"], "changes": ch, "log": []}, ensure_ascii=False))
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        pg = ctx.new_page(); pg.clock.set_fixed_time(datetime.datetime(2026, 11, 10, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))))
        pg.on("pageerror", lambda e: print("   页面报错：", e)); pg.on("dialog", lambda d: d.accept())
        pg.add_init_script(SEEDRAND + TOKEN + "window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("https://www.googleapis.com/**", D.handle)
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url and "www.googleapis.com" not in r.request.url else r.fallback())
        pg.goto(URL)
        pg.wait_for_function("window.__GM && window.__GM.S.orders.length > 50 && window.__GM.S.moves.length > 50", timeout=20000)
        state = lambda: pg.evaluate("""() => { const S = window.__GM.S, o = {}; for (const k of ["items", "orders", "moves", "expenses", "purchases", "transfers", "settles"]) o[k] = Object.fromEntries(S[k].map((x) => { const y = Object.assign({}, x); delete y._v; delete y.by_at; delete y.by; delete y.at; return [x.id, y]; })); return o; }""")
        s0 = state()
        # ① 自动上传（店主打开 6 秒后）
        pg.wait_for_timeout(9000)
        f = next((x for x in D.files.values() if x["name"] == "最新数据.json"), None)
        up = json.loads(f["content"])["data"] if f else None
        # ② 查看并确认 → 写入
        try: pg.wait_for_selector("[data-ib=open]", timeout=8000)
        except Exception:
            print("   Drive 请求：", *getattr(D, "log", [])[:12], sep="\n     "); print("   提示条：", pg.evaluate("(document.getElementById('inbox-bar')||{}).outerHTML"), "\n   标记：", pg.evaluate("document.body.innerText.slice(0,120)")); raise
        pg.click("[data-ib=open]")
        pg.wait_for_selector("#ib-apply", timeout=5000); conf = pg.inner_text("#inbox-dlg"); pg.click("#ib-apply")
        pg.wait_for_selector("[data-ib=undo]", timeout=8000); pg.wait_for_timeout(500)
        s1 = state()
        v2src = pg.evaluate(f"""() => ({{ order: (__server('v2_orders')['{od_id}'] || {{}}).note, moveDeleted: !!((__server('v2_movements')['{mv_id}'] || {{}})._deleted), exp: !!__server('v2_expenses')['e-20261110-claude1'],
              oldOrder: (__server('orders')['{od_id}'] || {{}}).note }})""")
        # ③ 撤销
        pg.click("[data-ib=undo]"); pg.wait_for_timeout(300)
        if pg.is_visible("[data-ib=undo]"): pg.click("[data-ib=undo]")
        pg.wait_for_timeout(1500)
        s2 = state()
        br.close()
    return {"up": up, "s0": s0, "s1": s1, "s2": s2, "conf": conf, "v2src": v2src, "ids": (it_id, od_id, mv_id)}


A, B = run(FIX1, "旧版"), run(FIX2, "新版")
strip = lambda d: {c: {i: {k: v for k, v in x.items() if k not in ("by_at",)} for i, x in m.items()} for c, m in (d or {}).items() if c in ("orders", "movements", "expenses", "purchases", "transfers", "settlements", "items")}
check("① 两边都自动上传了 最新数据.json", bool(A["up"]) and bool(B["up"]))
ua, ub = strip(A["up"]), strip(B["up"])
bad = [f"{c}/{i}" for c in ua for i in set(ua[c]) | set(ub.get(c, {})) if ua[c].get(i) != ub.get(c, {}).get(i)]
check("① 新版上传的旧样子数据 == 旧版上传的（订单/流水/支出/订货/往来/结账/口味）", not bad, f"{len(bad)} 处：{bad[:4]}" if bad else f"{sum(len(m) for m in ua.values())} 条")
check("② 两边核对弹窗一样（可写/跳过/冲突）", A["conf"] == B["conf"], "" if A["conf"] == B["conf"] else f"\n旧:{A['conf'][:200]}\n新:{B['conf'][:200]}")
d1 = [f"{k}/{i}" for k in A["s1"] for i in set(A["s1"][k]) | set(B["s1"][k]) if A["s1"][k].get(i) != B["s1"][k].get(i)]
check("② 写入 Claude 改动后，App 里全部记录两边一样", not d1, f"{d1[:4]}")
it_id, od_id, mv_id = A["ids"]
check("② 改动真的写进去了（价格、备注、删盘点、加支出）", B["s1"]["orders"][od_id]["note"] == "Claude 改的备注" and mv_id not in B["s1"]["moves"] and "e-20261110-claude1" in B["s1"]["expenses"] and B["s1"]["items"][it_id]["price_aud"] == (FIX1["items"][it_id].get("price_aud") or 0) + 5)
v = B["v2src"]
check("② 新版只改了源头（v2_orders 备注、v2_movements 删除标记、v2_expenses 新增），旧集合没动", v["order"] == "Claude 改的备注" and v["moveDeleted"] and v["exp"] and v["oldOrder"] != "Claude 改的备注", json.dumps(v, ensure_ascii=False))
d2 = [f"{k}/{i}" for k in B["s0"] for i in set(B["s0"][k]) | set(B["s2"][k]) if B["s0"][k].get(i) != B["s2"][k].get(i)]
d2a = [f"{k}/{i}" for k in A["s0"] for i in set(A["s0"][k]) | set(A["s2"][k]) if A["s0"][k].get(i) != A["s2"][k].get(i)]
check("③ 撤销后新版回到原样", not d2, f"{d2[:4]}")
check("③ 撤销后旧版也回到原样（对照）", not d2a, f"{d2a[:4]}")
if "--debug" in sys.argv:
    k = A["ids"][2]
    print("上传 旧:", json.dumps(ua["movements"].get(k), ensure_ascii=False)); print("上传 新:", json.dumps(ub["movements"].get(k), ensure_ascii=False))
    print("fixture:", json.dumps(FIX1["movements"][k], ensure_ascii=False))
    print("核对 旧:", A["conf"][:400]); print("核对 新:", B["conf"][:400])
    print("写入后 旧:", A["s1"]["moves"].get(k), " 新:", B["s1"]["moves"].get(k)); print("撤销后 旧:", A["s2"]["moves"].get(k), " 原来:", A["s0"]["moves"].get(k))
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)

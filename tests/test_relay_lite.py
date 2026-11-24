"""中转站省流量（2026-11-25）：以前每记一笔 4 秒后就把整份数据传一次（11-24 已 663KB，一天 30 多次 ≈ 20MB）
  ① 压缩成 最新数据.json.gz（里面还是 fb-jizhang-relay/1），解开跟原来的格式一样，比不压缩小
  ② 重新打开 App、数据没变：不传
  ③ 连续记几笔：离上次上传不满间隔（正式 10 分钟，测试改成 8 秒）不传，到点只传一次，几笔都带上
  ④ 切出 App 时有排着没传的：马上传
  ⑤ 点「中转站」手动传：数据没变也传
  ⑥ 手机不支持压缩：照旧传 最新数据.json
用编的小数据（新结构），GitHub 上也跑。运行：python3 tests/test_relay_lite.py"""
import os, sys, json, gzip, re, hashlib, datetime, functools, http.server, subprocess, tempfile, threading, pathlib, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
OWNER = hashlib.sha256(b"test@example.com").hexdigest()
TOKEN = "localStorage.setItem('fb-gtoken', JSON.stringify({ t: 'tok', exp: Date.now() + 3600e3, sc: 'https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly' }));"
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, v, n: {"sku": sku, "series": "Bar Pro", "variant": v, "name": n, "price_aud": 60, "cost_aud": 30, "status": "在售"}
V1 = {"items": {"XF-01": IT("XF-01", "Banana Buzz", "香蕉"), "XF-02": IT("XF-02", "Peach Ice", "蜜桃冰")},
      "movements": {f"b-1-{s}": {"type": "in", "sku": s, "name": "x", "qty": 10, "date": TODAY, "at": TODAY + "T01:00:00Z", "cost": 300, "batch_id": "b-1", "note": "进货"} for s in ("XF-01", "XF-02")},
      "expenses": {"b-1-cost": {"date": TODAY, "at": TODAY + "T01:00:00Z", "amount": 600, "category": "进货成本", "note": "进货", "batch_id": "b-1"}},
      "orders": {f"o-{i}": {"status": "paid", "date": TODAY, "at": TODAY + "T03:%02d:00Z" % i, "customer": "客人%d" % i, "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit_price": 60}],
                            "delivery_fee": 0, "payment": "现金", "note": "备注备注备注备注"} for i in range(1, 9)},
      "purchases": {}, "settlements": {}, "transfers": {}, "customers": {}, "followups": {}}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] == "/firebase-config.js":
            b = re.sub(r"owners:\s*\[[^\]]*\]", f'owners: ["{OWNER}"]', (PUB / "firebase-config.js").read_text(encoding="utf8")).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/javascript"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        return super().do_GET()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
results = []
def check(name, ok, extra=""):
    ok = bool(ok); results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))


class Drive:
    """内存里的 Google Drive，文件内容存原始字节"""
    def __init__(self): self.files = {}; self.n = 0; self.ups = []
    def add(self, name, parent=None, folder=False, content=None):
        self.n += 1; fid = "f%d" % self.n
        self.files[fid] = {"id": fid, "name": name, "parents": [parent] if parent else [], "folder": folder, "content": content}; return fid
    def by_name(self, name): return next((f for f in self.files.values() if f["name"] == name), None)
    def relay(self, name):
        f = self.by_name(name)
        if not f: return None
        b = f["content"]; return json.loads(gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b)
    def handle(self, route):
        req = route.request; u = urllib.parse.urlparse(req.url); qs = urllib.parse.parse_qs(u.query); path = u.path
        js = lambda o: route.fulfill(status=200, content_type="application/json", body=json.dumps(o, ensure_ascii=False))
        if path == "/drive/v3/files" and req.method == "GET":
            q = qs.get("q", [""])[0]; out = []
            for f in self.files.values():
                ok = True
                for m in re.finditer(r"name\s*=\s*'([^']*)'", q): ok &= f["name"] == m.group(1)
                for m in re.finditer(r"name contains '([^']*)'", q): ok &= m.group(1) in f["name"]
                for m in re.finditer(r"'([^']*)' in parents", q): ok &= m.group(1) in f["parents"]
                if "mimeType='application/vnd.google-apps.folder'" in q: ok &= f["folder"]
                if ok: out.append({"id": f["id"], "name": f["name"], "createdTime": "2026-11-25T00:00:00Z"})
            return js({"files": out})
        if path == "/drive/v3/files" and req.method == "POST":
            meta = json.loads(req.post_data or "{}"); return js({"id": self.add(meta.get("name"), (meta.get("parents") or [None])[0], meta.get("mimeType", "").endswith("folder"))})
        if path == "/upload/drive/v3/files" and req.method == "POST":
            body = req.post_data_buffer; bd = re.search(rb"boundary=([^;]+)", req.headers.get("content-type", "").encode()).group(1)
            parts = [p.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0] for p in body.split(b"--" + bd) if b"\r\n\r\n" in p]
            meta = json.loads(parts[0]); fid = self.add(meta["name"], (meta.get("parents") or [None])[0], content=parts[1])
            self.ups.append((meta["name"], len(parts[1]))); return js({"id": fid})
        m = re.match(r"^/upload/drive/v3/files/([^/]+)$", path)
        if m and req.method == "PATCH":
            f = self.files[m.group(1)]; f["content"] = req.post_data_buffer; self.ups.append((f["name"], len(f["content"]))); return js({"id": m.group(1)})
        return route.fulfill(status=404, body="{}")


def open_ctx(br, D, extra=""):
    ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
    ctx.add_init_script("window.__relayGap = 8000;" + TOKEN + extra + "window.__SEED = " + json.dumps(V2, ensure_ascii=False) + ";")
    ctx.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    ctx.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    ctx.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    ctx.route("https://www.googleapis.com/**", D.handle)
    ctx.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url and "www.googleapis.com" not in r.request.url else r.fallback())
    return ctx
def load(pg):
    pg.goto(URL); pg.wait_for_function("document.querySelector('#sync-badge') && window.__fbOwner === true", timeout=20000)
def write(pg, i): pg.evaluate("(i) => firebase.firestore().doc('customers/c-t' + i).set({ name: '测试客' + i, key: 'ce' + i })", i)


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    errs = []
    D = Drive(); D.add("FB 记账中转站", folder=True)
    ctx = open_ctx(br, D); pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    load(pg); pg.wait_for_timeout(8000)  # 打开 6 秒后传一次

    # ①
    R = D.relay("最新数据.json.gz")
    check("① 打开后传了一次压缩的 最新数据.json.gz，没传 最新数据.json", len(D.ups) == 1 and R is not None and D.by_name("最新数据.json") is None, D.ups)
    check("① 解开是原来的格式（fb-jizhang-relay/1、条数对得上、最后一笔）", R and R["format"] == "fb-jizhang-relay/1" and R["counts"]["orders"] == 8 == len(R["data"]["orders"]) and R["last_record"], R and R.get("counts"))
    raw = len(json.dumps(R, ensure_ascii=False).encode("utf8")) if R else 0
    check("① 压缩后比原来小", R and D.ups[0][1] < raw * 0.5, (D.ups[0][1], raw))
    check("① 右上角显示「中转站 几点」", "中转站 " in pg.inner_text("#sync-badge") and "待更新" not in pg.inner_text("#sync-badge"), pg.inner_text("#sync-badge"))

    # ②
    pg.reload(); pg.wait_for_function("window.__fbOwner === true", timeout=20000); pg.wait_for_timeout(8000)
    check("② 重新打开、数据没变：不传", len(D.ups) == 1, D.ups)

    # ③ 上一次（②里查过、没传）刚做过：现在连记 3 笔，间隔 8 秒内不传，到点只传一次、3 笔都在
    n = len(D.ups); write(pg, 1); pg.wait_for_timeout(300); write(pg, 2); pg.wait_for_timeout(300); write(pg, 3)
    pg.wait_for_timeout(5000); early = len(D.ups) - n
    for _ in range(80):
        if len(D.ups) > n: break
        pg.wait_for_timeout(100)
    pg.wait_for_timeout(300)
    R = D.relay("最新数据.json.gz"); got = sorted(k for k in (R or {}).get("data", {}).get("customers", {}))
    check("③ 连记 3 笔：5 秒时还没传（以前 4 秒就传）", early == 0, D.ups[n:])
    check("③ 连记 3 笔：到点只传一次，3 笔都带上", len(D.ups) - n == 1 and got == ["c-t1", "c-t2", "c-t3"], (D.ups[n:], got))
    # 刚传完马上又记一笔：要等满间隔
    n = len(D.ups); write(pg, 4); pg.wait_for_timeout(5500)
    check("③ 刚传完又记一笔：不满间隔不传", len(D.ups) == n, D.ups[n:])

    # ④ 切出 App：排着的那次马上传
    pg.evaluate("Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' }); document.dispatchEvent(new Event('visibilitychange'))")
    pg.wait_for_timeout(800)
    R = D.relay("最新数据.json.gz")
    check("④ 切出 App：马上传了，刚记的那笔在里面", len(D.ups) == n + 1 and "c-t4" in R["data"]["customers"], (D.ups[n:], list(R["data"]["customers"])))
    pg.evaluate("Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' }); document.dispatchEvent(new Event('visibilitychange'))")

    # ⑤ 手动：数据没变也传
    n = len(D.ups); pg.evaluate("window.__fbRelayNow()"); pg.wait_for_timeout(1500)
    check("⑤ 手动传（点「中转站」）：数据没变也传", len(D.ups) == n + 1, D.ups[n:])
    check("①–⑤ 一直只有一个 .gz 文件（覆盖，不是每次新建）", sum(1 for f in D.files.values() if f["name"] == "最新数据.json.gz") == 1)
    ctx.close()

    # ⑥ 不支持压缩
    D2 = Drive(); D2.add("FB 记账中转站", folder=True)
    ctx = open_ctx(br, D2, "delete window.CompressionStream;"); pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    load(pg); pg.wait_for_timeout(8000)
    R = D2.relay("最新数据.json")
    check("⑥ 不支持压缩：照旧传 最新数据.json（明文 JSON）", R and R["format"] == "fb-jizhang-relay/1" and D2.by_name("最新数据.json.gz") is None and D2.files[D2.by_name("最新数据.json")["id"]]["content"][:1] == b"{", D2.ups)
    ctx.close()
    check("全程页面没有报错", not errs, errs[:3])
    br.close()

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)

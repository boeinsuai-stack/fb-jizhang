/* 离线也能打开 App：
   - 安装时把 App 本身和 Firebase、Excel 组件（都放在本站 vendor/ 里）全部存进手机
   - App 本身（SHELL 里的文件）：直接用手机里存的，马上打开（2026-11-16：以前先走网络、3 秒没回应才用存的，信号差时白屏 3 秒 × 2）。
     新版靠 sw.js 本身：CACHE 版本号一变，浏览器装上新的 Service Worker、把新文件整套存好，下次打开就是新版；
     开着的时候 shim.js 会提示「有新版 · 点一下更新」。页面带 cache:"reload" / "no-store" 来要的照旧走网络
   - 其他本站文件（恢复页 import.html 等）：先走网络，3 秒没回应或没网就用手机里存的
   - vendor/ 里的文件带版本号、不会变：直接用手机里存的
   - 字体：有就存，没网时用存过的（拿不到就用系统字体，不影响使用）
   数据由 Firestore 离线缓存负责：没网时照常记账，联网后自动上传 */
const CACHE = "fb-app-v37";
const SHELL = ["./", "index.html", "v2.js", "orderparse.js", "shim.js", "firebase-config.js", "manifest.webmanifest", "icons/icon-192.png", "icons/apple-touch-icon.png",
  "vendor/firebasejs/10.12.2/firebase-app-compat.js", "vendor/firebasejs/10.12.2/firebase-auth-compat.js", "vendor/firebasejs/10.12.2/firebase-firestore-compat.js",
  "vendor/xlsx/0.18.5/xlsx.full.min.js"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });

const SHELL_PATHS = new Set(SHELL.map((p) => new URL(p, self.registration.scope).pathname));
const put = (req, res) => { if (res && (res.ok || res.type === "opaque")) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); } return res; };
const fromCache = (req) => caches.match(req, { ignoreSearch: true }).then((r) => r || (req.mode === "navigate" ? caches.match("index.html") : undefined));

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const same = url.origin === location.origin, font = /fonts\.(googleapis|gstatic)\.com/.test(url.hostname);
  if (!same && !font) return; // Firebase 数据、Google 登录等不经过这里

  if (same && url.pathname.includes("/vendor/")) { // 带版本号，不会变
    e.respondWith(caches.match(req).then((r) => r || fetch(req).then((res) => put(req, res))));
    return;
  }
  if (font) { // 先用存的，后台顺便更新
    e.respondWith(caches.match(req).then((r) => { const net = fetch(req).then((res) => put(req, res)).catch(() => r); return r || net; }));
    return;
  }
  if (same && SHELL_PATHS.has(url.pathname) && req.cache !== "reload" && req.cache !== "no-store") { // App 本身：先用存的
    e.respondWith(caches.match(req, { ignoreSearch: true }).then((r) => r || fetch(req).then((res) => put(req, res))));
    return;
  }
  // 其他本站文件：网络优先，3 秒超时就用手机里存的
  e.respondWith(new Promise((resolve) => {
    let done = false;
    const fallback = () => fromCache(req).then((r) => { if (r && !done) { done = true; resolve(r); } return r; });
    const timer = setTimeout(fallback, 3000);
    fetch(req).then((res) => { clearTimeout(timer); put(req, res); if (!done) { done = true; resolve(res); } })
      .catch(() => { clearTimeout(timer); fallback().then((r) => { if (!done) { done = true; resolve(r || Response.error()); } }); });
  }));
});

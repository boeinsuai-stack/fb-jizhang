/* 先走网络、失败再用缓存：有网时总是最新版本，没网时也能打开 App（数据由 Firestore 离线缓存负责） */
const CACHE = "fb-app-v7";
const SHELL = ["./", "index.html", "shim.js", "firebase-config.js", "manifest.webmanifest", "icons/icon-192.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // 只缓存本站文件和字体、组件脚本；Firebase 的数据请求不经过这里
  const cacheable = url.origin === location.origin || /(gstatic\.com\/firebasejs|cdnjs\.cloudflare\.com|fonts\.(googleapis|gstatic)\.com)/.test(url.href);
  if (!cacheable) return;
  e.respondWith(fetch(req).then((res) => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); } return res; })
    .catch(() => caches.match(req).then((r) => r || caches.match("index.html"))));
});

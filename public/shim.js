/* 转接层：让原来在 Claude 里运行的记账 App 不改业务代码，直接跑在 Firebase 上。
   App 调用 window.claude.use("db" | "user" | "downloads" ...)，这里用 Firebase 提供同样的接口。 */
(function () {
  const CFG = window.APP_CONFIG || {};
  firebase.initializeApp(window.FIREBASE_CONFIG);
  const auth = firebase.auth();
  const fs = firebase.firestore();
  // 和 Claude 数据库一致：值为 undefined 的字段直接忽略，而不是报错
  // cacheSizeBytes 无上限：手机里的本地数据库不自动清旧记录（App 现在从本地数据库读全部记录，见下面「增量同步」）
  fs.settings({ ignoreUndefinedProperties: true, merge: true, cacheSizeBytes: firebase.firestore.CACHE_SIZE_UNLIMITED });
  // 离线可用：没网时照常记账，联网后自动同步。persistOK = 本地数据库能不能用（隐私模式等情况下不能用）
  let persistOK = null;
  const persistReady = fs.enablePersistence({ synchronizeTabs: true }).then(() => { persistOK = true; }, (e) => { persistOK = false; console.warn("本地数据库不可用，改为每次从云端整份读取", e); });

  /* ---------- 登录界面 ---------- */
  let resolveUser;
  const userReady = new Promise((r) => { resolveUser = r; });
  let box = null;
  function showLogin(msg) {
    if (!box) {
      box = document.createElement("div");
      box.id = "login-box";
      box.innerHTML =
        '<style>#login-box{position:fixed;inset:0;z-index:99;display:grid;place-items:center;padding:24px;background:var(--bg,#f5f6f3);font-family:"Noto Sans SC",system-ui,sans-serif}' +
        "#login-box form{width:100%;max-width:340px;display:grid;gap:12px}" +
        "#login-box h1{margin:0 0 8px;font-size:1.8rem}" +
        "#login-box input{font:inherit;font-size:16px;padding:10px 12px;border:1px solid #dde1dc;border-radius:8px}" +
        "#login-box button{font:inherit;padding:11px;border:0;border-radius:8px;background:#2f6b5a;color:#fff;font-weight:600}" +
        "#login-box p{margin:0;color:#b23b3b;font-size:.9rem;min-height:1.2em}</style>" +
        '<form><h1>登录</h1><input name="e" type="email" autocomplete="username" placeholder="邮箱" required>' +
        '<input name="p" type="password" autocomplete="current-password" placeholder="密码" required>' +
        '<button>登录</button><p role="alert"></p></form>';
      box.querySelector("form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const f = ev.target;
        const btn = f.querySelector("button");
        f.querySelector("p").textContent = "";
        btn.disabled = true; btn.textContent = "登录中…";
        try { await auth.signInWithEmailAndPassword(f.e.value.trim(), f.p.value); }
        catch (e) { f.querySelector("p").textContent = e && e.code === "auth/network-request-failed" ? "网络不通，请检查网络后再试。" : "登录失败：邮箱或密码不对。"; }
        finally { btn.disabled = false; btn.textContent = "登录"; }
      });
      document.body.appendChild(box);
    }
    box.hidden = false;
    if (msg) box.querySelector("p").textContent = msg;
  }
  // 没网或信号很差时，Firebase 确认登录最长要等 30 秒，这段时间 App 一片空白。
  // 手机里记着上次是谁登录的：1.5 秒还没确认，就先用他打开（数据从手机缓存读，记账先存手机）。
  let started = null, lastU = null;
  const startWith = (u) => { if (started) return; started = u; resolveUser(u); };
  try { lastU = JSON.parse(localStorage.getItem("fb-last-user") || "null"); } catch (_) {}
  const fastStart = lastU && lastU.uid ? setTimeout(() => startWith(lastU), 1500) : null;
  auth.onAuthStateChanged((u) => {
    if (u) {
      try { localStorage.setItem("fb-last-user", JSON.stringify({ uid: u.uid, email: u.email || "", displayName: u.displayName || "" })); } catch (_) {}
      if (box) box.hidden = true;
      if (started && started.uid !== u.uid) { location.reload(); return; }
      startWith(u);
    } else {
      clearTimeout(fastStart); // 已经退出登录：不要再用上次的人启动
      try { localStorage.removeItem("fb-last-user"); } catch (_) {}
      if (document.body) showLogin(); else document.addEventListener("DOMContentLoaded", () => showLogin());
    }
  });

  /* ---------- user：谁在用 ---------- */
  async function sha256(t) {
    if (!(window.crypto && crypto.subtle)) return ""; // 只有 https 页面才有；正式网站一定是 https
    const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(t));
    return Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, "0")).join("");
  }
  async function userNs(u) {
    const email = (u.email || "").toLowerCase();
    const key = await sha256(email); // 配置里只存邮箱指纹，不存邮箱本身
    // 旧数据里记录的是 Claude 的用户 ID；同一个人登录后沿用旧 ID，旧记录才会显示「我记的」
    const myId = (CFG.legacyIds || {})[key] || u.uid;
    const myName = (CFG.displayNames || {})[key] || u.displayName || email.split("@")[0];
    const owner = (CFG.owners || []).includes(key);
    window.__fbOwner = owner; window.__fbMyId = myId;
    if (owner && !window.__fbRelayBoot) { window.__fbRelayBoot = 1; setTimeout(() => { paintBadge(); scheduleRelay(0); }, 6000); setTimeout(checkInbox, 800); } // 打开 App 时（含老婆记的账）刷新一次中转站
    // 每人登录时把「ID → 名字」写进 meta/people，另一个人的手机上就能显示「老婆记的」
    const peopleRef = fs.doc("meta/people");
    peopleRef.set({ [myId]: myName }, { merge: true }).catch(() => {});
    let people = { [myId]: myName };
    peopleRef.onSnapshot((s) => { if (s.exists) people = Object.assign({}, s.data(), { [myId]: myName }); }, () => {});
    return {
      id: async () => myId,
      me: async () => ({ id: myId, name: myName }),
      name: async () => myName,
      isOwner: async () => owner,
      canEdit: async () => true,
      can: () => true,
      profiles: async (ids) => {
        try { const s = await peopleRef.get(); if (s.exists) people = Object.assign({}, s.data(), { [myId]: myName }); } catch (_) {}
        const r = {}; (ids || []).forEach((i) => { r[i] = { id: i, name: people[i] || "" }; }); return r;
      },
      search: async () => [],
    };
  }

  /* ---------- downloads：导出 Excel ---------- */
  const downloads = {
    save: async ({ filename, data }) => {
      const blob = data instanceof Blob ? data : new Blob([data], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      const file = new File([blob], filename, { type: blob.type });
      // iPhone 上优先弹出系统分享面板（可以存到「文件」或发微信）
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        try { await navigator.share({ files: [file], title: filename }); return; }
        catch (e) { if (e && e.name === "AbortError") return; }
      }
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    },
  };

  /* ---------- 云端同步状态标记 ---------- */
  // 每次写入后等 Firestore 服务器确认；确认了才显示「已保存到云端」
  let pending = 0, lastSaved = null, badge = null;
  try { lastSaved = localStorage.getItem("fb-last-saved"); } catch (_) {}
  const hhmm = (d) => { d = new Date(d); const t = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); return new Date().toDateString() === d.toDateString() ? t : (d.getMonth() + 1) + "/" + d.getDate() + " " + t; };
  function paintBadge() {
    if (!badge || !badge.isConnected) {
      badge = document.createElement("span");
      badge.id = "sync-badge";
      badge.setAttribute("role", "status");
      badge.style.cssText = "display:inline-flex;align-items:center;gap:5px;margin-left:10px;font:500 11px/1 -apple-system,'Noto Sans SC',system-ui,sans-serif;letter-spacing:0;vertical-align:1px;white-space:nowrap";
      badge.innerHTML = '<i style="width:7px;height:7px;border-radius:50%;display:inline-block;flex:none"></i><b style="font-weight:500"></b>';
      // 固定在 App 顶部标题区的右上角，跟着页面一起滚动（往下滑就看不到了）
      const host = document.querySelector("header.top");
      if (host) {
        host.style.position = "relative";
        badge.style.cssText += ";position:absolute;top:1px;right:0;margin:0";
        host.appendChild(badge);
      } else {
        badge.style.cssText += ";position:absolute;top:calc(env(safe-area-inset-top,0px) + 10px);right:16px;margin:0";
        document.body.appendChild(badge);
      }
    }
    const off = !navigator.onLine;
    let t, c;
    if (failed) { t = failed + " 笔云端没收下（" + failMsg + "）· 发给 Claude 看"; c = "#b23b3b"; }
    else if (pending > 0 && off) { t = "没网 · " + pending + " 笔待上传"; c = "#d08a2e"; }
    else if (pending > 0) { t = "保存中…"; c = "#9aa3ad"; }
    else if (off) { t = "没网 · 先存在手机里"; c = "#d08a2e"; }
    else { t = "已保存到云端" + (lastSaved ? " " + hhmm(lastSaved) : ""); c = "#2fa36b"; }
    badge.firstChild.style.background = c;
    const main = badge.querySelector("b");
    main.textContent = t;
    main.style.color = c === "#2fa36b" ? "var(--muted, #66707d)" : c;
    // 中转站状态（只有 Bowen 的手机负责上传，老婆的手机不显示）
    let r = badge.querySelector("u");
    if (!r) { r = document.createElement("u"); r.style.cssText = "text-decoration:none;margin-left:4px"; badge.appendChild(r); }
    if (!relayOn()) { r.textContent = ""; badge.style.cursor = ""; return; }
    const stale = relayState === "stale" || relayState === "error" || (!canRead() && relayState !== "uploading");
    r.textContent = relayState === "uploading" ? "· 中转站上传中…" : stale ? "· 中转站待更新 ↻" : relayAt ? "· 中转站 " + hhmm(relayAt) : "· 中转站待更新 ↻";
    r.style.color = stale || !relayAt ? "#d08a2e" : "var(--muted, #66707d)";
    badge.style.cursor = stale || !relayAt ? "pointer" : "";
  }
  function trackWrite(p) {
    pending++; paintBadge();
    const done = () => fs.waitForPendingWrites().then(() => {
      pending = 0; lastSaved = new Date().toISOString();
      try { localStorage.setItem("fb-last-saved", lastSaved); } catch (_) {}
      paintBadge();
      scheduleRelay();
    });
    Promise.resolve(p).then(done, done);
    return p;
  }
  // 包住所有写入操作（App 原代码不用改）
  // 没网也能记账：Firestore 的 set/update/delete 要等云端确认才算完成，没网时永远等不到，
  // App 的「保存」就一直卡着，后面几笔也写不进去。改成：写进手机（本地缓存）就算完成；
  // 云端确认交给右上角的「已保存到云端」。读一次本地缓存排在这笔写入后面，读完说明写入已经进了手机、
  // 页面也已经收到更新（再等一拍让 onSnapshot 跑完），跟有网时一样。
  const localDone = () => fs.doc("meta/people").get({ source: "cache" }).catch(() => {}).then(() => new Promise((r) => setTimeout(r, 0)));
  let failed = 0, failMsg = "";
  function local(p) {
    let settled = false;
    p.catch((e) => { if (!settled) return; failed++; failMsg = (e && (e.code || e.message)) || String(e); paintBadge(); console.error("云端没收下这笔", e); });
    return Promise.race([p, localDone()]).finally(() => { settled = true; });
  }
  /* ---------- 增量同步：写入这一半 ----------
     账本里的记录（SYNCED）每次写入都自动带上 _u = 云端收到的时间。另一台手机只需要问云端
     「_u 比我上次看到的晚的有哪些」，不用每次把全部记录重读一遍（重读按条数收费，记录越多越贵）。
     删除不真删，而是留一个 { _deleted: true } 标记：这样删除也有 _u，另一台手机能同步到。App 里看不到这些标记。 */
  const SYNCED = new Set(["items", "movements", "orders", "expenses", "purchases", "settlements", "transfers", "customers", "followups", "log",
    "v2_orders", "v2_purchases", "v2_transfers", "v2_movements", "v2_expenses", "v2_batches", "v2_settlements"]);
  const FV = firebase.firestore.FieldValue;
  const synced = (ref) => !!ref && !!ref.parent && !ref.parent.parent && SYNCED.has(ref.parent.id);
  const tomb = () => ({ _deleted: true, _u: FV.serverTimestamp() });
  const stampSet = (ref, d, opt) => (!synced(ref) || !d || typeof d !== "object" ? d : Object.assign({}, d, { _u: FV.serverTimestamp() }, opt && opt.merge ? { _deleted: FV.delete() } : {}));
  const stampUpd = (ref, a) => (!synced(ref) ? a : a.length && a[0] && typeof a[0] === "object" && !(a[0] instanceof firebase.firestore.FieldPath) ? [Object.assign({}, a[0], { _u: FV.serverTimestamp() })].concat(a.slice(1)) : a.concat(["_u", FV.serverTimestamp()]));
  const DR = firebase.firestore.DocumentReference.prototype;
  const dSet = DR.set, dUpd = DR.update, dDel = DR.delete;
  DR.set = function (d, opt) { return local(trackWrite(dSet.call(this, stampSet(this, d, opt), opt))); };
  DR.update = function (...a) { return local(trackWrite(dUpd.apply(this, stampUpd(this, a)))); };
  DR.delete = function () { return local(trackWrite(synced(this) ? dSet.call(this, tomb()) : dDel.call(this))); };
  const WB = firebase.firestore.WriteBatch.prototype, origCommit = WB.commit;
  const bSet = WB.set, bUpd = WB.update, bDel = WB.delete;
  WB.set = function (ref, d, opt) { return bSet.call(this, ref, stampSet(ref, d, opt), opt); };
  WB.update = function (ref, ...a) { return bUpd.call(this, ref, ...stampUpd(ref, a)); };
  WB.delete = function (ref) { return synced(ref) ? bSet.call(this, ref, tomb()) : bDel.call(this, ref); };
  WB.commit = function (...a) { return local(trackWrite(origCommit.apply(this, a))); };
  // 读一条记录：已删除标记 = 不存在；去掉内部字段 _u
  const live = (s) => { if (!s || !s.exists) return null; const x = s.data(); if (!x || x._deleted) return null; delete x._u; return x; };

  /* ---------- 增量同步：读取这一半 ----------
     以前：每类记录 limit(1000) 直接从云端订阅。超过 1000 条后按编号丢记录（t- 开头的合伙人往来先丢），
     而且每次打开 App（离开超过 30 分钟）都把全部记录重新计费读一遍。
     现在：页面从手机里的本地数据库读全部记录（不收费、没网也能读）；另开一个只问「新改动」的云端监听，
     把别的手机的改动拉进本地数据库。每台手机每天整份对一次账（补漏、清理旧版本真删的记录）。 */
  const MARGIN = 10 * 60e3, DAY = 24 * 3600e3;
  let syncUid = "";
  const pulled = {};
  const maxU = (s) => s.docs.reduce((m, d) => { if (d.metadata.hasPendingWrites) return m; const u = d.get("_u"); return u && u.toMillis ? Math.max(m, u.toMillis()) : m; }, 0);
  function pull(c) {
    if (pulled[c]) return; pulled[c] = 1;
    const key = "fb-sync:" + syncUid + ":" + c;
    let st = {}; try { st = JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch (_) {}
    const save = (o) => { Object.assign(st, o); try { localStorage.setItem(key, JSON.stringify(st)); } catch (_) {} };
    const delta = () => {
      const since = firebase.firestore.Timestamp.fromMillis(Math.max(0, (st.since || 0) - MARGIN));
      fs.collection(c).where("_u", ">", since).onSnapshot({ includeMetadataChanges: true }, (s) => {
        if (s.metadata.fromCache) return;
        const m = maxU(s); if (m > (st.since || 0)) save({ since: m });
      }, (e) => console.warn("增量同步出错：" + c, e));
    };
    const full = () => {
      const t0 = Date.now();
      const un = fs.collection(c).onSnapshot({ includeMetadataChanges: true }, (s) => {
        if (s.metadata.fromCache) return; // 等云端的完整结果
        un();
        save({ since: Math.max(maxU(s), st.since || 0) || t0 - 3600e3, full: Date.now(), n: s.size });
        delta();
      }, (e) => { console.warn("整份对账出错：" + c, e); if (st.since) delta(); });
    };
    fs.collection(c).get({ source: "cache" }).then((s) => s.size, () => 0).then((have) => {
      // 本地数据库是空的（新手机、清过数据）或者一天没对账了：先整份读一次
      if (!st.since || !have || Date.now() - (st.full || 0) > DAY) full(); else delta();
    });
  }
  // 给页面的快照：去掉已删除的、去掉 _u；有 lim 时只给前 lim 条（操作记录只显示最新 200 条）
  function view(s, lim) {
    let docs = s.docs.filter((d) => !d.get("_deleted")).map((d) => ({ id: d.id, ref: d.ref, exists: true, metadata: d.metadata, get: (f) => d.get(f), data: () => { const x = d.data({ serverTimestamps: "estimate" }); delete x._u; return x; } }));
    if (lim) docs = docs.slice(0, lim);
    return { docs, size: docs.length, empty: !docs.length, metadata: s.metadata, forEach: (f) => docs.forEach(f) };
  }
  function listen(c, order, lim, next, err) {
    let un = null, stop = false;
    persistReady.then(() => {
      if (stop) return;
      let q = fs.collection(c); if (order) q = q.orderBy(order[0], order[1]);
      if (persistOK === false) { if (lim) q = q.limit(lim * 2); un = q.onSnapshot((s) => next(view(s, lim)), err); return; } // 没有本地数据库：直接读云端（不再限 1000 条）
      un = q.onSnapshot({ source: "cache" }, (s) => next(view(s, lim)), err);
      pull(c);
    });
    return () => { stop = true; if (un) un(); };
  }
  function syncedQuery(c, order, lim) {
    return {
      limit: (n) => syncedQuery(c, order, order ? n : null), // 没排序的 limit(1000) 不再生效：全部记录都要
      orderBy: (f, d) => syncedQuery(c, [f, d || "asc"], lim),
      onSnapshot: (...a) => { const fns = a.filter((x) => typeof x === "function"); return listen(c, order, lim, fns[0], fns[1]); },
    };
  }
  // 交给业务代码的数据库：账本集合走增量同步，其他（meta 等）照旧
  const dbApi = {
    collection: (c) => {
      const raw = fs.collection(c);
      if (!SYNCED.has(c)) return raw;
      return Object.assign(syncedQuery(c, null, null), { doc: (id) => raw.doc(id), id: c });
    },
    doc: (p) => fs.doc(p),
    batch: () => fs.batch(),
  };
  window.addEventListener("online", paintBadge);
  window.addEventListener("offline", paintBadge);

  /* ---------- mcp：备份到 Google Drive ---------- */
  // 原 App 调用 mcp.callTool("Google Drive", "create_file", {...})。这里用 Google 官方的网页授权（只申请
  // 「本应用创建的文件」权限 drive.file，看不到你 Drive 里的其他文件）直接上传。
  const DRIVE_FOLDER = "FB 记账备份";
  // drive.file：上传备份和中转站；drive.readonly：读 Claude 版放进中转站的「改动清单」（Claude 建的文件 drive.file 看不到）
  const SCOPES = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly";
  let token = null, tokenExp = 0, tokenScope = "", tokenWait = null, tokenClient = null;
  try { const t = JSON.parse(localStorage.getItem("fb-gtoken") || "null"); if (t && t.exp > Date.now()) { token = t.t; tokenExp = t.exp; tokenScope = t.sc || ""; } } catch (_) {}
  const tokenOk = () => !!token && Date.now() < tokenExp;
  const canRead = () => tokenOk() && /drive\.readonly/.test(tokenScope);
  function gis() {
    if (tokenClient || !(window.google && google.accounts && google.accounts.oauth2) || !CFG.googleClientId) return tokenClient;
    tokenClient = google.accounts.oauth2.initTokenClient({
      client_id: CFG.googleClientId,
      scope: SCOPES,
      callback: () => {},
    });
    return tokenClient;
  }
  // 必须在「点按钮」的那一刻直接弹授权窗口，否则 iPhone 会拦截弹窗；所以在按钮上抢先监听点击
  function askToken() {
    if (tokenOk() && (canRead() || !window.__fbOwner)) return Promise.resolve(token);
    const tc = gis();
    if (!tc) return Promise.reject({ code: "tool_error", message: "Google 授权组件没加载出来，请检查网络后刷新" });
    tokenWait = new Promise((ok, bad) => {
      tc.callback = (r) => {
        if (r && r.access_token) {
          token = r.access_token; tokenExp = Date.now() + (Number(r.expires_in) || 3000) * 1000 - 60000; tokenScope = r.scope || "";
          try { localStorage.setItem("fb-gtoken", JSON.stringify({ t: token, exp: tokenExp, sc: tokenScope })); } catch (_) {}
          ok(token); scheduleRelay(0); checkInbox();
        }
        else bad({ code: "consent_required", message: (r && r.error) || "没有授权" });
      };
      tc.error_callback = (e) => bad({ code: "tool_error", message: e && e.type === "popup_failed_to_open" ? "授权窗口被拦截了。可以先用「导出 Excel」→ 分享 → Google Drive" : e && e.type === "popup_closed" ? "授权窗口被关掉了" : "Google 授权失败" });
      let seen = false; try { seen = !!localStorage.getItem("fb-gauth-once"); localStorage.setItem("fb-gauth-once", "1"); } catch (_) {}
      tc.requestAccessToken({ prompt: token || seen ? "" : "consent" });
    });
    return tokenWait;
  }
  document.addEventListener("click", (e) => { if (e.target && e.target.closest && e.target.closest("#bk-btn")) askToken().catch(() => {}); }, true);
  async function gfetch(url, opt = {}) {
    const r = await fetch(url, Object.assign({}, opt, { headers: Object.assign({ Authorization: "Bearer " + token }, opt.headers || {}) }));
    if (r.status === 401) { token = null; tokenExp = 0; try { localStorage.removeItem("fb-gtoken"); } catch (_) {} throw { code: "tool_error", message: "Google 授权过期了，请再点一次备份" }; }
    if (!r.ok) throw { code: "tool_error", message: "Google Drive 返回 " + r.status };
    return opt.raw ? r.text() : r.json();
  }
  async function folderId() {
    try { const c = localStorage.getItem("fb-drive-folder"); if (c) return c; } catch (_) {}
    const q = encodeURIComponent("name='" + DRIVE_FOLDER + "' and mimeType='application/vnd.google-apps.folder' and trashed=false");
    const l = await gfetch("https://www.googleapis.com/drive/v3/files?fields=files(id)&q=" + q);
    const id = l.files && l.files[0] ? l.files[0].id : (await gfetch("https://www.googleapis.com/drive/v3/files?fields=id", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: DRIVE_FOLDER, mimeType: "application/vnd.google-apps.folder" }),
    })).id;
    try { localStorage.setItem("fb-drive-folder", id); } catch (_) {}
    window.__driveFolderUrl = "https://drive.google.com/drive/folders/" + id;
    return id;
  }
  const mcp = {
    callTool: async (server, tool, input) => {
      if (server !== "Google Drive" || tool !== "create_file") throw { code: "tool_error", message: "不支持的操作" };
      await (tokenWait || askToken());
      tokenWait = null;
      const parent = await folderId(); // 放进本应用自己建的文件夹，而不是旧的 Claude 备份文件夹
      const bin = Uint8Array.from(atob(input.base64Content), (c) => c.charCodeAt(0));
      const form = new FormData();
      form.append("metadata", new Blob([JSON.stringify({ name: input.title + ".xlsx", parents: [parent] })], { type: "application/json" }));
      form.append("file", new Blob([bin], { type: input.contentMimeType }));
      const f = await gfetch("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink", { method: "POST", body: form });
      return { payload: { id: f.id, viewUrl: f.webViewLink } };
    },
  };
  try { const c = localStorage.getItem("fb-drive-folder"); if (c) window.__driveFolderUrl = "https://drive.google.com/drive/folders/" + c; } catch (_) {}

  /* ---------- 中转站：把 Firebase 的完整数据拷贝一份到 Google Drive，给 Claude 版读取 ---------- */
  // 不是一条条攒改动，而是每次上传「当前全部数据」的完整拷贝，覆盖旧的那份；所以晚传、漏传都不会乱。
  const RELAY_FOLDER = "FB 记账中转站", RELAY_FILE = "最新数据.json";
  const COLLS = ["items", "movements", "orders", "expenses", "purchases", "settlements", "transfers", "customers", "followups", "log", "meta"];
  let relayAt = null, relayState = "idle", relayTimer = null, relayBusy = false, relayAgain = false;
  try { relayAt = localStorage.getItem("fb-relay-at"); if (localStorage.getItem("fb-relay-stale")) relayState = "stale"; } catch (_) {}
  const relayOn = () => window.__fbOwner === true && !!CFG.googleClientId;
  function markStale() { relayState = "stale"; try { localStorage.setItem("fb-relay-stale", "1"); } catch (_) {} paintBadge(); }
  function scheduleRelay(ms) {
    if (!relayOn()) return;
    if (!tokenOk()) { markStale(); return; } // 授权过期：只记一个「待更新」标记，等你点一下再传
    clearTimeout(relayTimer);
    relayTimer = setTimeout(uploadRelay, ms == null ? 4000 : ms); // 连续记几笔只传一次
  }
  async function relayIds() {
    let ids = {};
    try { ids = JSON.parse(localStorage.getItem("fb-relay-ids") || "{}"); } catch (_) {}
    if (ids.folder && ids.file) return ids;
    const q = (x) => encodeURIComponent(x);
    const fl = await gfetch("https://www.googleapis.com/drive/v3/files?fields=files(id)&q=" + q("name='" + RELAY_FOLDER + "' and mimeType='application/vnd.google-apps.folder' and trashed=false"));
    ids.folder = fl.files && fl.files[0] ? fl.files[0].id : (await gfetch("https://www.googleapis.com/drive/v3/files?fields=id", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: RELAY_FOLDER, mimeType: "application/vnd.google-apps.folder" }),
    })).id;
    const ff = await gfetch("https://www.googleapis.com/drive/v3/files?fields=files(id)&q=" + q("name='" + RELAY_FILE + "' and '" + ids.folder + "' in parents and trashed=false"));
    ids.file = ff.files && ff.files[0] ? ff.files[0].id : null;
    try { localStorage.setItem("fb-relay-ids", JSON.stringify(ids)); } catch (_) {}
    return ids;
  }
  function lastRecord(data) {
    const all = [];
    for (const c of ["orders", "movements", "expenses", "transfers", "settlements"]) for (const [id, d] of Object.entries(data[c] || {})) if (d && d.at) all.push([String(d.at), c, id, d]);
    all.sort((a, b) => (a[0] < b[0] ? 1 : -1));
    if (!all.length) return null;
    const [at, c, id, d] = all[0];
    const what = c === "orders" ? (d.customer ? d.customer + " " : "") + (d.lines || []).map((l) => (l.name || l.sku) + "×" + l.qty).join("、") : d.note || d.name || "";
    return { at, collection: c, id, text: what.slice(0, 80) };
  }
  async function uploadRelay() {
    if (!relayOn() || !tokenOk()) { if (relayOn()) markStale(); return; }
    if (relayBusy) { relayAgain = true; return; }
    if (pending > 0) { relayTimer = setTimeout(uploadRelay, 2000); return; } // 等云端确认保存后再拷贝
    relayBusy = true; relayState = "uploading"; paintBadge();
    try {
      const data = {};
      for (const c of COLLS) {
        let snap;
        try { snap = await fs.collection(c).get({ source: "cache" }); } catch (_) { snap = await fs.collection(c).get(); } // 读手机缓存，不消耗 Firebase 读取额度
        data[c] = {}; snap.docs.forEach((d) => { const x = live(d); if (x) data[c][d.id] = x; });
      }
      const counts = {}; for (const c of COLLS) counts[c] = Object.keys(data[c]).length;
      const body = JSON.stringify({ format: "fb-jizhang-relay/1", uploaded_at: new Date().toISOString(), saved_at: lastSaved, uploaded_by: "Bowen 的手机", counts, last_record: lastRecord(data), data });
      let ids = await relayIds();
      const put = (id) => id
        ? gfetch("https://www.googleapis.com/upload/drive/v3/files/" + id + "?uploadType=media&fields=id", { method: "PATCH", headers: { "Content-Type": "application/json" }, body })
        : (() => { const f = new FormData();
            f.append("metadata", new Blob([JSON.stringify({ name: RELAY_FILE, parents: [ids.folder], mimeType: "application/json" })], { type: "application/json" }));
            f.append("file", new Blob([body], { type: "application/json" }));
            return gfetch("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id", { method: "POST", body: f }); })();
      let r;
      try { r = await put(ids.file); }
      catch (e) { if (!ids.file || !/404/.test(e && e.message)) throw e; try { localStorage.removeItem("fb-relay-ids"); } catch (_) {} ids = await relayIds(); r = await put(ids.file); } // 文件被删了就重建
      if (!ids.file) { ids.file = r.id; try { localStorage.setItem("fb-relay-ids", JSON.stringify(ids)); } catch (_) {} }
      relayAt = new Date().toISOString(); relayState = "ok";
      try { localStorage.setItem("fb-relay-at", relayAt); localStorage.removeItem("fb-relay-stale"); } catch (_) {}
    } catch (e) {
      relayState = "error"; try { localStorage.setItem("fb-relay-stale", "1"); } catch (_) {}
    } finally {
      relayBusy = false; paintBadge();
      if (relayAgain) { relayAgain = false; scheduleRelay(1000); }
    }
  }
  // 点「中转站待更新 ↻」：在点的那一刻弹授权（iPhone 要求），然后马上上传
  document.addEventListener("click", (e) => {
    const b = e.target && e.target.closest && e.target.closest("#sync-badge");
    if (!b || !relayOn() || relayState === "uploading") return;
    if (relayState !== "stale" && relayState !== "error" && relayAt && canRead()) return;
    askToken().then(() => { scheduleRelay(0); checkInbox(); }, () => {});
  }, true);
  window.__fbRelayNow = () => scheduleRelay(0);

  /* ---------- 中转站 → App：Claude 版发来的「改动清单」 ----------
     Claude 版点「同步到 App」后，在中转站文件夹新建 Claude改动-*.json（格式 fb-jizhang-changes/1）。
     这里在打开 App / 每次拿到 Google 授权时检查最新一份：用人话列出来 → 逐条核对冲突 → 你点确认才写入 Firebase。
     写入前把每条记录原来的样子存进 relay_undo/<清单id>，可以一键撤销。只认最新一份清单。 */
  const INBOX_COLLS = ["items", "movements", "orders", "expenses", "purchases", "settlements", "transfers", "customers", "followups"];
  const INBOX_LABEL = { items: "香型", movements: "库存流水", orders: "订单", expenses: "支出", purchases: "订货单", settlements: "结账", transfers: "合伙人往来", customers: "客户资料", followups: "跟进" };
  const ID_OK = /^[A-Za-z0-9_\-.~:@+]{1,200}$/;
  let inbox = null, inboxBusy = false, inboxBar = null, inboxDone = null;
  try { inboxDone = JSON.parse(localStorage.getItem("fb-inbox-done") || "null"); if (inboxDone && Date.now() - new Date(inboxDone.at).getTime() > 864e5) inboxDone = null; } catch (_) {}
  function same(a, b) {
    if (a === b) return true;
    if (a == null || b == null || typeof a !== "object" || typeof b !== "object") return a === b;
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    if (Array.isArray(a)) return a.length === b.length && a.every((x, i) => same(x, b[i]));
    const ka = Object.keys(a).filter((k) => a[k] !== undefined).sort(), kb = Object.keys(b).filter((k) => b[k] !== undefined).sort();
    return ka.length === kb.length && ka.every((k, i) => k === kb[i] && same(a[k], b[k]));
  }
  const ihhmm = (iso) => { const d = new Date(iso); return isNaN(d) ? "?" : (d.getMonth() + 1) + "月" + d.getDate() + "日 " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
  const iesc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function inboxCss() {
    if (document.getElementById("inbox-css")) return;
    const st = document.createElement("style"); st.id = "inbox-css";
    st.textContent = "#inbox-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 12px;padding:10px 14px;border-radius:10px;border:1px solid var(--accent,#2f6b5a);background:var(--accent-soft,#e2efe9);color:var(--fg,#1d2430);font-size:.9rem}" +
      "#inbox-bar.done{border-color:var(--line,#dde1dc);background:var(--surface,#fff)}#inbox-bar b{font-weight:600}#inbox-bar .ib-btns{display:flex;gap:6px}" +
      "#inbox-dlg{position:fixed;inset:0;z-index:60;background:rgba(20,26,32,.45);display:flex;align-items:flex-end;justify-content:center;padding:calc(12px + env(safe-area-inset-top,0px)) 12px calc(12px + env(safe-area-inset-bottom,0px))}" +
      "@media(min-width:640px){#inbox-dlg{align-items:center}}" +
      "#inbox-dlg .card{background:var(--surface,#fff);color:var(--fg,#1d2430);border-radius:14px;width:100%;max-width:560px;max-height:100%;overflow:auto;padding:18px;display:grid;gap:12px;box-shadow:0 12px 40px rgba(0,0,0,.25)}" +
      "#inbox-dlg h3{margin:0;font-size:1.3rem}#inbox-dlg p{margin:0;font-size:.86rem;color:var(--muted,#66707d)}#inbox-dlg p.err{color:var(--bad,#b23b3b)}" +
      "#inbox-dlg ul{list-style:none;margin:0;padding:0;border:1px solid var(--line,#dde1dc);border-radius:8px}" +
      "#inbox-dlg li{padding:9px 12px;font-size:.88rem;overflow-wrap:anywhere}#inbox-dlg li+li{border-top:1px solid var(--line,#dde1dc)}" +
      "#inbox-dlg li .k{font-weight:600;margin-right:6px}#inbox-dlg li .k.add{color:var(--accent,#2f6b5a)}#inbox-dlg li .k.mod{color:var(--warn,#a8641a)}#inbox-dlg li .k.del{color:var(--bad,#b23b3b)}" +
      "#inbox-dlg li small{display:block;color:var(--muted,#66707d);font-size:.78rem;margin-top:2px}#inbox-dlg li.skip{opacity:.55}" +
      "#inbox-dlg li.conf{background:var(--warn-soft,#fbeedd)}#inbox-dlg li.conf label{display:flex;gap:6px;align-items:center;margin-top:6px;font-size:.82rem;color:var(--warn,#a8641a)}#inbox-dlg li.conf input{width:auto;margin:0}" +
      "#inbox-dlg .acts{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}";
    document.head.appendChild(st);
  }
  function paintInbox() {
    inboxCss();
    const host = document.querySelector("header.top");
    if (!host) return;
    if (!inboxBar || !inboxBar.isConnected) { inboxBar = document.createElement("div"); inboxBar.id = "inbox-bar"; inboxBar.setAttribute("role", "status"); host.insertAdjacentElement("afterend", inboxBar); }
    if (inbox && inbox.pending) {
      inboxBar.className = ""; inboxBar.hidden = false;
      inboxBar.innerHTML = "<span><b>Claude 版发来 " + inbox.file.count + " 条改动</b>（" + iesc(ihhmm(inbox.file.created_at)) + "）</span><span class=\"ib-btns\"><button class=\"btn small primary\" type=\"button\" data-ib=\"open\">查看并确认</button></span>";
    } else if (inboxDone) {
      inboxBar.className = "done"; inboxBar.hidden = false;
      inboxBar.innerHTML = "<span>已写入 Claude 版的 " + inboxDone.n + " 条改动（" + iesc(ihhmm(inboxDone.at)) + "）</span><span class=\"ib-btns\"><button class=\"btn small\" type=\"button\" data-ib=\"undo\">撤销</button><button class=\"btn small ghost\" type=\"button\" data-ib=\"ok\">知道了</button></span>";
    } else inboxBar.hidden = true;
  }
  async function checkInbox() {
    if (!relayOn() || !canRead() || inboxBusy) { paintBadge(); return; }
    const dlgOpen = document.getElementById("inbox-dlg"); if (dlgOpen && !dlgOpen.hidden) return; // 正在看弹窗时不打扰
    inboxBusy = true;
    try {
      const ids = await relayIds();
      const q = encodeURIComponent("'" + ids.folder + "' in parents and name contains 'Claude改动-' and trashed=false");
      const l = await gfetch("https://www.googleapis.com/drive/v3/files?orderBy=createdTime%20desc&pageSize=5&fields=files(id,name,createdTime)&q=" + q);
      const f = l.files && l.files[0];
      if (!f) { inbox = null; paintInbox(); return; }
      let seenId = null; try { seenId = localStorage.getItem("fb-inbox-seen"); } catch (_) {}
      if (seenId === f.id) { inbox = null; paintInbox(); return; } // 这份已经处理过，不用再查
      const applied = await fs.doc("meta/relay_applied").get().catch(() => null);
      const last = applied && applied.exists ? applied.data() : {};
      if (inbox && inbox.pending && inbox.fileId === f.id) { paintInbox(); return; } // 已经提示着这份
      if (last.last_file_id === f.id) { try { localStorage.setItem("fb-inbox-seen", f.id); } catch (_) {} inbox = null; paintInbox(); return; }
      const file = JSON.parse(await gfetch("https://www.googleapis.com/drive/v3/files/" + f.id + "?alt=media", { raw: true }));
      if (!file || file.format !== "fb-jizhang-changes/1" || !Array.isArray(file.changes)) throw new Error("清单格式不对");
      if (last.last_created_at && file.created_at <= last.last_created_at) { inbox = null; paintInbox(); return; }
      inbox = { pending: true, fileId: f.id, fileName: f.name, file };
      paintInbox();
    } catch (e) {
      inbox = null; paintInbox();
    } finally { inboxBusy = false; }
  }
  // 逐条核对：拿 Firebase 现在的数据，和清单里「Claude 版读取时 App 的样子」(base) 以及要写成的样子比
  async function inboxPlan(file) {
    const rows = [];
    for (let i = 0; i < file.changes.length; i++) {
      const ch = file.changes[i], text = (file.summary && file.summary[i]) || (ch.col + "/" + ch.id);
      const kind = ch.op === "delete" ? "del" : ch.base ? "mod" : "add";
      const row = { i, ch, text, kind, state: "ok", note: "" };
      if (!INBOX_COLLS.includes(ch.col) || !ID_OK.test(String(ch.id || "")) || (ch.op !== "set" && ch.op !== "delete") || (ch.op === "set" && (!ch.data || typeof ch.data !== "object" || Array.isArray(ch.data)))) { row.state = "bad"; row.note = "格式不对，跳过"; rows.push(row); continue; }
      let cur = null;
      try { cur = live(await fs.doc(ch.col + "/" + ch.id).get()); } catch (_) { cur = live(await fs.doc(ch.col + "/" + ch.id).get({ source: "cache" }).catch(() => null)); }
      row.before = cur;
      const target = ch.op === "delete" ? null : ch.data;
      if (same(cur, target)) { row.state = "same"; row.note = "App 里已经是这样了，跳过"; }
      else if (!same(cur, ch.base || null)) { row.state = "conf"; row.note = cur ? "这条在 Claude 版读取之后，App 里又改过" : "这条在 Claude 版读取之后，App 里被删掉了"; }
      rows.push(row);
    }
    return rows;
  }
  function dlg(html) {
    inboxCss();
    let d = document.getElementById("inbox-dlg");
    if (!d) { d = document.createElement("div"); d.id = "inbox-dlg"; document.body.appendChild(d); }
    d.innerHTML = '<div class="card" role="dialog" aria-modal="true">' + html + "</div>"; d.hidden = false;
    return d;
  }
  const closeDlg = () => { const d = document.getElementById("inbox-dlg"); if (d) d.hidden = true; };
  async function openInbox() {
    if (!inbox || !inbox.pending) return;
    const file = inbox.file;
    dlg("<h3>Claude 版发来的改动</h3><p>正在和 App 现在的数据逐条核对…</p>");
    let rows;
    try { rows = await inboxPlan(file); } catch (e) { dlg('<h3>Claude 版发来的改动</h3><p class="err">核对时读不到 App 的数据，请联网后再试。</p><div class="acts"><button class="btn" data-ib="close">关闭</button></div>'); return; }
    const okN = rows.filter((r) => r.state === "ok").length, conf = rows.filter((r) => r.state === "conf"), skip = rows.filter((r) => r.state === "same" || r.state === "bad").length;
    const word = { add: "新增", mod: "修改", del: "删除" };
    const list = rows.map((r) => '<li class="' + (r.state === "conf" ? "conf" : r.state !== "ok" ? "skip" : "") + '"><span class="k ' + r.kind + '">' + word[r.kind] + " " + (INBOX_LABEL[r.ch.col] || r.ch.col) + "</span>" + iesc(String(r.text).replace(/^[^：]*：/, "")) +
      (r.note ? "<small>" + iesc(r.note) + "</small>" : "") + (r.state === "conf" ? '<label><input type="checkbox" data-force="' + r.i + '">仍然用 Claude 版的（会覆盖 App 里的这条）</label>' : "") + "</li>").join("");
    dlg("<h3>Claude 版发来的改动</h3><p>Claude 版 " + iesc(ihhmm(file.created_at)) + " 发出，基于 App " + iesc(ihhmm(file.based_on && file.based_on.uploaded_at)) + " 的数据。可以写入 <b>" + okN + "</b> 条" +
      (conf.length ? "，<b style=\"color:var(--warn,#a8641a)\">" + conf.length + " 条有冲突</b>（默认保留 App 的）" : "") + (skip ? "，" + skip + " 条跳过" : "") + "。写入前会先备份，写完可以一键撤销。</p><ul>" + list + "</ul>" +
      '<p class="err" id="ib-err" hidden></p><div class="acts"><button class="btn ghost" data-ib="ignore">不要这份</button><button class="btn" data-ib="close">稍后</button><button class="btn primary" data-ib="apply" id="ib-apply">写入</button></div>');
    const btn = document.getElementById("ib-apply");
    const count = () => okN + document.querySelectorAll("#inbox-dlg [data-force]:checked").length;
    const label = () => { const n = count(); btn.textContent = n ? "确认写入 " + n + " 条" : "没有要写入的"; btn.disabled = !n; };
    label(); document.querySelectorAll("#inbox-dlg [data-force]").forEach((x) => x.addEventListener("change", label));
    inbox.rows = rows;
  }
  async function applyInbox() {
    const rows = inbox.rows || [], file = inbox.file, btn = document.getElementById("ib-apply");
    const forced = new Set(Array.from(document.querySelectorAll("#inbox-dlg [data-force]:checked")).map((x) => Number(x.dataset.force)));
    const todo = rows.filter((r) => r.state === "ok" || (r.state === "conf" && forced.has(r.i)));
    if (!todo.length) return;
    btn.disabled = true; btn.textContent = "写入中…";
    try {
      const undoId = String(file.id || inbox.fileId).replace(/[^A-Za-z0-9_\-]/g, "") || ("u" + Date.now());
      const now = new Date().toISOString(), me = window.__fbMyId || null;
      const undo = { at: now, file_id: inbox.fileId, file_name: inbox.fileName, change_id: file.id || null, by: me,
        items: todo.map((r) => ({ col: r.ch.col, id: r.ch.id, before: r.before == null ? null : r.before, after: r.ch.op === "delete" ? null : r.ch.data })) };
      if (JSON.stringify(undo).length > 900000) throw new Error("这份改动太大（超过 0.9MB），请让 Claude 分几次发");
      const ops = [];
      ops.push((b) => b.set(fs.doc("relay_undo/" + undoId), undo));
      for (const r of todo) {
        const ref = fs.doc(r.ch.col + "/" + r.ch.id);
        ops.push(r.ch.op === "delete" ? (b) => b.delete(ref) : (b) => b.set(ref, r.ch.data));
        if (r.ch.col !== "movements") ops.push((b) => b.set(fs.collection("log").doc("l-c-" + undoId + "-" + r.i), { at: now, by: me, op: { add: "新增", mod: "修改", del: "删除" }[r.kind], col: r.ch.col, ref: r.ch.id, text: String(r.text).replace(/^[^：]*：/, "") + "（Claude 版同步）" }));
      }
      ops.push((b) => b.set(fs.doc("meta/relay_applied"), { last_file_id: inbox.fileId, last_change_id: file.id || null, last_created_at: file.created_at || now, applied_at: now, applied: todo.length, skipped: rows.length - todo.length, undo_id: undoId, by: me }));
      for (let i = 0; i < ops.length; i += 450) { const b = fs.batch(); ops.slice(i, i + 450).forEach((f) => f(b)); await b.commit(); }
      inboxDone = { at: now, n: todo.length, undo: undoId };
      try { localStorage.setItem("fb-inbox-seen", inbox.fileId); } catch (_) {}
      try { localStorage.setItem("fb-inbox-done", JSON.stringify(inboxDone)); } catch (_) {}
      inbox = null; closeDlg(); paintInbox();
    } catch (e) {
      const er = document.getElementById("ib-err"); er.textContent = "写入失败：" + ((e && e.message) || e) + "。什么都没改，可以再试一次。"; er.hidden = false;
      btn.disabled = false; btn.textContent = "再试一次";
    }
  }
  async function ignoreInbox() {
    const now = new Date().toISOString();
    await fs.doc("meta/relay_applied").set({ last_file_id: inbox.fileId, last_change_id: inbox.file.id || null, last_created_at: inbox.file.created_at || now, applied_at: now, applied: 0, ignored: true, by: window.__fbMyId || null }).catch(() => {});
    try { localStorage.setItem("fb-inbox-seen", inbox.fileId); } catch (_) {}
    inbox = null; closeDlg(); paintInbox();
  }
  async function undoInbox() {
    if (!inboxDone) return;
    const s = await fs.doc("relay_undo/" + inboxDone.undo).get().catch(() => null);
    if (!s || !s.exists) { alert("找不到这次写入的备份，没法撤销。"); return; }
    const u = s.data(), items = u.items || [];
    let changedSince = 0;
    for (const it of items) { const c = await fs.doc(it.col + "/" + it.id).get().catch(() => null); if (!same(live(c), it.after)) changedSince++; }
    if (!confirm("撤销这次写入的 " + items.length + " 条改动，恢复成写入前的样子？" + (changedSince ? "\n\n注意：其中 " + changedSince + " 条在写入后又改过，撤销会把那些后来的改动也退回去。" : ""))) return;
    const ops = items.map((it) => { const ref = fs.doc(it.col + "/" + it.id); return it.before == null ? (b) => b.delete(ref) : (b) => b.set(ref, it.before); });
    const now = new Date().toISOString();
    ops.push((b) => b.set(fs.collection("log").doc("l-c-undo-" + inboxDone.undo), { at: now, by: window.__fbMyId || null, op: "撤销", col: "", ref: inboxDone.undo, text: "撤销了 Claude 版同步的 " + items.length + " 条改动" }));
    ops.push((b) => b.set(fs.doc("relay_undo/" + inboxDone.undo), { undone_at: now }, { merge: true }));
    for (let i = 0; i < ops.length; i += 450) { const b = fs.batch(); ops.slice(i, i + 450).forEach((f) => f(b)); await b.commit(); }
    inboxDone = null; try { localStorage.removeItem("fb-inbox-done"); } catch (_) {}
    paintInbox();
  }
  document.addEventListener("click", (e) => {
    const t = e.target && e.target.closest && e.target.closest("[data-ib]");
    if (!t) { if (e.target && e.target.id === "inbox-dlg") closeDlg(); return; }
    const a = t.dataset.ib;
    if (a === "open") openInbox();
    else if (a === "close") closeDlg();
    else if (a === "apply") applyInbox();
    else if (a === "ignore") { if (confirm("不要这份改动？以后不会再提示这份。")) ignoreInbox(); }
    else if (a === "undo") undoInbox().catch((x) => alert("撤销失败：" + ((x && x.message) || x)));
    else if (a === "ok") { inboxDone = null; try { localStorage.removeItem("fb-inbox-done"); } catch (_) {} paintInbox(); }
  });
  if (inboxDone) document.addEventListener("DOMContentLoaded", () => setTimeout(paintInbox, 500));
  window.__fbCheckInbox = checkInbox;
  // 流畅度：从后台切回 App 时马上查一次；App 开着时每 45 秒查一次（只是列一下文件夹，很轻）
  let inboxLast = 0;
  const inboxTick = (force) => { if (!relayOn() || document.visibilityState !== "visible") return; if (!force && Date.now() - inboxLast < 10000) return; inboxLast = Date.now(); checkInbox(); };
  document.addEventListener("visibilitychange", () => inboxTick(false));
  window.addEventListener("pageshow", () => inboxTick(false));
  setInterval(() => inboxTick(true), 45000);


  window.claude = {
    use: async (name) => {
      const u = await userReady;
      if (name === "db") { if (!window.__fbFirstSync) { window.__fbFirstSync = 1; trackWrite(Promise.resolve()); } syncUid = u.uid || ""; return dbApi; }
      if (name === "user") return await userNs(u);
      if (name === "downloads") return downloads;
      if (name === "mcp") return CFG.googleClientId ? mcp : null;
      return null; // assets（照片）：独立版暂不提供
    },
  };
  window.appSignOut = () => auth.signOut().then(() => location.reload());

  if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
})();

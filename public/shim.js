/* 转接层：让原来在 Claude 里运行的记账 App 不改业务代码，直接跑在 Firebase 上。
   App 调用 window.claude.use("db" | "user" | "downloads" ...)，这里用 Firebase 提供同样的接口。 */
(function () {
  const CFG = window.APP_CONFIG || {};
  firebase.initializeApp(window.FIREBASE_CONFIG);
  const auth = firebase.auth();
  const fs = firebase.firestore();
  // 和 Claude 数据库一致：值为 undefined 的字段直接忽略，而不是报错
  fs.settings({ ignoreUndefinedProperties: true, merge: true });
  // 离线可用：没网时照常记账，联网后自动同步
  fs.enablePersistence({ synchronizeTabs: true }).catch(() => {});

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
  auth.onAuthStateChanged((u) => {
    if (u) { if (box) box.hidden = true; resolveUser(u); }
    else if (document.body) showLogin();
    else document.addEventListener("DOMContentLoaded", () => showLogin());
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
  const hhmm = (d) => { d = new Date(d); return (d.getMonth() + 1) + "月" + d.getDate() + "日 " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
  function paintBadge() {
    if (!badge) {
      badge = document.createElement("div");
      badge.id = "sync-badge";
      badge.setAttribute("role", "status");
      badge.style.cssText = "position:fixed;z-index:40;top:calc(env(safe-area-inset-top,0px) + 6px);right:10px;font:600 12px/1.2 'Noto Sans SC',system-ui,sans-serif;padding:5px 10px;border-radius:999px;pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,.08)";
      document.body.appendChild(badge);
    }
    const off = !navigator.onLine;
    let t, bg, fg;
    if (pending > 0 && off) { t = "⚠ 没网：" + pending + " 笔待上传，联网后自动保存"; bg = "#fbeedd"; fg = "#a8641a"; }
    else if (pending > 0) { t = "⏳ 正在保存到云端…"; bg = "#ecebe7"; fg = "#4d5560"; }
    else if (off) { t = "⚠ 没网（记的账会先存在手机里）"; bg = "#fbeedd"; fg = "#a8641a"; }
    else { t = "✓ 已全部保存到云端" + (lastSaved ? " · " + hhmm(lastSaved) : ""); bg = "#e2efe9"; fg = "#2f6b5a"; }
    badge.textContent = t; badge.style.background = bg; badge.style.color = fg;
  }
  function trackWrite(p) {
    pending++; paintBadge();
    const done = () => fs.waitForPendingWrites().then(() => {
      pending = 0; lastSaved = new Date().toISOString();
      try { localStorage.setItem("fb-last-saved", lastSaved); } catch (_) {}
      paintBadge();
    });
    Promise.resolve(p).then(done, done);
    return p;
  }
  // 包住所有写入操作（App 原代码不用改）
  const DR = firebase.firestore.DocumentReference.prototype;
  for (const m of ["set", "update", "delete"]) { const orig = DR[m]; DR[m] = function (...a) { return trackWrite(orig.apply(this, a)); }; }
  const WB = firebase.firestore.WriteBatch.prototype, origCommit = WB.commit;
  WB.commit = function (...a) { return trackWrite(origCommit.apply(this, a)); };
  window.addEventListener("online", paintBadge);
  window.addEventListener("offline", paintBadge);

  /* ---------- mcp：备份到 Google Drive ---------- */
  // 原 App 调用 mcp.callTool("Google Drive", "create_file", {...})。这里用 Google 官方的网页授权（只申请
  // 「本应用创建的文件」权限 drive.file，看不到你 Drive 里的其他文件）直接上传。
  const DRIVE_FOLDER = "FB 记账备份";
  let token = null, tokenExp = 0, tokenWait = null, tokenClient = null;
  function gis() {
    if (tokenClient || !(window.google && google.accounts && google.accounts.oauth2) || !CFG.googleClientId) return tokenClient;
    tokenClient = google.accounts.oauth2.initTokenClient({
      client_id: CFG.googleClientId,
      scope: "https://www.googleapis.com/auth/drive.file",
      callback: () => {},
    });
    return tokenClient;
  }
  // 必须在「点按钮」的那一刻直接弹授权窗口，否则 iPhone 会拦截弹窗；所以在按钮上抢先监听点击
  function askToken() {
    if (token && Date.now() < tokenExp) return Promise.resolve(token);
    const tc = gis();
    if (!tc) return Promise.reject({ code: "tool_error", message: "Google 授权组件没加载出来，请检查网络后刷新" });
    tokenWait = new Promise((ok, bad) => {
      tc.callback = (r) => {
        if (r && r.access_token) { token = r.access_token; tokenExp = Date.now() + (Number(r.expires_in) || 3000) * 1000 - 60000; ok(token); }
        else bad({ code: "consent_required", message: (r && r.error) || "没有授权" });
      };
      tc.error_callback = (e) => bad({ code: "tool_error", message: e && e.type === "popup_failed_to_open" ? "授权窗口被拦截了。可以先用「导出 Excel」→ 分享 → Google Drive" : e && e.type === "popup_closed" ? "授权窗口被关掉了" : "Google 授权失败" });
      tc.requestAccessToken({ prompt: token ? "" : "consent" });
    });
    return tokenWait;
  }
  document.addEventListener("click", (e) => { if (e.target && e.target.closest && e.target.closest("#bk-btn")) askToken().catch(() => {}); }, true);
  async function gfetch(url, opt = {}) {
    const r = await fetch(url, Object.assign({}, opt, { headers: Object.assign({ Authorization: "Bearer " + token }, opt.headers || {}) }));
    if (r.status === 401) { token = null; throw { code: "tool_error", message: "Google 授权过期了，请再点一次备份" }; }
    if (!r.ok) throw { code: "tool_error", message: "Google Drive 返回 " + r.status };
    return r.json();
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

  window.claude = {
    use: async (name) => {
      const u = await userReady;
      if (name === "db") { if (!window.__fbFirstSync) { window.__fbFirstSync = 1; trackWrite(Promise.resolve()); } return fs; }
      if (name === "user") return await userNs(u);
      if (name === "downloads") return downloads;
      if (name === "mcp") return CFG.googleClientId ? mcp : null;
      return null; // assets（照片）：独立版暂不提供
    },
  };
  window.appSignOut = () => auth.signOut().then(() => location.reload());

  if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
})();

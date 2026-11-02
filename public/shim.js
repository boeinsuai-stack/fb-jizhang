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

  window.claude = {
    use: async (name) => {
      const u = await userReady;
      if (name === "db") return fs;
      if (name === "user") return await userNs(u);
      if (name === "downloads") return downloads;
      return null; // assets（照片）、mcp（Google Drive 备份）：独立版暂不提供
    },
  };
  window.appSignOut = () => auth.signOut().then(() => location.reload());

  if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
})();

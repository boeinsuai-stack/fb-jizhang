/* FB 记账镜像外壳（tools/build_mirror.py 把它放在 App 业务代码前面）。
   1) __M.use(name)：替代业务代码里的 window.claude.use。db 给只读的一层（读照常，写一律拒绝并提示）；user 照给；
      mcp / assets / downloads 给 null（备份、上传、导出只在手机 App 里做）
   2) 同步：店主打开时从 Google Drive「FB 记账中转站/最新数据.json」读 App 最新上传的数据，只把变了的记录写进镜像的数据库
      （业务代码订阅着这些集合，写进去界面就跟着变）。开着时每 30 秒、切回页面时再查；文件没变就不下载。
      指纹存 meta/fp_<集合>，跟最早的「数据镜像」页同一套，已有的数据不用重写。 */
(() => {
  "use strict";
  const COLS = ["items", "orders", "movements", "expenses", "purchases", "transfers", "settlements", "customers", "followups", "log"];
  const NAMES = { items: "口味", orders: "订单", movements: "库存流水", expenses: "支出", purchases: "订货", transfers: "合伙人往来", settlements: "结账", customers: "客户", followups: "跟进", log: "操作记录" };
  const RO_MSG = "镜像只读：要改请在手机 App 里改，或者跟 Claude 说";
  const real = { db: null, user: null, mcp: null };
  const ready = (window.claude && window.claude.use)
    ? Promise.all(["db", "user", "mcp"].map((n) => window.claude.use(n).catch(() => null))).then(([d, u, m]) => { real.db = d; real.user = u; real.mcp = m; })
    : Promise.resolve();

  /* ---------- 状态条 ---------- */
  const $ = (id) => document.getElementById(id);
  const fmt = (iso) => { const d = new Date(iso); return isNaN(d) ? "—" : (d.getMonth() + 1) + "月" + d.getDate() + "日 " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
  let barState = ["busy", "正在连接…"], goVisible = false, flashTimer = 0;
  function paint() {
    const b = $("mirror-bar"); if (!b) return;
    b.dataset.s = barState[0]; $("mb-text").textContent = barState[1]; $("mb-go").hidden = !goVisible;
  }
  function show(s, text, go) { barState = [s, text]; goVisible = !!go; if (!flashTimer) paint(); }
  function asof(m) {
    if (!m) return "";
    const lr = m.last_record;
    return "App 数据截至 " + fmt(m.uploaded_at) + (lr ? " · 最后一笔：" + (lr.text || lr.id) : "");
  }
  let lastGesture = 0;
  for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, () => { lastGesture = Date.now(); }, true);
  function roNotice() {
    if (Date.now() - lastGesture > 3000) return; // 后台自动写入（如补操作记录）被拒不打扰
    const b = $("mirror-bar"); if (!b) return;
    clearTimeout(flashTimer); b.classList.add("flash"); b.dataset.s = "warn"; $("mb-text").textContent = RO_MSG;
    flashTimer = setTimeout(() => { flashTimer = 0; b.classList.remove("flash"); paint(); }, 4000);
  }

  /* ---------- 只读数据库 ---------- */
  const roReject = () => { roNotice(); const e = new Error(RO_MSG); e.code = "read_only"; e.userMsg = RO_MSG; return Promise.reject(e); };
  const wrapDoc = (d) => ({ id: d.id, path: d.path, get: (...a) => d.get(...a), onSnapshot: (...a) => d.onSnapshot(...a), set: roReject, update: roReject, delete: roReject });
  const wrapQ = (q) => ({
    where: (...a) => wrapQ(q.where(...a)), orderBy: (...a) => wrapQ(q.orderBy(...a)), limit: (...a) => wrapQ(q.limit(...a)),
    get: (...a) => q.get(...a), onSnapshot: (...a) => q.onSnapshot(...a), doc: (id) => wrapDoc(q.doc(id)),
  });
  const roDb = () => real.db && {
    doc: (p) => wrapDoc(real.db.doc(p)), collection: (c) => wrapQ(real.db.collection(c)),
    batch: () => { const b = { set: () => b, update: () => b, delete: () => b, commit: roReject }; return b; },
  };
  window.__M = { use: async (name) => { await ready; return name === "db" ? roDb() : name === "user" ? real.user : null; } };

  /* ---------- 同步 ---------- */
  function stable(v) {
    if (v === null || typeof v !== "object") return JSON.stringify(v === undefined ? null : v);
    if (Array.isArray(v)) return "[" + v.map(stable).join(",") + "]";
    return "{" + Object.keys(v).filter((k) => v[k] !== undefined).sort().map((k) => JSON.stringify(k) + ":" + stable(v[k])).join(",") + "}";
  }
  function fp(v) {
    const s = stable(v); let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i); h1 = Math.imul(h1 ^ c, 2654435761); h2 = Math.imul(h2 ^ c, 1597334677); }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
  }
  function mcpMsg(e) {
    switch (e && e.code) {
      case "not_in_manifest": case "consent_required": case "approval_required": case "not_granted": return "还没获得读取 Google Drive 的许可，点「重新读取」并允许";
      case "needs_reauth": return "Google Drive 连接过期了，请在 claude.ai 设置 → Connectors 重新连接";
      case "server_not_connected": case "selection_required": case "server_not_found": return "Google Drive 连接器没连上，请在 claude.ai 设置 → Connectors 添加";
      case "rate_limited": case "server_unavailable": case "upstream_error": return "Google Drive 暂时没响应，稍后会自动再试";
    }
    return (e && e.userMsg) || "读取失败（" + ((e && (e.code || e.message)) || e) + "）";
  }
  async function put(op, path, data) {
    const ref = real.db.doc(path);
    for (let i = 0; ; i++) {
      try { return op === "set" ? await ref.set(data) : await ref.delete(); }
      catch (e) {
        if (i < 3 && e && (e.code === "unavailable" || e.code === "resource_exhausted")) { await new Promise((r) => setTimeout(r, 600 * (i + 1) + Math.random() * 400)); continue; }
        throw e;
      }
    }
  }

  let busy = false, meta = null, lastRun = 0;
  async function sync(opts) {
    opts = opts || {};
    if (busy || !real.db || !real.mcp) return;
    busy = true; lastRun = Date.now();
    try {
      if (!meta) { const s = await real.db.doc("meta/mirror").get(); meta = s.exists ? s.data() : null; }
      if (opts.loud || !meta) show("busy", meta ? asof(meta) + " · 正在检查…" : "正在从中转站读取…");
      const sr = await real.mcp.callTool("Google Drive", "search_files", { query: "title = '最新数据.json'", excludeContentSnippets: true, pageSize: 10 }, { cache: false });
      const files = ((sr && sr.payload && sr.payload.files) || []).filter((f) => f.title === "最新数据.json" && /json/.test(f.mimeType || "")).sort((a, b) => (a.modifiedTime < b.modifiedTime ? 1 : -1));
      if (!files.length) { show("warn", "Google Drive 里还没有中转站文件。在 App 里记一笔，或点 App 右上角「中转站待更新」", true); return; }
      const f = files[0];
      if (!opts.force && meta && meta.file_id === f.id && meta.file_modified === f.modifiedTime) { show("ok", asof(meta), true); return; }

      show("busy", (meta ? asof(meta) + " · " : "") + "App 有新数据，正在下载…");
      const dr = await real.mcp.callTool("Google Drive", "download_file_content", { fileId: f.id }, { cache: false });
      const b64 = dr && dr.payload && dr.payload.content;
      if (!b64) throw { userMsg: "中转站文件下载下来是空的" };
      const relay = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))));
      if (!relay || relay.format !== "fb-jizhang-relay/1" || !relay.data) throw { userMsg: "中转站文件格式不对，没有更新" };
      for (const c of COLS) if (relay.counts && relay.counts[c] != null && relay.data[c] && Object.keys(relay.data[c]).length !== relay.counts[c]) throw { userMsg: "中转站文件不完整（" + NAMES[c] + "条数对不上），没有更新" };
      if (!opts.force && meta && meta.uploaded_at && relay.uploaded_at < meta.uploaded_at) { show("warn", "中转站里的数据（" + fmt(relay.uploaded_at) + "）比镜像里的还旧，没有更新", true); return; }
      // 防呆：条数突然少很多，多半是手机缓存不全，先停下
      if (!opts.force && meta && meta.counts) for (const c of ["orders", "movements", "items"]) {
        const had = meta.counts[c] || 0, now = Object.keys(relay.data[c] || {}).length;
        if (had >= 10 && now < had * 0.8) { show("warn", "中转站里的" + NAMES[c] + "只有 " + now + " 条（镜像里 " + had + " 条），看起来不完整，先没更新", true); return; }
      }
      const plan = [], fps = {};
      for (const c of COLS) {
        if (!relay.data[c]) { fps[c] = null; continue; } // 文件里没有这一类：不动
        const R = relay.data[c], s = await real.db.doc("meta/fp_" + c).get(), old = (s.exists && s.data().fp) || {};
        fps[c] = {};
        for (const [id, x] of Object.entries(R)) { const h = fp(x); fps[c][id] = h; if (old[id] !== h) plan.push(["set", c + "/" + id, x]); }
        for (const id of Object.keys(old)) if (!R[id]) plan.push(["del", c + "/" + id]);
      }
      let failed = 0;
      for (let i = 0; i < plan.length; i += 6) {
        if (plan.length > 12) show("busy", "正在更新 " + Math.min(i + 6, plan.length) + " / " + plan.length + " 条…");
        const res = await Promise.allSettled(plan.slice(i, i + 6).map((w) => put(w[0], w[1], w[2])));
        res.forEach((r, k) => { if (r.status === "rejected") { failed++; const p = plan[i + k][1], j = p.indexOf("/"); delete fps[p.slice(0, j)][p.slice(j + 1)]; } });
      }
      /* 见面地点（meta/places）：meta 别的都不抄，只抄这一份 */
      const mpl = relay.data.meta && relay.data.meta.places;
      if (mpl && fp(mpl) !== (meta && meta.places_fp)) { await put("set", "meta/places", mpl).catch(() => { failed++; }); }
      /* 跟合伙人的价格（meta/pprice，2026-11-24）：对账单「价格」，也抄 */
      const mpp = relay.data.meta && relay.data.meta.pprice;
      if (mpp && fp(mpp) !== (meta && meta.pprice_fp)) { await put("set", "meta/pprice", mpp).catch(() => { failed++; }); }
      for (const c of COLS) if (fps[c]) await put("set", "meta/fp_" + c, { fp: fps[c] });
      const counts = {}; for (const c of COLS) if (relay.data[c]) counts[c] = Object.keys(relay.data[c]).length;
      meta = { file_id: f.id, file_modified: f.modifiedTime, uploaded_at: relay.uploaded_at || null, last_record: relay.last_record || null, counts, places_fp: mpl ? fp(mpl) : null, pprice_fp: mpp ? fp(mpp) : null, mirrored_at: new Date().toISOString(), result: { written: plan.length - failed, failed } };
      await put("set", "meta/mirror", meta);
      if (failed) show("warn", failed + " 条没写进去，点「重新读取」补上", true);
      else show("ok", asof(meta) + (plan.length ? " · 刚更新 " + plan.length + " 条" : ""), true);
    } catch (e) {
      show("warn", mcpMsg(e), true);
    } finally { busy = false; }
  }

  ready.then(async () => {
    const go = () => { const b = $("mb-go"); if (b) b.onclick = () => sync({ loud: true, force: true }); paint(); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go); else go();
    if (!real.db) { show("warn", "在 claude.ai 里登录后打开才能看到数据"); return; }
    // App 的「补操作记录」只需要做一次；镜像只读，标记成已做，免得它每次打开都试着写
    try { const b = await real.db.doc("meta/backfill").get(); if (!b.exists) await put("set", "meta/backfill", { done: true, by: "mirror" }); } catch (_) {}
    let owner = false; try { owner = real.user ? await real.user.isOwner() : false; } catch (_) {}
    if (!owner || !real.mcp) {
      try { const s = await real.db.doc("meta/mirror").get(); meta = s.exists ? s.data() : null; } catch (_) {}
      show("ok", asof(meta) + (owner ? " · Google Drive 连接器用不了，显示的是上次的数据" : " · 店主打开时才会更新"));
      return;
    }
    sync({ loud: true });
    setInterval(() => { if (document.visibilityState === "visible") sync(); }, 30000);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && Date.now() - lastRun > 10000) sync(); });
  });
})();

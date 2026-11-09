/* 测试用的假 Firebase（compat 接口，只实现 App 用到的部分）。分两层，照真 Firestore 的行为：
   - 云端（server）：所有手机共用的那份。写入时把 serverTimestamp 换成云端时间。
   - 手机本地数据库（cache）：本地写入马上进来；云端的记录只有被某个「云端监听」查到时才拷进来。
   - 监听 onSnapshot({source:"cache"}) 只看本地；普通监听在有网时问云端（按条计费：第一次 = 结果条数，之后 = 变化的条数），
     没网时看本地（fromCache: true）。
   - 写入：没网时（__MOCK_OFFLINE）promise 永远不完成、不进云端；有网时 40ms 后进云端。
   页面里可用：__dump(c) 本地数据（含内部字段）、__server(c) 云端数据、__reads 计费读取次数、
   __remoteWrite(c, id, data|null) 模拟另一台手机写/删、__dumpCache() 导出本地数据库给下一次打开用（__CACHE_SEED）。 */
(function () {
  const OFFLINE = !!window.__MOCK_OFFLINE;
  const copy = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
  class Timestamp {
    constructor(ms) { this.ms = ms; this.seconds = Math.floor(ms / 1000); this.nanoseconds = (ms % 1000) * 1e6; }
    toMillis() { return this.ms; } toDate() { return new Date(this.ms); }
    static fromMillis(ms) { return new Timestamp(ms); } static now() { return new Timestamp(Date.now()); }
    toJSON() { return { __ts: this.ms }; }
  }
  const SV = { serverTimestamp: { __sv: "ts" }, del: { __sv: "del" } };
  const FieldValue = { serverTimestamp: () => SV.serverTimestamp, delete: () => SV.del };
  class FieldPath { constructor(...p) { this.p = p; } }
  const isTs = (v) => v && typeof v === "object" && "__ts" in v;
  const isPend = (v) => v && typeof v === "object" && v.__pending;

  // 两层数据：{ c: Map(id -> { d: 数据, v: 版本, pend: 本地没上传 }) }
  const server = {}, cache = {};
  const col = (L, c) => L[c] || (L[c] = new Map());
  let ver = 0;
  const seedInto = (L, seed, ts) => { for (const [c, docs] of Object.entries(seed || {})) for (const [id, x] of Object.entries(docs)) { const d = copy(x); if (ts && !d._u) d._u = { __ts: ts }; col(L, c).set(id, { d, v: ++ver }); } };
  // __MOCK_PERSIST：页面刷新后数据还在（存在 sessionStorage），用来测「迁移后自动刷新」
  const saved = window.__MOCK_PERSIST ? (() => { try { return JSON.parse(sessionStorage.getItem("__mockfb") || "null"); } catch (_) { return null; } })() : null;
  if (saved) { for (const [c, docs] of Object.entries(saved.server)) for (const [id, r] of Object.entries(docs)) col(server, c).set(id, r); for (const [c, docs] of Object.entries(saved.cache)) for (const [id, r] of Object.entries(docs)) col(cache, c).set(id, r); ver = saved.ver; }
  else {
    seedInto(server, window.__SEED, null);
    if (window.__CACHE_SEED) seedInto(cache, window.__CACHE_SEED, null); else seedInto(cache, window.__SEED, null);
  }
  const persist = () => { if (!window.__MOCK_PERSIST) return; const dump = (L) => Object.fromEntries(Object.entries(L).map(([c, m]) => [c, Object.fromEntries(m)])); try { sessionStorage.setItem("__mockfb", JSON.stringify({ server: dump(server), cache: dump(cache), ver })); } catch (_) {} };
  window.__reads = 0; window.__writes = 0;
  window.__dump = (c) => { const o = {}; for (const [id, r] of col(cache, c)) o[id] = r.d; return o; };
  window.__server = (c) => { const o = {}; for (const [id, r] of col(server, c)) o[id] = r.d; return o; };
  window.__dumpCache = () => { const o = {}; for (const [c, m] of Object.entries(cache)) { o[c] = {}; for (const [id, r] of m) o[c][id] = r.d; } return o; };
  window.__store = cache;

  // 把写入内容（含 serverTimestamp / delete）合到旧数据上
  function merge(base, d, now) {
    const out = Object.assign({}, base || {});
    for (const [k, v] of Object.entries(d)) {
      if (v === undefined) continue;
      if (v === SV.del) delete out[k];
      else if (v === SV.serverTimestamp) out[k] = now == null ? { __pending: true } : { __ts: now };
      else out[k] = copy(v);
    }
    return out;
  }
  // 写入：先进本地，有网时再进云端
  function write(path, kind, d, opt) {
    const [c, id] = path.split("/"); const L = col(cache, c), cur = L.get(id);
    window.__writes++;
    let nd;
    if (kind === "delete") nd = null;
    else if (kind === "update") { if (!cur) throw new Error("no doc " + path); nd = merge(cur.d, d, null); }
    else nd = merge(opt && opt.merge && cur ? cur.d : {}, d, null);
    if (nd) L.set(id, { d: nd, v: ++ver, pend: true }); else L.delete(id);
    return () => { // 云端收下
      const S = col(server, c), sc = S.get(id), now = Date.now();
      let sd;
      if (kind === "delete") sd = null;
      else if (kind === "update") { if (!sc) return; sd = merge(sc.d, d, now); }
      else sd = merge(opt && opt.merge && sc ? sc.d : {}, d, now);
      if (sd) S.set(id, { d: sd, v: ++ver }); else S.delete(id);
      if (sd) L.set(id, { d: copy(sd), v: ver }); else if (!L.get(id) || !L.get(id).pend) L.delete(id);
    };
  }
  window.__remoteWrite = (c, id, d) => { // 另一台手机写入（已在云端）
    const S = col(server, c), now = Date.now();
    if (d === null) S.delete(id); else S.set(id, { d: Object.assign(copy(d), { _u: { __ts: now } }), v: ++ver });
    notify();
  };

  // 查询
  const val = (d, f) => d[f];
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const num = (v) => (isTs(v) ? v.__ts : v instanceof Timestamp ? v.ms : v);
  function run(L, q) {
    let rows = [...col(L, q.c).entries()];
    for (const [f, op, v] of q.where) rows = rows.filter(([, r]) => { const x = val(r.d, f); if (x == null || isPend(x)) return false; const a = num(x), b = num(v); return op === ">" ? a > b : op === ">=" ? a >= b : op === "==" ? a === b : op === "<" ? a < b : true; });
    rows.sort((a, b) => cmp(a[0], b[0]));
    if (q.order) { const [f, dir] = q.order; rows.sort((a, b) => cmp(num(val(a[1].d, f)) ?? "", num(val(b[1].d, f)) ?? "") * (dir === "desc" ? -1 : 1)); }
    if (q.lim) rows = rows.slice(0, q.lim);
    return rows;
  }
  function docSnap(id, r, c) {
    const data = (o) => { if (!r) return undefined; const x = copy(r.d); for (const k of Object.keys(x)) { if (isTs(x[k])) x[k] = new Timestamp(x[k].__ts); else if (isPend(x[k])) x[k] = o && o.serverTimestamps === "estimate" ? Timestamp.now() : null; } return x; };
    return { id, exists: !!r, ref: new DocumentReference(c + "/" + id), metadata: { hasPendingWrites: !!(r && r.pend), fromCache: false }, data, get: (f) => { const x = data(); return x ? x[f] : undefined; } };
  }
  const listeners = [];
  function deliver(l) {
    const online = !OFFLINE && !l.cacheOnly;
    if (l.doc) { const [c, id] = l.doc.split("/"); const r = col(online ? server : cache, c).get(id); l.cb(docSnap(id, r, c)); return; }
    let rows;
    if (online) {
      rows = run(server, l.q);
      // 云端结果拷进本地数据库；按条计费
      const L = col(cache, l.q.c);
      for (const [id, r] of rows) { if (l.seen.get(id) !== r.v) { window.__reads++; l.seen.set(id, r.v); } const cur = L.get(id); if (!cur || !cur.pend) L.set(id, { d: copy(r.d), v: r.v }); }
      const ids = new Set(rows.map((r) => r[0])); for (const id of [...l.seen.keys()]) if (!ids.has(id)) l.seen.delete(id);
      rows = run(cache, l.q); // 本地视图（含自己还没上传的写入）
    } else rows = run(cache, l.q);
    const key = rows.map(([id, r]) => id + ":" + r.v).join("|") + "|" + online;
    if (key === l.last) return; l.last = key;
    const docs = rows.map(([id, r]) => docSnap(id, r, l.q.c));
    l.cb({ docs, size: docs.length, empty: !docs.length, metadata: { hasPendingWrites: docs.some((d) => d.metadata.hasPendingWrites), fromCache: !online }, forEach: (f) => docs.forEach(f) });
  }
  let queued = false;
  function notify() { if (queued) return; queued = true; setTimeout(() => { queued = false; persist(); listeners.filter((l) => !l.off && !l.cacheOnly).forEach(deliver); listeners.filter((l) => !l.off && l.cacheOnly).forEach(deliver); }, 0); }
  const ack = (commit) => (OFFLINE ? new Promise(() => {}) : new Promise((r) => setTimeout(() => { commit(); notify(); r(); }, 40)));
  function subscribe(spec, a) {
    let opts = {}; if (a[0] && typeof a[0] === "object" && !a[0].next) opts = a.shift();
    const cb = a[0], err = a[1];
    const l = Object.assign({ cb, err, seen: new Map(), cacheOnly: opts.source === "cache" }, spec);
    listeners.push(l); setTimeout(() => !l.off && deliver(l), 0);
    return () => { l.off = true; };
  }

  class DocumentReference {
    constructor(path) { this.path = path; const [c, id] = path.split("/"); this.id = id; this.parent = { id: c, parent: null }; }
    set(d, opt) { const commit = write(this.path, "set", d, opt); notify(); return ack(commit); }
    update(d, ...rest) { if (typeof d === "string") { const o = {}; o[d] = rest[0]; for (let i = 1; i + 1 < rest.length; i += 2) o[rest[i]] = rest[i + 1]; d = o; } const commit = write(this.path, "update", d); notify(); return ack(commit); }
    delete() { const commit = write(this.path, "delete"); notify(); return ack(commit); }
    get(o) { const [c, id] = this.path.split("/"); const useCache = OFFLINE || (o && o.source === "cache"); const r = col(useCache ? cache : server, c).get(id); if (!useCache && r) window.__reads++; return Promise.resolve(docSnap(id, r, c)); }
    onSnapshot(...a) { return subscribe({ doc: this.path }, a); }
  }
  class WriteBatch {
    constructor() { this.ops = []; }
    set(r, d, o) { this.ops.push([r.path, "set", d, o]); return this; }
    update(r, d) { this.ops.push([r.path, "update", d]); return this; }
    delete(r) { this.ops.push([r.path, "delete"]); return this; }
    commit() { const cs = this.ops.map((o) => write(...o)); notify(); return ack(() => cs.forEach((f) => f())); }
  }
  function query(c, q) {
    return {
      limit: (n) => query(c, Object.assign({}, q, { lim: n })),
      orderBy: (f, dir) => query(c, Object.assign({}, q, { order: [f, dir || "asc"] })),
      where: (f, op, v) => query(c, Object.assign({}, q, { where: q.where.concat([[f, op, v]]) })),
      onSnapshot: (...a) => subscribe({ q: Object.assign({ c }, q) }, a),
      get: (o) => { const useCache = OFFLINE || (o && o.source === "cache"); const rows = run(useCache ? cache : server, Object.assign({ c }, q)); if (!useCache) window.__reads += rows.length; const docs = rows.map(([id, r]) => docSnap(id, r, c)); return Promise.resolve({ docs, size: docs.length, empty: !docs.length, metadata: { fromCache: useCache } }); },
      doc: (id) => new DocumentReference(c + "/" + (id || "auto" + Math.random().toString(36).slice(2))),
    };
  }
  const fs = {
    settings() {}, enablePersistence: () => (window.__NO_PERSIST ? Promise.reject(new Error("no persistence")) : Promise.resolve()),
    collection: (c) => query(c, { where: [] }),
    doc: (p) => new DocumentReference(p),
    batch: () => new WriteBatch(),
    waitForPendingWrites: () => (OFFLINE ? new Promise(() => {}) : new Promise((r) => setTimeout(r, 60))),
  };
  const USER = { uid: "u-test", email: "test@example.com", displayName: "测试" };
  const auth = {
    currentUser: null,
    onAuthStateChanged(cb) { if (!window.__AUTH_NEVER) setTimeout(() => { auth.currentUser = USER; cb(USER); }, window.__AUTH_DELAY || 0); },
    signInWithEmailAndPassword: () => Promise.resolve(), signOut: () => Promise.resolve(),
  };
  const firestore = () => fs;
  Object.assign(firestore, { DocumentReference, WriteBatch, FieldValue, FieldPath, Timestamp, CACHE_SIZE_UNLIMITED: -1 });
  window.firebase = { initializeApp() {}, auth: () => auth, firestore };
})();

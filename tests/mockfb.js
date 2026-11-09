/* 测试用的假 Firebase（compat 接口，只实现 App 用到的部分）。
   行为照真 Firestore 离线时：写入马上进本地、页面收到更新，但 set/update/delete 的 promise
   要等云端确认——window.__MOCK_OFFLINE 为 true 时永远不确认（=没网）。 */
(function () {
  const OFFLINE = !!window.__MOCK_OFFLINE;
  const store = {}, listeners = [];
  const col = (c) => store[c] || (store[c] = new Map());
  const copy = (x) => JSON.parse(JSON.stringify(x));
  const clean = (d) => JSON.parse(JSON.stringify(d)); // 去掉 undefined，跟 ignoreUndefinedProperties 一样
  for (const [c, docs] of Object.entries(window.__SEED || {})) for (const [id, x] of Object.entries(docs)) col(c).set(id, copy(x));
  window.__store = store;
  window.__dump = (c) => Object.fromEntries(col(c));
  const docSnap = (path) => { const [c, id] = path.split("/"); const x = col(c).get(id); return { id, exists: !!x, data: () => (x ? copy(x) : undefined) }; };
  const colSnap = (c, q) => {
    let docs = [...col(c).entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1));
    if (q && q.order) { const [f, dir] = q.order; docs.sort((a, b) => ((a[1][f] || "") < (b[1][f] || "") ? -1 : 1) * (dir === "desc" ? -1 : 1)); }
    if (q && q.lim) docs = docs.slice(0, q.lim);
    docs = docs.map(([id, x]) => ({ id, exists: true, data: () => copy(x) }));
    return { docs, size: docs.length, empty: !docs.length, metadata: { hasPendingWrites: false, fromCache: OFFLINE } };
  };
  const fire = (l) => (l.c ? l.cb(colSnap(l.c, l.q)) : l.cb(docSnap(l.path)));
  const notify = () => setTimeout(() => listeners.forEach(fire), 0);
  const ack = () => (OFFLINE ? new Promise(() => {}) : new Promise((r) => setTimeout(r, 40)));
  window.__writes = 0;
  const apply = (path, kind, d, opt) => {
    const [c, id] = path.split("/"); const cur = col(c).get(id);
    window.__writes++;
    if (kind === "delete") col(c).delete(id);
    else if (kind === "update") { if (!cur) throw new Error("no doc " + path); col(c).set(id, Object.assign({}, cur, clean(d))); }
    else col(c).set(id, opt && opt.merge ? Object.assign({}, cur, clean(d)) : clean(d));
  };
  class DocumentReference {
    constructor(path) { this.path = path; this.id = path.split("/")[1]; }
    set(d, opt) { apply(this.path, "set", d, opt); notify(); return ack(); }
    update(d) { apply(this.path, "update", d); notify(); return ack(); }
    delete() { apply(this.path, "delete"); notify(); return ack(); }
    get() { return Promise.resolve(docSnap(this.path)); }
    onSnapshot(cb) { const l = { path: this.path, cb }; listeners.push(l); setTimeout(() => fire(l), 0); return () => {}; }
  }
  class WriteBatch {
    constructor() { this.ops = []; }
    set(r, d, o) { this.ops.push([r.path, "set", d, o]); return this; }
    update(r, d) { this.ops.push([r.path, "update", d]); return this; }
    delete(r) { this.ops.push([r.path, "delete"]); return this; }
    commit() { this.ops.forEach((o) => apply(...o)); notify(); return ack(); }
  }
  const query = (c, q) => ({
    limit: (n) => query(c, Object.assign({}, q, { lim: n })),
    orderBy: (f, dir) => query(c, Object.assign({}, q, { order: [f, dir] })),
    onSnapshot: (cb) => { const l = { c, q, cb }; listeners.push(l); setTimeout(() => fire(l), 0); return () => {}; },
    get: () => Promise.resolve(colSnap(c, q)),
    doc: (id) => new DocumentReference(c + "/" + (id || "auto" + Math.random().toString(36).slice(2))),
  });
  const fs = {
    settings() {}, enablePersistence: () => Promise.resolve(),
    collection: (c) => query(c, {}),
    doc: (p) => new DocumentReference(p),
    batch: () => new WriteBatch(),
    waitForPendingWrites: () => ack(),
  };
  const USER = { uid: "u-test", email: "test@example.com", displayName: "测试" };
  const auth = {
    currentUser: null,
    onAuthStateChanged(cb) { if (!window.__AUTH_NEVER) setTimeout(() => { auth.currentUser = USER; cb(USER); }, window.__AUTH_DELAY || 0); },
    signInWithEmailAndPassword: () => Promise.resolve(), signOut: () => Promise.resolve(),
  };
  const firestore = () => fs; firestore.DocumentReference = DocumentReference; firestore.WriteBatch = WriteBatch;
  window.firebase = { initializeApp() {}, auth: () => auth, firestore };
})();

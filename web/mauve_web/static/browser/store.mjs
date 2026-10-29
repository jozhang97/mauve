const request = r => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
export class Store {
  async open() {
    const r = indexedDB.open('mauve-browser-v1', 1);
    r.onupgradeneeded = () => {
      for (const name of ['alignments', 'blocks', 'members', 'annotations', 'inputs', 'jobs', 'artifacts']) r.result.createObjectStore(name);
    };
    this.db = await request(r); this.db.onversionchange = () => this.db.close(); return this;
  }
  async get(store, key) { return request(this.db.transaction(store).objectStore(store).get(key)); }
  async all(store, range) { return request(this.db.transaction(store).objectStore(store).getAll(range)); }
  async put(store, key, value) { return this.batch([[store, key, value]]); }
  async batch(rows) {
    const tx = this.db.transaction([...new Set(rows.map(r => r[0]))], 'readwrite');
    const done = new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = tx.onabort = () => reject(tx.error || Error('Storage transaction aborted.')); });
    for (const [store, key, value] of rows) tx.objectStore(store).put(value, key);
    return done;
  }
  async deleteAlignment(id) {
    const tx = this.db.transaction(['alignments', 'blocks', 'members', 'annotations'], 'readwrite');
    const done = new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); });
    tx.objectStore('alignments').delete(id);
    for (const name of ['blocks', 'members', 'annotations']) tx.objectStore(name).delete(this.range(id));
    return done;
  }
  range(id) { return IDBKeyRange.bound([id], [id, []]); }
}
export class MemberCache {
  constructor(store, limit = 64 * 1024 * 1024) { this.store = store; this.limit = limit; this.bytes = 0; this.items = new Map(); }
  async get(aid, bid, gid) {
    const key = `${aid}/${bid}/${gid}`;
    if (this.items.has(key)) { const m = this.items.get(key); this.items.delete(key); this.items.set(key, m); return m; }
    const m = await this.store.get('members', [aid, bid, gid]);
    if (!m) throw Error('Block member not found.');
    const size = m.sequence.byteLength + m.prefix.byteLength;
    if (size <= this.limit) {
      while (this.bytes + size > this.limit && this.items.size) {
        const [old, value] = this.items.entries().next().value; this.items.delete(old); this.bytes -= value.sequence.byteLength + value.prefix.byteLength;
      }
      this.items.set(key, m); this.bytes += size;
    }
    return m;
  }
}

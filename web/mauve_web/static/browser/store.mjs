import {STRIDE, columnSlice, consumed, indexMember, metadata} from './core.mjs';
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
  constructor(store, limit = 64 * 1024 * 1024, windowLimit = 4 * 1024 * 1024) {
    this.store = store; this.limit = limit; this.bytes = 0; this.items = new Map(); this.pending = new Map();
    this.windowLimit = windowLimit; this.windowBytes = 0; this.windows = new Map();
  }
  async get(aid, bid, gid, retained) {
    const key = `${aid}/${bid}/${gid}`;
    if (this.items.has(key)) { const m = this.items.get(key); this.items.delete(key); this.items.set(key, m); return m; }
    if (this.pending.has(key)) return this.pending.get(key);
    const load = this.load(key, [aid, bid, gid], retained);
    this.pending.set(key, load);
    try { return await load; }
    finally { if (this.pending.get(key) === load) this.pending.delete(key); }
  }
  async load(key, address, retained) {
    const m = await this.store.get('members', address);
    if (!m) throw Error('Block member not found.');
    const size = m.sequence.byteLength + m.prefix.byteLength;
    if (size <= this.limit) {
      if (this.bytes + size > this.limit) for (const [old, value] of this.items) {
        if (retained?.has(old)) continue;
        this.items.delete(old); this.bytes -= value.sequence.byteLength + value.prefix.byteLength;
        if (this.bytes + size <= this.limit) break;
      }
      if (this.bytes + size <= this.limit) { this.items.set(key, m); this.bytes += size; }
    }
    return m;
  }
  async *pages(aid, bid, gids, offset, limit, columns) {
    const workingSet = gids.length * (columns + (Math.floor(columns / STRIDE) + 1) * 4);
    if (workingSet <= this.limit || this.windowLimit === 0) {
      for await (const member of this.scan(aid, bid, gids)) yield columnSlice(member, offset, limit);
      return;
    }
    const retained = new Set(gids.map(gid => `${aid}/${bid}/${gid}`).filter(key => this.items.has(key)));
    const start = Math.floor(offset / 8192) * 8192, end = Math.min(columns, offset + limit);
    for (const gid of gids) {
      const key = `${aid}/${bid}/${gid}/${start}`;
      let window = this.windows.get(key);
      if (!window || window.member.sequence.length + start < end) {
        const member = await this.get(aid, bid, gid, retained);
        // Another page may have filled or evicted this window while we waited.
        window = this.windows.get(key);
        if (!window || window.member.sequence.length + start < end) {
          const before = consumed(member, start), original = metadata(member);
          // Copy the window: a subarray would retain the entire large buffer.
          const sequence = member.sequence.slice(start, Math.max(start + 8192, end));
          const partial = indexMember({...original, sequence,
            start: member.strand === '+' ? member.start + before : member.start,
            end: member.strand === '-' ? member.end - before : member.end});
          if (window) {
            this.windows.delete(key); this.windowBytes -= window.bytes;
          }
          window = {member: partial, original, bytes: sequence.byteLength + partial.prefix.byteLength};
          if (window.bytes <= this.windowLimit) {
            while (this.windowBytes + window.bytes > this.windowLimit) {
              const oldest = this.windows.keys().next().value;
              this.windowBytes -= this.windows.get(oldest).bytes; this.windows.delete(oldest);
            }
            this.windows.set(key, window); this.windowBytes += window.bytes;
          }
        }
      }
      if (this.windows.get(key) === window) {
        this.windows.delete(key); this.windows.set(key, window);
      }
      yield {...columnSlice(window.member, offset - start, limit), ...window.original};
    }
  }
  async *scan(aid, bid, gids) {
    // Preserve members this scan will reuse. For blocks larger than the cache,
    // stream other members without evicting the upcoming hits on every page.
    const retained = new Set(gids.map(gid => `${aid}/${bid}/${gid}`).filter(key => this.items.has(key)));
    for (const gid of gids) yield await this.get(aid, bid, gid, retained);
  }
}

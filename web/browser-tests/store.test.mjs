import test from 'node:test';
import assert from 'node:assert/strict';
import {MemberCache} from '../mauve_web/static/browser/store.mjs';

function fixture(limit = 18) {
  const reads = [];
  const store = {async get(table, [aid, bid, gid]) {
    reads.push([aid, bid, gid]);
    if (gid === 99) return undefined;
    return {genome_id: gid, sequence: new Uint8Array(gid === 4 ? 30 : 5).fill(bid * 10 + gid), prefix: new Uint32Array(1)};
  }};
  return {cache: new MemberCache(store, limit), reads};
}

test('oversized block scans retain upcoming hits and stay within the byte limit', async () => {
  const {cache, reads} = fixture();
  for (let page = 0; page < 4; ++page) {
    const members = [];
    for await (const member of cache.scan('a', 1, [1, 2, 3])) {
      members.push(member.genome_id);
      assert.equal(member.sequence[0], 10 + member.genome_id);
      assert.ok(cache.bytes <= cache.limit);
    }
    assert.deepEqual(members, [1, 2, 3]);
    assert.equal(reads.length, 3 + page); // three initial reads, then one per page
    assert.equal(cache.bytes, 18);
  }
});

test('scan retention ends on early exit or failure and other blocks can replace entries', async () => {
  const {cache, reads} = fixture();
  for await (const member of cache.scan('a', 1, [1, 2, 3])) { /* warm cache */ }
  for await (const member of cache.scan('a', 1, [1, 2, 3])) break;
  await assert.rejects(async () => {
    for await (const member of cache.scan('a', 1, [2, 99, 3])) { /* missing member */ }
  }, /not found/);
  for await (const member of cache.scan('a', 2, [1, 2])) assert.equal(member.sequence[0], 20 + member.genome_id);
  const before = reads.length;
  for await (const member of cache.scan('a', 2, [1, 2])) { /* fits completely */ }
  assert.equal(reads.length, before);
  assert.equal(cache.bytes, 18);
});

test('individual oversized members bypass storage and normal reads retain LRU behavior', async () => {
  const {cache, reads} = fixture();
  await cache.get('a', 1, 1); await cache.get('a', 1, 2); await cache.get('a', 1, 1);
  await cache.get('a', 1, 3); // evicts 2, which is least recently used
  const before = reads.length;
  await cache.get('a', 1, 1);
  assert.equal(reads.length, before);
  await cache.get('a', 1, 4);
  assert.equal(cache.bytes, 18);
  await cache.get('a', 1, 3);
  assert.equal(reads.length, before + 1);
});

import {indexMember, columnSlice} from '../mauve_web/static/browser/core.mjs';

function pageFixture(limit = 25000, windowLimit = 40000) {
  const reads = [], sequence = 'AC-GT--N'.repeat(2500), length = sequence.replaceAll('-', '').length;
  const member = (bid, gid) => indexMember({genome_id: gid, start: bid * 100000 + gid * 1000,
    end: bid * 100000 + gid * 1000 + length - 1, strand: gid === 2 ? '-' : '+', sequence});
  const store = {async get(table, [aid, bid, gid]) {
    reads.push([aid, bid, gid]); return gid === 99 ? undefined : member(bid, gid);
  }};
  const cache = new MemberCache(store, limit, windowLimit);
  const page = async (bid, offset, count, gids = [1, 2, 3]) => {
    const result = [];
    for await (const value of cache.pages('a', bid, gids, offset, count, sequence.length)) result.push(value);
    assert.deepEqual(result, gids.map(gid => columnSlice(member(bid, gid), offset, count)));
    assert.ok(cache.bytes <= limit);
    assert.ok(cache.windowBytes <= windowLimit);
    assert.equal(cache.windowBytes, [...cache.windows.values()].reduce((n, w) => n + w.bytes, 0));
    for (const window of cache.windows.values()) assert.equal(window.member.sequence.buffer.byteLength, window.member.sequence.byteLength);
    return result;
  };
  return {cache, reads, page};
}

test('page windows avoid rereads and preserve coordinates across boundaries and gaps', async () => {
  const {cache, reads, page} = pageFixture();
  await page(1, 0, 100);
  assert.equal(reads.length, 3);
  await page(1, 100, 100); await page(1, 400, 500);
  assert.equal(reads.length, 3, 'adjacent pages reuse windows without full-member reads');
  for (const offset of [8190, 8200, 16380, 19990, 0, 400, 8192]) await page(1, offset, 500);
  await assert.rejects(async () => {
    for await (const value of cache.pages('a', 1, [3, 99, 1], 100, 100, 20000)) { /* missing member */ }
  }, /not found/);
  for await (const value of cache.pages('a', 1, [1, 2, 3], 0, 100, 20000)) break;
  await page(2, 100, 500); await page(1, 200, 100);
});

test('fitting blocks and undersized window budgets preserve the full-member cache path', async () => {
  const fitting = pageFixture(100000, 40000);
  await fitting.page(1, 0, 100); await fitting.page(1, 100, 100);
  assert.equal(fitting.reads.length, 3);
  assert.equal(fitting.cache.windowBytes, 0);
  const tiny = pageFixture(25000, 1);
  await tiny.page(1, 0, 100); await tiny.page(1, 100, 100);
  assert.equal(tiny.cache.windowBytes, 0);
});

test('overlapping member reads share one load and count cached bytes once', async () => {
  const {cache, reads} = fixture();
  const members = await Promise.all(Array.from({length: 8}, () => cache.get('a', 1, 1)));
  assert.equal(reads.length, 1);
  for (const member of members) assert.equal(member, members[0]);
  assert.equal(cache.bytes, 9);
  assert.equal((cache.pending?.size ?? 0), 0);
  await Promise.all([cache.get('a', 1, 2), cache.get('a', 1, 3)]);
  assert.equal(cache.bytes, [...cache.items.values()].reduce((n, m) => n + m.sequence.byteLength + m.prefix.byteLength, 0));
  assert.ok(cache.bytes <= cache.limit);
});

test('shared load failures clear pending state and can be retried', async () => {
  for (const missing of [false, true]) {
    let reads = 0, fail = true;
    const member = {genome_id: 1, sequence: new Uint8Array(5), prefix: new Uint32Array(1)};
    const cache = new MemberCache({async get() {
      reads++;
      if (fail) { if (missing) return undefined; throw Error('storage failed'); }
      return member;
    }}, 18);
    const results = await Promise.allSettled([cache.get('a', 1, 1), cache.get('a', 1, 1)]);
    assert.deepEqual(results.map(r => r.status), ['rejected', 'rejected']);
    assert.equal(reads, 1); assert.equal((cache.pending?.size ?? 0), 0); assert.equal(cache.bytes, 0);
    fail = false;
    assert.equal(await cache.get('a', 1, 1), member);
    assert.equal(reads, 2); assert.equal(cache.bytes, 9); assert.equal((cache.pending?.size ?? 0), 0);
  }
});

test('oversized members share in-flight reads without entering the cache', async () => {
  const {cache, reads} = fixture(1);
  const [a, b] = await Promise.all([cache.get('a', 1, 4), cache.get('a', 1, 4)]);
  assert.equal(a, b); assert.equal(reads.length, 1);
  assert.equal(cache.items.size, 0); assert.equal(cache.bytes, 0); assert.equal((cache.pending?.size ?? 0), 0);
  await cache.get('a', 1, 4); assert.equal(reads.length, 2);
});

test('overlapping pages share windows while preserving byte accounting and reverse positions', async () => {
  const {cache, reads, page} = pageFixture();
  await Promise.all([page(1, 0, 100), page(1, 100, 100), page(1, 400, 500)]);
  assert.equal(reads.length, 3);
  assert.equal((cache.pending?.size ?? 0), 0);
  await Promise.all([page(1, 8190, 500), page(1, 8192, 500), page(1, 16380, 500), page(2, 100, 100)]);
  assert.equal((cache.pending?.size ?? 0), 0);
  assert.equal(cache.bytes, [...cache.items.values()].reduce((n, m) => n + m.sequence.byteLength + m.prefix.byteLength, 0));
});

test('a window evicted during an asynchronous growth read is not subtracted twice', async () => {
  const {cache, page} = pageFixture();
  await page(1, 0, 100);
  assert.ok(cache.windows.has('a/1/1/0'));
  const get = cache.store.get;
  let release, entered;
  const gate = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { entered = resolve; });
  cache.store.get = async (...args) => {
    const [, bid, gid] = args[1];
    if (bid === 1 && gid === 1) { entered(); await gate; }
    return get(...args);
  };
  const growing = page(1, 8190, 500, [1, 2]);
  await started;
  try {
    await page(2, 0, 100);
    assert.equal(cache.windows.has('a/1/1/0'), false);
  } finally { release(); }
  await growing;
  assert.equal((cache.pending?.size ?? 0), 0);
});

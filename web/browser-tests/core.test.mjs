import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {parseXMFA, columnSlice, coordinateColumn, nextDifference, pairCounts, profileMember, indexMember, consumed, lines} from '../mauve_web/static/browser/core.mjs';
import {parseRecords, annotationData, verifyMember, locationParts, normalizeInput} from '../mauve_web/static/browser/genbank.mjs';
const fixture = name => readFile(new URL('../' + name, import.meta.url));
async function parse(text) { const blocks = []; const meta = await parseXMFA(new Blob([text]), b => blocks.push(b)); return {...meta, blocks}; }
test('streamed lines preserve UTF-8, CRLF, empty lines and unwrapped chunk boundaries', async () => {
  const cases = ['', '\n', '  ', ' \r\nαβ\t\n\n> chr🧬.fa\nACG--\r\nlast  '];
  for (const text of [...cases, 'A'.repeat(131071) + '\r\nend']) {
    const bytes = new TextEncoder().encode(text);
    for (const size of text.length > 1000 ? [65535, 65536, 65537] : [1, 2, 3, 7, 64]) {
      const source = {stream: () => new ReadableStream({start(controller) {
        for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.subarray(i, i + size));
        controller.close();
      }})};
      const actual = [];
      for await (const line of lines(source)) actual.push(line);
      const expected = text ? text.split('\n') : [];
      if (text.endsWith('\n')) expected.pop();
      assert.deepEqual(actual, expected.map(s => s.trim()));
    }
  }
  await assert.rejects(async () => {
    for await (const line of lines(new Blob([new Uint8Array([0xc3, 0x28])]))) { /* malformed UTF-8 */ }
  });
});
test('real yeast fixture, annotations and coordinates', async () => {
  const a = await parse(await fixture('demo.alignment'));
  assert.equal(a.block_count, 5); assert.deepEqual(a.genomes.map(g => g.extent), [693, 2000]);
  const annotations = annotationData(await parseRecords(new Blob([await fixture('demo.gbk')])), true);
  let count = 0; for (const b of a.blocks) for (const m of b.members) if (m.genome_id === 2) count += verifyMember(m, annotations.sequence);
  assert.equal(count, 2000); assert.equal(annotations.records.length, 2);
  assert.ok(annotations.features.some(f => f.name === 'TEL01L-TR'));
  for (const b of a.blocks) for (const m of b.members) {
    const page = columnSlice(m, 0, b.columns);
    for (let c = 0; c < page.positions.length; c++) if (page.positions[c] !== null) assert.equal(coordinateColumn(m, page.positions[c]), c);
  }
});
test('reverse strand, gaps, ambiguity and identity rules', async () => {
  const a = await parse('> 1:10-12 + first.fa\nAC-G\n> 2:21-23 - second.fa\nA-TG\n=\n');
  const [x, y] = a.blocks[0].members;
  assert.deepEqual(columnSlice(x, 0, 4).positions, [10, 11, null, 12]);
  assert.deepEqual(columnSlice(y, 0, 4).positions, [23, null, 22, 21]);
  assert.equal(nextDifference(a.blocks[0]), 1); assert.equal(nextDifference(a.blocks[0], 3), null);
  const p = profileMember(y, 4, 2, pairCounts(y.sequence, x.sequence, 2));
  assert.equal(p.matches, 2); assert.equal(p.gap_columns, 2); assert.equal(p.substitutions, 0);
});
test('sparse rank index across long gaps and exact stride boundary', () => {
  const sequence = 'A' + '-'.repeat(4095) + 'CT'.repeat(1024), m = indexMember({genome_id: 1, start: 1, end: 2049, strand: '-', sequence});
  assert.equal(consumed(m, sequence.length), 2049);
  assert.equal(coordinateColumn(m, 2049), 0); assert.equal(coordinateColumn(m, 2048), 4096);
  assert.equal(coordinateColumn(m, 1), sequence.length - 1);
});
test('malformed XMFA never publishes valid-looking output', async () => {
  for (const text of ['', 'not an alignment', '> 1:1-5 +\nACG\n=', '> 1:1-3 +\nACG\n> 2:1-2 +\nAC\n=', '> 1:0-0 +\nACG\n=', '> 0:1-3 +\nACG\n=', '> 1:1-3 +\nXYZ\n=']) await assert.rejects(parse(text));
});
test('XMFA span validation reuses rank counts across boundaries and missing members', async () => {
  for (const length of [1, 1023, 1024, 1025, 2048, 2049]) {
    const sequence = 'ac-nr--t'.repeat(Math.ceil(length / 8)).slice(0, length);
    const bases = sequence.replaceAll('-', '').length;
    for (const strand of ['+', '-']) {
      const header = `> 1:10-${9 + bases} ${strand}\n`;
      const a = await parse(`${header}${sequence}\n> 2:0-0 +\n${'-'.repeat(length)}\n=\n`);
      assert.equal(a.genomes.length, 1);
      assert.equal(a.blocks[0].members.length, 1);
      const member = a.blocks[0].members[0];
      assert.equal(consumed(member, length), bases);
      assert.equal(columnSlice(member, 0, length).bases, sequence.toUpperCase());
      await assert.rejects(parse(`> 1:10-${10 + bases} ${strand}\n${sequence}\n=\n`), /span does not match/);
    }
  }
});
test('GenBank locations preserve compound strand/fuzzy coordinates and reject unsupported locations', () => {
  assert.deepEqual(locationParts('complement(join(<1..3,8..>10))', 20), [{start:8,end:10,strand:'-',fuzzy:true},{start:1,end:3,strand:'-',fuzzy:true}]);
  for (const s of ['OTHER:1..3', '1^2', '?..4', '3..100']) assert.throws(() => locationParts(s, 10));
});
test('FASTA inputs validate DNA and preserve record offsets', async () => {
  const result = await normalizeInput(new Blob(['>a\n'+'ACGT'.repeat(20)+'\n>b\n'+'A'.repeat(50)]));
  assert.equal(result.bases, 130); assert.deepEqual(result.records.map(r => [r.start,r.end]), [[1,80],[81,130]]);
  await assert.rejects(normalizeInput(new Blob(['>a\n'+'A-'.repeat(50)])));
});
test('FASTA normalization preserves records across line batches', async () => {
  const a = 'acgtn'.repeat(20000), b = 'tgca'.repeat(25000);
  const wrap = sequence => sequence.match(/.{1,80}/g).join('\n');
  const result = await normalizeInput(new Blob([`>first description\n${wrap(a)}\n\n>second\n${wrap(b)}`]));
  assert.equal(result.bases, a.length + b.length);
  assert.deepEqual(result.records, [{name: 'first', start: 1, end: a.length},
    {name: 'second', start: a.length + 1, end: a.length + b.length}]);
  assert.equal((await result.normalized.text()).split('\n').slice(1).join(''), (a + b).toUpperCase());
});

test('identity counts classify every byte pair and partial bins', () => {
  const a = new Uint8Array(65536), b = new Uint8Array(65536);
  for (let i = 0; i < a.length; i++) { a[i] = i >>> 8; b[i] = i & 255; }
  for (const width of [1, 53, 1024, 65537]) {
    const expected = new Uint32Array(Math.ceil(a.length / width) * 4);
    for (let i = 0; i < a.length; i++) {
      const at = Math.floor(i / width) * 4;
      if (a[i] === 45 || b[i] === 45) expected[at + 2]++;
      else if ([65, 67, 71, 84].includes(a[i]) && [65, 67, 71, 84].includes(b[i])) {
        expected[at + 1]++; if (a[i] === b[i]) expected[at]++;
      } else expected[at + 3]++;
    }
    assert.deepEqual(pairCounts(a, b, width), expected);
  }
  assert.deepEqual(pairCounts(new Uint8Array(), new Uint8Array(), 53), new Uint32Array());
});

test('GenBank batching preserves fixed columns, qualifiers, UTF-8 and record boundaries', async () => {
  const feature = (key, value) => '     ' + key.padEnd(16) + value;
  const sequence = 'acgtn'.repeat(40);
  const header = ['LOCUS       record 200 bp', 'VERSION     RECORD.1', 'FEATURES             Location/Qualifiers'];
  const detail = [feature('CDS', 'complement(join(1..5,'), feature('', '11..15))'),
    feature('', '/gene="βeta"'), feature('', '/product="alpha'), feature('', 'beta"')];
  const origin = ['ORIGIN', '        1 ' + sequence, '//'];
  const compact = [...header, ...detail, ...origin].join('\r\n');
  const large = [...header, ...Array.from({length: 1022}, () => ''), ...detail, ...origin].join('\r\n');
  for (const text of [compact, large + '\n' + compact]) {
    const bytes = new TextEncoder().encode(text);
    for (const size of text === compact ? [1, 2, 7, 65536] : [63, 65536]) {
      const source = {stream: () => new ReadableStream({start(controller) {
        for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.subarray(i, i + size));
        controller.close();
      }})};
      const records = await parseRecords(source);
      assert.equal(records.length, text === compact ? 1 : 2);
      for (const record of records) {
        assert.equal(record.name, 'RECORD.1');
        assert.equal(new TextDecoder().decode(record.sequence), sequence.toUpperCase());
        assert.deepEqual(record.features, [{type: 'CDS', location: 'complement(join(1..5,11..15))',
          qualifiers: {gene: ['"βeta"'], product: ['"alpha beta"']}}]);
      }
    }
  }
});

test('reverse annotation verification preserves canonical, ambiguous and gap rules', () => {
  const encode = text => new TextEncoder().encode(text);
  const sequence = encode('NNACGTNRYSWKMBDHVNNN');
  const member = {start: 3, end: 17, strand: '-', sequence: encode('NNNNNNNNNNNA-CGT')};
  assert.equal(verifyMember(member, sequence), 4);
  assert.throws(() => verifyMember({...member, sequence: encode('NNNNNNNNNNNA-CGA')}, sequence), /does not match/);
  assert.equal(verifyMember({start: 3, end: 17, strand: '+', sequence: encode('AC-GTNNNNNNNNNNN')}, sequence), 4);
  assert.throws(() => verifyMember({...member, end: sequence.length + 1}, sequence), /shorter/);
});

test('profile windows match explicit coordinates through empty bins and rank boundaries', () => {
  for (const sequence of ['A' + '-'.repeat(4095) + 'CTN', 'AC-GT--N'.repeat(129), '-'.repeat(1025)]) {
    for (const strand of ['+', '-']) for (const width of [1, 17, 1024, 2048, 10000]) {
      const count = sequence.replaceAll('-', '').length;
      const member = indexMember({genome_id: 2, start: 100, end: 99 + count, strand, sequence});
      const counts = pairCounts(member.sequence, member.sequence, width);
      const actual = profileMember(member, sequence.length, width, counts);
      let position = strand === '+' ? member.start : member.end;
      const positions = Array.from(sequence, base => {
        if (base === '-') return null;
        const value = position; position += strand === '+' ? 1 : -1; return value;
      });
      const windows = [];
      for (let start = 0; start < sequence.length; start += width) {
        const bases = sequence.slice(start, start + width), coords = positions.slice(start, start + width).filter(p => p !== null);
        const compared = Array.from(bases).filter(b => 'ACGT'.includes(b)).length;
        if (coords.length) windows.push({start: Math.min(...coords), end: Math.max(...coords), identity: compared ? 1 : null, compared, columns: bases.length});
      }
      assert.deepEqual(actual.windows, windows);
      assert.equal(actual.matches, Array.from(sequence).filter(b => 'ACGT'.includes(b)).length);
      assert.equal(actual.gap_columns, sequence.length - count);
      assert.equal(actual.substitutions, 0);
      assert.equal(actual.ambiguous_columns, count - actual.matches);
    }
  }
});

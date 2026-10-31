import {canonical, coordinateColumn} from './core.mjs';

export function eligibleGene(f, rna = 'annotated') {
  if (f.pseudo || !['+', '-'].includes(f.strand) || !f.parts?.length || f.parts.some(p => p.fuzzy)) return false;
  if (f.type === 'CDS') return true;
  if (!['rRNA', 'tRNA', 'ncRNA', 'tmRNA', 'misc_RNA', 'snRNA', 'snoRNA'].includes(f.type)) return false;
  const experimental = Boolean(f.experiment?.trim()) && !/not experimental|no experimental/i.test(f.experiment);
  return experimental || (rna === 'annotated' && ['rRNA', 'tRNA'].includes(f.type));
}

const edgeKey = (a, b) => JSON.stringify(a < b ? [a, b] : [b, a]);
const ratio = (n, d) => d ? n / d : null;
const intersection = (a, b) => new Set([...a].filter(x => b.has(x)));

// A chromosome is a cyclic list of oriented family markers. Gene extremities
// make rotation and whole-chromosome reverse complementation invariant.
export function adjacencies(chromosomes) {
  const edges = new Set();
  for (const genes of chromosomes) for (let i = 0; i < genes.length; i++) {
    const a = genes[i], b = genes[(i + 1) % genes.length];
    edges.add(edgeKey(`${a.family}:${a.strand === '+' ? 'h' : 't'}`, `${b.family}:${b.strand === '+' ? 't' : 'h'}`));
  }
  return edges;
}

export function circularDCJ(a, b, n) {
  if (!n) return null;
  const links = new Map();
  for (const edges of [a, b]) for (const edge of edges) {
    const [x, y] = JSON.parse(edge);
    if (!links.has(x)) links.set(x, []);
    if (!links.has(y)) links.set(y, []);
    links.get(x).push(y); links.get(y).push(x);
  }
  if (links.size !== 2 * n || [...links.values()].some(v => v.length !== 2)) throw Error('DCJ requires unique shared, oriented markers.');
  const visited = new Set(); let cycles = 0;
  for (const vertex of links.keys()) if (!visited.has(vertex)) {
    cycles++; const stack = [vertex];
    while (stack.length) {
      const x = stack.pop(); if (visited.has(x)) continue;
      visited.add(x); stack.push(...links.get(x).filter(y => !visited.has(y)));
    }
  }
  return n - cycles;
}

export function pairMetrics(a, b) {
  const counts = chromosomes => {
    const map = new Map();
    for (const gene of chromosomes.flat()) map.set(gene.family, (map.get(gene.family) || 0) + 1);
    return map;
  };
  const ac = counts(a), bc = counts(b), shared = intersection(new Set(ac.keys()), new Set(bc.keys()));
  const union = ac.size + bc.size - shared.size;
  const unique = new Set([...shared].filter(id => ac.get(id) === 1 && bc.get(id) === 1));
  const aa = adjacencies(a), ab = adjacencies(b), common = intersection(aa, ab).size;
  const sa = adjacencies(a.map(c => c.filter(g => unique.has(g.family))));
  const sb = adjacencies(b.map(c => c.filter(g => unique.has(g.family))));
  const preserved = intersection(sa, sb).size;
  return {genes_a: a.flat().length, genes_b: b.flat().length, families_a: ac.size, families_b: bc.size,
    shared: shared.size, union, content_jaccard: ratio(shared.size, union),
    adjacency_shared: common, adjacency_union: aa.size + ab.size - common,
    adjacency_jaccard: ratio(common, aa.size + ab.size - common),
    order_genes: unique.size, excluded_shared: shared.size - unique.size,
    preserved, neighbors_a: sa.size, neighbors_b: sb.size,
    conservation: ratio(2 * preserved, sa.size + sb.size),
    conservation_a: ratio(preserved, sa.size), conservation_b: ratio(preserved, sb.size),
    dcj: circularDCJ(sa, sb, unique.size)};
}

function projected(gene, member) {
  return gene.parts.filter(p => p.start <= member.end && p.end >= member.start).map(p => {
    const x = coordinateColumn(member, Math.max(p.start, member.start));
    const y = coordinateColumn(member, Math.min(p.end, member.end));
    return {gene, start: Math.min(x, y), end: Math.max(x, y)};
  });
}

export async function analyzeGenes({genomes, sources, blocks}, loadMember, options = {}, progress = () => {}) {
  if (genomes.length < 2) throw Error('Gene comparisons require at least two genomes.');
  const settings = {coverage: 0.7, identity: 0.6, rna: 'annotated', ...options};
  if (![settings.coverage, settings.identity].every(x => Number.isFinite(x) && x > 0 && x <= 1)) throw Error('Coverage and identity must be greater than 0 and at most 100%.');
  if (!['annotated', 'experimental'].includes(settings.rna)) throw Error('Unknown RNA evidence policy.');
  const genes = [], byGenome = new Map(), summaries = [];
  for (const genome of genomes) {
    const source = sources.find(s => s.genome_id === genome.id);
    if (!source) throw Error(`Import GenBank annotations for ${genome.name} before running all-pairs analysis.`);
    if (!source.metadata.analysis_version) throw Error(`Reimport annotations for ${genome.name} to retain RNA evidence, pseudogene flags, and chromosome topology.`);
    if (source.metadata.records.some(r => r.topology === 'linear')) throw Error(`${genome.name} has a linear record. This analysis requires complete circular chromosomes.`);
    const selected = [], seen = new Set();
    for (const f of source.features) if (eligibleGene(f, settings.rna)) {
      // Count a CDS/RNA locus once, never both its gene and CDS records.
      const key = `${f.record}/${f.type}/${f.locus_tag || JSON.stringify(f.parts)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const parts = [...f.parts].sort((a, b) => a.start - b.start);
      if (parts.some((p, i) => i && p.start <= parts[i - 1].end)) continue;
      const record = source.metadata.records.find(r => r.name === f.record);
      if (!record) throw Error('Annotation record boundaries are missing. Reimport annotations.');
      const forwardParts = f.strand === '-' ? [...f.parts].reverse() : f.parts;
      const wraps = forwardParts.some((p, i) => i && p.start < forwardParts[i - 1].start);
      const gene = {...f, parts, index: genes.length, genome_id: genome.id,
        order: wraps ? forwardParts[0].start : f.start, length: parts.reduce((n, p) => n + p.end - p.start + 1, 0)};
      genes.push(gene); selected.push(gene);
    }
    byGenome.set(genome.id, selected);
    summaries.push({id: genome.id, name: genome.name, genes: selected.length,
      excluded_features: source.features.length - selected.length,
      assumed_circular: source.metadata.records.filter(r => r.topology !== 'circular').length});
  }
  // Repeated alignment coordinates would inflate coverage; require a unique map.
  for (const genome of genomes) {
    const intervals = blocks.flatMap(b => b.members.filter(m => m.genome_id === genome.id)).sort((a, b) => a.start - b.start);
    if (intervals.some((m, i) => i && m.start <= intervals[i - 1].end)) throw Error(`${genome.name} has overlapping alignment blocks; unique gene mapping is required.`);
  }
  const candidates = new Map(); let completed = 0;
  for (const block of blocks) {
    progress(`Matching genes: block ${++completed} of ${blocks.length}`);
    const members = block.members.filter(m => byGenome.get(m.genome_id)?.length);
    for (let i = 0; i < members.length; i++) {
      const a = await loadMember(block.id, members[i].genome_id);
      const ap = byGenome.get(a.genome_id).flatMap(g => projected(g, a)).sort((x, y) => x.start - y.start);
      if (!ap.length) continue;
      for (let j = i + 1; j < members.length; j++) {
        progress(`Matching genes: block ${completed} of ${blocks.length}, genomes ${members[i].genome_id} / ${members[j].genome_id}`);
        const b = await loadMember(block.id, members[j].genome_id);
        const bp = byGenome.get(b.genome_id).flatMap(g => projected(g, b)).sort((x, y) => x.start - y.start);
        let first = 0;
        for (const x of ap) {
          while (first < bp.length && bp[first].end < x.start) first++;
          for (let k = first; k < bp.length && bp[k].start <= x.end; k++) {
            const y = bp[k];
            if (y.end < x.start || x.gene.type !== y.gene.type || (x.gene.strand === a.strand) !== (y.gene.strand === b.strand)) continue;
            const ai = Math.min(x.gene.index, y.gene.index), bi = Math.max(x.gene.index, y.gene.index), key = `${ai}/${bi}`;
            let pair = candidates.get(key);
            if (!pair) { pair = {a: ai, b: bi, bases: 0, canonical: 0, matches: 0}; candidates.set(key, pair); }
            for (let c = Math.max(x.start, y.start); c <= Math.min(x.end, y.end); c++) {
              const ac = a.sequence[c], bc = b.sequence[c];
              if (ac === 45 || bc === 45) continue;
              pair.bases++;
              if (canonical(ac) && canonical(bc)) { pair.canonical++; if (ac === bc) pair.matches++; }
            }
          }
        }
      }
    }
  }
  const parent = genes.map(g => g.index);
  const root = i => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
  let matchedPairs = 0;
  for (const p of candidates.values()) {
    if (p.bases / genes[p.a].length >= settings.coverage && p.bases / genes[p.b].length >= settings.coverage &&
        p.canonical && p.matches / p.canonical >= settings.identity) {
      parent[root(p.b)] = root(p.a); matchedPairs++;
    }
  }
  const families = new Map();
  for (const gene of genes) {
    const id = root(gene.index);
    if (!families.has(id)) families.set(id, {id: `F${families.size + 1}`, members: []});
    const family = families.get(id); gene.family = family.id;
    family.members.push({genome_id: gene.genome_id, id: gene.id, name: gene.name, locus_tag: gene.locus_tag,
      type: gene.type, record: gene.record, start: gene.start, end: gene.end, strand: gene.strand});
  }
  const chromosomes = new Map();
  for (const genome of genomes) {
    const source = sources.find(s => s.genome_id === genome.id);
    chromosomes.set(genome.id, source.metadata.records.map(r => byGenome.get(genome.id).filter(g => g.record === r.name).sort((a, b) => a.order - b.order || a.end - b.end || a.index - b.index)));
  }
  const pairs = [];
  for (let i = 0; i < genomes.length; i++) for (let j = i + 1; j < genomes.length; j++) {
    const a = genomes[i].id, b = genomes[j].id;
    pairs.push({a, b, ...pairMetrics(chromosomes.get(a), chromosomes.get(b))});
  }
  const occupancy = Array(genomes.length).fill(0); let core = 0, singleCopyCore = 0, singleton = 0, duplicated = 0;
  for (const f of families.values()) {
    f.genomes = new Set(f.members.map(g => g.genome_id)).size;
    f.duplicated = f.members.length > f.genomes;
    occupancy[f.genomes - 1]++;
    if (f.genomes === genomes.length) { core++; if (!f.duplicated) singleCopyCore++; }
    if (f.genomes === 1) singleton++;
    if (f.duplicated) duplicated++;
  }
  progress('');
  return {settings, genomes: summaries, pairs, families: [...families.values()], matched_pairs: matchedPairs,
    pan: families.size, core, single_copy_core: singleCopyCore, accessory: families.size - core,
    genome_specific: singleton, duplicated_families: duplicated, occupancy};
}

// Deterministic workloads shared by profiling and baseline/optimized comparisons.
export function engineCase(kind, genomes, bases, seed = 12345) {
  const alphabet = 'ACGT';
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed; };
  const dna = n => Array.from({length: n}, () => alphabet[random() >>> 30]).join('');
  const reverse = s => [...s].reverse().map(c => ({A: 'T', C: 'G', G: 'C', T: 'A', N: 'N'})[c]).join('');
  let original = dna(bases);
  if (kind === 'repeats') {
    const repeat = original.slice(0, Math.min(500, Math.floor(bases / 20)));
    for (let at = 1000; at + repeat.length < bases; at += 2500)
      original = original.slice(0, at) + repeat + original.slice(at + repeat.length);
  }
  if (!['similar', 'divergent', 'rearranged', 'repeats', 'ambiguous'].includes(kind))
    throw Error('Unknown case: ' + kind);
  return Array.from({length: genomes}, (_, g) => {
    const sequence = [...original];
    const stride = kind === 'divergent' ? 31 : 997;
    for (let i = 100 + g; i < bases; i += stride) sequence[i] = alphabet[(g + i) % 4];
    if (kind === 'ambiguous') for (let i = 200 + g; i < bases; i += 613) sequence[i] = 'N';
    let result = sequence.join('');
    if (kind === 'rearranged' && g % 2) {
      const start = Math.floor(bases / 3), end = Math.floor(bases / 2);
      result = result.slice(0, start) + reverse(result.slice(start, end)) + result.slice(end);
      const at = Math.floor(bases * 0.75);
      result = result.slice(0, at) + 'ACGTACGT' + result.slice(at + 3);
    }
    return result;
  });
}

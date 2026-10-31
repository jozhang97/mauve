// Correlations of two permutations of the same unique family identifiers.
// With no ties, Kendall tau-b equals tau-a. Count discordances in O(n log n).
export function rankCorrelation(a, b) {
  const n = a.length;
  if (n !== b.length || new Set(a).size !== n || new Set(b).size !== n)
    throw Error('Rank correlations require matching unique families.');
  const ranks = new Map(b.map((id, i) => [id, i]));
  if (a.some(id => !ranks.has(id))) throw Error('Rank correlations require matching unique families.');
  if (n < 2) return {n, kendall: null, spearman: null};
  const tree = new Float64Array(n + 1);
  let discordant = 0, squared = 0;
  a.forEach((id, i) => {
    const rank = ranks.get(id);
    let prefix = 0;
    for (let k = rank + 1; k > 0; k -= k & -k) prefix += tree[k];
    discordant += i - prefix;
    for (let k = rank + 1; k <= n; k += k & -k) tree[k]++;
    squared += (i - rank) ** 2;
  });
  return {n, kendall: 1 - 4 * discordant / (n * (n - 1)),
    spearman: 1 - 6 * squared / (n * (n * n - 1))};
}

export function anchoredOrder(genes, direction, anchor) {
  const ordered = [...genes].sort((a, b) => a.order - b.order || a.family.localeCompare(b.family));
  if (direction === -1) ordered.reverse();
  const index = ordered.findIndex(g => g.family === anchor);
  if (index < 0) throw Error('Shared anchor family is missing.');
  return [...ordered.slice(index), ...ordered.slice(0, index)].map(g => g.family);
}

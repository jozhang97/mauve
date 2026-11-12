/* Native-coordinate replication geometry; independent of display orientation. */
(function(root) {
  function model(record, normalization) {
    if (!record || record.topology !== 'circular') return null;
    const normalized = ['rotated', 'already at oriC'].includes(normalization?.status);
    const origin = normalized ? 1 : record.replication_origin;
    if (!origin || record.replication_direction === 'LEFT' || record.replication_direction === 'RIGHT') return null;
    const length = record.end - record.start + 1;
    const terminus = ((origin - record.start + Math.floor(length / 2)) % length) + record.start;
    const direction = position => ((position - origin + length) % length) < Math.floor(length / 2) ? 1 : -1;
    const boundaries = [...new Set([record.start, origin, terminus, record.end + 1])].sort((a,b) => a-b);
    return {origin, terminus, direction, segments: boundaries.slice(0,-1).map((start,i) => ({start,end:boundaries[i+1]-1,direction:direction(start)}))};
  }
  function classify(replication, parts) {
    if (!replication || !parts?.length) return 'unknown';
    const values = parts.map(p => {
      if (!['+', '-'].includes(p.strand) || p.fuzzy) return 'unknown';
      if (replication.segments.some(s => s.start > p.start && s.start <= p.end)) return 'boundary';
      return replication.direction(p.start) === (p.strand === '+' ? 1 : -1) ? 'co-oriented' : 'head-on';
    });
    return values.every(v => v === values[0]) ? values[0] : 'boundary';
  }
  root.mauveReplication = {model, classify};
})(globalThis);

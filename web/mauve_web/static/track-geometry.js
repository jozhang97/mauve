/* Shared, DOM-independent model for circular track views and core filtering. */
(function (root) {
  'use strict';
  const base = (position, extent, direction) => direction === -1 ? extent + 1 - position : position;
  const edge = (position, extent, direction) => direction === -1 ? extent + 2 - position : position;
  function interval(start, end, extent, direction) {
    const a = base(start, extent, direction), b = base(end, extent, direction);
    return [Math.min(a,b), Math.max(a,b)];
  }
  function copies(start, end, {extent, direction, offset, length, viewStart, viewEnd}) {
    [start,end] = interval(start,end,extent,direction);
    const endOfTrack = length ? Math.min(viewEnd,viewStart+length-1) : viewEnd;
    if (!length) return end >= viewStart+offset && start <= endOfTrack+offset ? [0] : [];
    const first = Math.ceil((viewStart+offset-end)/length);
    const last = Math.floor((endOfTrack+offset-start)/length);
    return Array.from({length:Math.max(0,last-first+1)},(_,i)=>(first+i)*length);
  }
  function directions(members, referenceId, orient) {
    const reference = members.find(m=>m.genome_id===referenceId) || members[0];
    return new Map(members.map(m=>[m.genome_id,orient && m.strand!==reference.strand ? -1 : 1]));
  }
  function coreIndex(result, blocks, {core = true, essential = false} = {}) {
    const genes = (result?.families || []).filter(f=>!core || f.genomes===result.genomes.length).flatMap(f=>f.members)
      .filter(g=>!essential || g.essentiality?.status.split(' / ').includes('essential'));
    const geneKeys = new Set(genes.map(g=>`${g.genome_id}:${g.id}`)), intervals = new Map();
    for (const gene of genes) {
      if (!intervals.has(gene.genome_id)) intervals.set(gene.genome_id,[]);
      intervals.get(gene.genome_id).push(...gene.parts);
    }
    const blockIds = new Set(blocks.filter(b=>b.members.some(m=>(intervals.get(m.genome_id)||[])
      .some(p=>p.start<=m.end && p.end>=m.start))).map(b=>b.id));
    return {geneKeys,blockIds};
  }
  const geometry = Object.freeze({base,edge,interval,copies,directions,coreIndex});
  if (typeof module !== 'undefined' && module.exports) module.exports = geometry;
  else root.mauveTrackGeometry = geometry;
})(globalThis);

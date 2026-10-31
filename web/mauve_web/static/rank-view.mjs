import {rankCorrelation, anchoredOrder} from './browser/rank-correlation.mjs';
const el = id => document.getElementById(id);
let cachedResult, cachedKey, output = null, message = "";
function refresh() {
  const result = window.mauveGeneAnalysis?.result;
  const key = JSON.stringify([state.selected,state.reference,el('orient-tracks').checked,el('align-tracks').checked,
    [...state.trackDirections],state.sources.map(s=>[s.genome_id,s.metadata.length])]);
  if (result === cachedResult && key === cachedKey) return;
  cachedResult = result; cachedKey = key; output = null;
  const status = value => { message = value; window.dispatchEvent(new Event('mauve-rank-correlations')); };
  if (!result) return status('Waiting for core-family analysis.');
  if (!el('orient-tracks').checked || !el('align-tracks').checked)
    return status('Enable “Orient tracks to selected block” to calculate oriented core-gene order correlations.');
  const block = state.blocks.find(b=>b.id===state.selected);
  const referenceMember = block?.members.find(m=>m.genome_id===state.reference);
  if (!referenceMember) return status('Select a block containing the reference genome to define the circular anchor and orientation.');
  if (state.sources.some(s=>s.metadata.records.length !== 1))
    return status('Rank correlations currently require one complete circular chromosome per genome.');
  const families = result.families.filter(f=>f.genomes===result.genomes.length && f.members.length===result.genomes.length);
  if (families.length < 2) return status(`Only ${families.length} single-copy core families; at least two are needed for rank correlations.`);
  const genes = new Map(result.genomes.map(g=>[g.id,[]]));
  for (const f of families) for (const m of f.members) genes.get(m.genome_id).push({...m,family:f.id,order:m.order ?? m.start});
  if ([...genes.values()].some(list=>new Set(list.map(g=>g.order)).size!==list.length))
    return status('Core-gene positions contain ties; their order is ambiguous, so rank correlations are unavailable.');
  const referenceGenes = genes.get(state.reference), direction = trackDirection(state.reference);
  const length = chromosomeExtent(state.reference), origin = direction===1 ? referenceMember.start : referenceMember.end;
  const distance = g => ((direction*(g.order-origin))%length+length)%length;
  const overlaps = g => g.parts.some(p=>p.start<=referenceMember.end && p.end>=referenceMember.start);
  const anchor = [...referenceGenes].sort((a,b)=>Number(overlaps(b))-Number(overlaps(a)) || distance(a)-distance(b) || a.family.localeCompare(b.family))[0];
  const members = new Set(block.members.map(m=>m.genome_id));
  const orders = new Map([...genes].filter(([id])=>members.has(id)).map(([id,list])=>[id,anchoredOrder(list,trackDirection(id),anchor.family)]));
  const pairs = [];
  for(let i=0;i<result.genomes.length;i++) for(let j=i+1;j<result.genomes.length;j++) {
    const a=result.genomes[i], b=result.genomes[j];
    const metrics = orders.has(a.id)&&orders.has(b.id) ? rankCorrelation(orders.get(a.id),orders.get(b.id))
      : {n:0,kendall:null,spearman:null};
    pairs.push({a:a.id,b:b.id,name_a:a.name,name_b:b.name,...metrics});
  }
  output = {block:block.id,reference:state.reference,anchor:anchor.family,n:families.length,
    directions:Object.fromEntries([...orders.keys()].map(id=>[id,trackDirection(id)])),pairs};
  status(`Block ${block.id} · ${families.length.toLocaleString()} single-copy core families across all ${result.genomes.length} genomes; ${result.core-families.length} duplicated core families excluded. Circular start: ${anchor.family} (${anchor.name || anchor.locus_tag || 'unnamed gene'}), ${overlaps(anchor) ? 'overlapping' : 'nearest after'} this block in the reference. Each chromosome is rotated to this same family and follows its displayed orientation. Scores use the full chromosome, independent of zoom and pan. +1 = same order; −1 = opposite order. N/A = genome absent from the selected block.`);

}
el('export-core-ranks').onclick = () => {
  if (!output) return;
  const rows=[['genome_a','genome_b','core_families','kendall_tau','spearman_rho','anchor_family','selected_block','reference','direction_a','direction_b'],
    ...output.pairs.map(p=>[p.name_a,p.name_b,p.n,p.kendall??'',p.spearman??'',output.anchor,output.block,output.reference,output.directions[p.a]??'',output.directions[p.b]??''])];
  const text=rows.map(row=>row.map(v=>String(v).replace(/[\t\r\n]/g,' ')).join('\t')).join('\n')+'\n';
  const url=URL.createObjectURL(new Blob([text],{type:'text/tab-separated-values'})), link=document.createElement('a');
  link.href=url;link.download='core-gene-rank-correlations.tsv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
window.mauveRankCorrelations={refresh,get result(){return output;},get status(){return message;}};
refresh();

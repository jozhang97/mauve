import {analyzeOrigins,histogram} from './browser/origin-analysis.mjs';
const el=id=>document.getElementById(id);
let cachedResult,cachedSources,cachedAlignment,cachedReference,output;
const node=(tag,text)=>{const n=document.createElement(tag); if(text!==undefined)n.textContent=text;return n;};
const colors={core:'#168b85',accessory:'#b66b24',essential:'#8b4fba'};
const essential=g=>g.essentiality?.status.split(' / ').includes('essential') || false;
function table(headers,rows) {
  const t=node('table'),head=node('thead'),tr=node('tr');
  for(const h of headers)tr.append(node('th',h)); head.append(tr);t.append(head);
  const body=node('tbody');for(const row of rows){const tr=node('tr');for(const value of row)tr.append(node('td',value));body.append(tr);}t.append(body);return t;
}
function plot(target,series,maximum,xLabel,percent=false) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox',`0 0 720 ${257 + Math.ceil(series.length/2)*22}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',`${xLabel}; ${series.map(s=>`${s.name}: ${s.values.length}`).join('; ')}; ${percent?'percent within each gene set':'counts'}`);
  const add=(tag,attrs,text)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;svg.append(n);return n;};
  const bins=series.map(s=>({...s,bins:histogram(s.values,maximum)}));
  const value=(s,b)=>percent ? (s.values.length ? 100*b.count/s.values.length : 0) : b.count;
  const max=Math.max(1,...bins.flatMap(s=>s.bins.map(b=>value(s,b))));
  add('line',{x1:52,x2:700,y1:200,y2:200,stroke:'currentColor'});
  for(let i=0;i<=4;i++){
    const y=200-i*43;add('text',{x:45,y:y+4,'text-anchor':'end',fill:'currentColor','font-size':11},percent?`${(max*i/4).toFixed(1)}%`:Math.round(max*i/4));
    add('line',{x1:52,x2:700,y1:y,y2:y,stroke:'currentColor',opacity:0.1});
    add('text',{x:52+i*162,y:218,'text-anchor':'middle',fill:'currentColor','font-size':11},(maximum*i/4).toFixed(maximum<=50?1:0));
  }
  for(const [j,s]of bins.entries())for(const [i,b]of s.bins.entries()){
    const width=648/20/bins.length;
    const bar=add('rect',{x:52+i*648/20+j*width,y:200-value(s,b)/max*172,width:width-1,height:value(s,b)/max*172,fill:s.color,'data-series':s.name,'data-value':value(s,b)});
    const title=document.createElementNS(svg.namespaceURI,'title');title.textContent=`${s.name}: ${b.start.toFixed(2)}–${b.end.toFixed(2)}: ${b.count}${percent?` / ${s.values.length} (${value(s,b).toFixed(2)}%)`:''}`;bar.append(title);
  }
  add('text',{x:376,y:240,'text-anchor':'middle',fill:'currentColor','font-size':12},xLabel);
  const legend=add('g',{class:'histogram-legend','aria-label':'Series legend'});
  series.forEach((s,i)=>{
    const x=52+(i%2)*324, y=263+Math.floor(i/2)*22;
    const entry=add('g',{'data-legend-series':s.name});
    entry.append(add('path',{d:`M${x},${y-9}h12v10h-12Z`,fill:s.color}));
    entry.append(add('text',{x:x+19,y,fill:'currentColor','font-size':11},`${s.name} (n=${s.values.length.toLocaleString()})`));
    legend.append(entry);
  });
  el(target).replaceChildren(svg);
}
function refresh() {
  const result=window.mauveGeneAnalysis?.result;
  if(result===cachedResult && state.sources===cachedSources && state.alignment===cachedAlignment && state.reference===cachedReference)return;
  cachedResult=result;cachedSources=state.sources;cachedAlignment=state.alignment;
  cachedReference=state.reference;
  output=result ? analyzeOrigins(result,state.sources,state.alignment.genomes,window.mauveReplication,{blocks:state.blocks,reference:state.reference}) : null;
  render();
}
function render() {
  el('origin-results').hidden=!output;
  if(!output){el('origin-analysis-status').textContent='Compute gene comparisons above to explore core/accessory genes relative to oriC.';return;}
  const unit=el('origin-unit').value, normalized=unit==='percent', gid=el('origin-genome').value;
  const options=state.alignment.genomes.map(g=>[String(g.id),g.name]);
  if(el('origin-genome').options.length!==options.length+1){
    el('origin-genome').replaceChildren(new Option('All eligible genomes','all'),...options.map(([id,name])=>new Option(name,id)));
  }
  const genes=output.genes.filter(g=>gid==='all'||String(g.genome_id)===gid);
  el('origin-analysis-status').textContent=`Origins available for ${output.eligible.length}/${state.alignment.genomes.length} genomes. ${output.excluded.length?'Excluded: '+output.excluded.map(g=>g.name).join('; ')+'. ':''}${genes.length.toLocaleString()} gene copies in the selected scope. Core/accessory membership uses all loaded genomes. Cross-genome ranges always use all eligible genomes, regardless of the genome selector.`;
  const rows=[];
  for(const category of ['core','accessory','pan','essential reference matches']){
    const group=genes.filter(g=>category==='essential reference matches'?essential(g):category==='pan'||g.category===category);
    const leading=group.filter(g=>g.replication==='co-oriented').length,lagging=group.filter(g=>g.replication==='head-on').length;
    const total=leading+lagging, percent=n=>total?`${(100*n/total).toFixed(1)}% (${n.toLocaleString()})`:'N/A';
    rows.push([category,group.length.toLocaleString(),percent(leading),percent(lagging),(group.length-total).toLocaleString()]);
  }
  el('origin-essentiality-status').textContent=cachedResult.essentiality_source
    ? `${genes.filter(essential).length.toLocaleString()} gene copies in this scope have essential reference evidence. Purple series overlap core/accessory sets. Distance and strand summaries count only copies with their own sequence match; variation plots use core families with evidence in at least one member and compare all usable members. Essentiality is not established in these strains.`
    : (cachedResult.essentiality_error || 'Essentiality evidence unavailable; recompute gene comparisons to load the reference annotations.');
  el('origin-fractions').replaceChildren(table(['Gene set','Gene copies','Leading / co-oriented','Lagging / head-on','Unknown / boundary'],rows));
  const distance=g=>normalized?g.distance_fraction*100:g.distance_bp/1000;
  const maximum=normalized?50:genes.reduce((n,g)=>Math.max(n,distance(g)),1);
  plot('origin-distances',[...['core','accessory'].map(category=>({name:category,color:colors[category],values:genes.filter(g=>g.category===category).map(distance)})),{name:'essential reference matches',color:colors.essential,values:genes.filter(essential).map(distance)}],maximum,`Shortest circular midpoint distance to oriC (${normalized?'% chromosome':'kb'})`,el('origin-histogram-scale').value==='percent');
  const positionFamilies=output.ranges.filter(r=>r.position_range_fraction!==null);
  const positional=el('origin-range-metric').value==='position';
  const plottedFamilies=positional?positionFamilies:output.ranges;
  const measurement=r=>positional?r.position_range_fraction*100:normalized?r.range_fraction*100:r.range_bp/1000;
  const values=plottedFamilies.map(measurement);
  const rangeMaximum=Math.ceil(values.reduce((n,v)=>Math.max(n,v),0.1)*10)/10;
  plot('origin-ranges',[
    {name:'Core families',color:colors.core,values},
    {name:'Essential-core families',color:colors.essential,values:plottedFamilies.filter(r=>r.essential_reference).map(measurement)}
  ],rangeMaximum,positional?'Maximum circular separation (% chromosome)':`Distance-to-oriC range (${normalized?'percentage points of chromosome':'kb'})`);
  const ambiguous=output.orientations.filter(o=>output.eligible.includes(o.genome_id)&&o.direction===null);
  const referenceName=state.alignment.genomes.find(g=>g.id===output.reference)?.name||'unavailable';
  el('origin-range-status').textContent=`${positionFamilies.length.toLocaleString()} core families compared; ${positionFamilies.filter(r=>r.essential_reference).length} with essential reference evidence; ${(cachedResult.core-positionFamilies.length).toLocaleString()} unavailable (fewer than two usable genome positions). Reference: ${referenceName}. ${ambiguous.length} origin-eligible genome(s) excluded for ambiguous alignment orientation. Includes positions near oriC and the terminus. ${positionFamilies.filter(r=>r.duplicated).length} families use circular means of duplicate copies within each genome. Cross-genome separation always uses normalized chromosome positions, regardless of distance units above.`;
  if(!positional)el('origin-range-status').textContent=`${plottedFamilies.length.toLocaleString()} core families compared; ${plottedFamilies.filter(r=>r.essential_reference).length} with essential reference evidence; ${cachedResult.core-plottedFamilies.length} unavailable. Distance range requires known origins in at least two genomes; chromosome orientation is not needed. Duplicate copies use their mean distance within each genome. Units follow the distance selector above.`;
  el('origin-orientations').replaceChildren(table(['Genome','Orientation to reference','Alignment support'],output.orientations.filter(o=>output.eligible.includes(o.genome_id)).map(o=>[state.alignment.genomes.find(g=>g.id===o.genome_id)?.name,o.genome_id===output.reference?'reference':o.direction===null?'ambiguous':o.direction===1?'same':'reverse-complemented',o.genome_id===output.reference?'reference':`${(o.support*100).toFixed(1)}% of ${o.columns.toLocaleString()} alignment columns`])));
  const query=el('origin-family-search').value.toLowerCase();
  const families=output.ranges.filter(r=>(r.family+' '+r.name).toLowerCase().includes(query)).sort((a,b)=>positional?(b.position_range_fraction??-1)-(a.position_range_fraction??-1):measurement(b)-measurement(a));
  el('origin-range-table').replaceChildren(table(['Core family','Example gene','Reference essentiality','Usable genomes (distance / position)','Duplicate copies?',`Distance-to-oriC range (${normalized?'% points':'kb'})`,'Maximum circular separation (%)','Position by genome (% from oriC)'],families.slice(0,100).map(r=>[r.family,r.name,r.reference_essentiality,`${r.genomes} / ${r.position_genomes}`,r.duplicated?'yes':'no',(normalized?r.range_fraction*100:r.range_bp/1000).toFixed(3),r.position_range_fraction===null?'N/A':(r.position_range_fraction*100).toFixed(3),r.means.map(m=>`#${m.genome_id}: ${m.circular_position_fraction===null?'N/A':(m.circular_position_fraction*100).toFixed(2)}`).join('; ')])));
  el('origin-table-status').textContent=`Showing ${Math.min(100,families.length)} of ${families.length} matching families, largest ${positional?'separation':'distance range'} first. Positions run from 0 to 100% around the chromosome from oriC. Export includes all positions, exclusions, and orientation support.`;
}
for(const id of ['origin-unit','origin-genome','origin-histogram-scale','origin-range-metric'])el(id).onchange=render;
el('origin-family-search').oninput=render;
el('export-origin-analysis').onclick=()=>{
  if(!output)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify({essentiality_source:cachedResult.essentiality_source,definitions:{essential:'Gene copies with essential reference sequence matches; essential-core range families have evidence in at least one member. Overlaps core/accessory sets; not measured essentiality in the loaded strains.',distance:'Shortest circular distance to midpoint along annotated gene segments',range:'Radial range: max minus min of per-genome mean distances to oriC',position_range:'Maximum pairwise shortest circular distance between normalized genome positions; fractions of chromosome length',copies:'Per-genome circular mean for positions (undefined for balanced opposing copies); arithmetic mean for radial distances',strand:'Bidirectional replication; terminus opposite oriC',core:'Present in every loaded genome',orientation:'Dominant relative block strand weighted by alignment columns; at least 80% support required'},...output},null,2)],{type:'application/json'}));
  const a=node('a');a.href=url;a.download='origin-gene-analysis.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
window.addEventListener('mauve-gene-analysis',refresh);
window.mauveOriginAnalysis={refresh,get result(){return output;}};
refresh();

// Gene-copy statistics; core/accessory membership always uses all loaded genomes.
export function midpoint(gene) {
  let parts = gene.parts || [];
  // Family output stores parts sorted by coordinate; restore circular gene order.
  if (Number.isFinite(gene.order) && parts.length>1) {
    parts=[...parts].sort((a,b)=>a.start-b.start);
    const anchor=parts.findIndex(p=>p.start===gene.order);
    if(anchor>0)parts=[...parts.slice(anchor),...parts.slice(0,anchor)];
    if(gene.strand==='-')parts.reverse();
  }
  let offset = Math.floor(parts.reduce((n,p) => n + p.end-p.start+1, 0)/2);
  for (const p of parts) {
    const length=p.end-p.start+1;
    if (offset < length) return p.strand === '-' ? p.end-offset : p.start+offset;
    offset-=length;
  }
  return null;
}
export function histogram(values, maximum, count=20) {
  const bins=Array.from({length:count},(_,i)=>({start:i*maximum/count,end:(i+1)*maximum/count,count:0}));
  for (const value of values) if (Number.isFinite(value) && value>=0 && value<=maximum) bins[Math.min(count-1,Math.floor(value/maximum*count))].count++;
  return bins;
}
function coveredFraction(intervals, record) {
  if(!record)return 0;
  let bases=0,end=record.start-1;
  for(const [a,b] of intervals.sort((a,b)=>a[0]-b[0])) {
    const start=Math.max(a,record.start),stop=Math.min(b,record.end);
    if(stop>=start){bases+=Math.max(0,stop-Math.max(end,start-1));end=Math.max(end,stop);}
  }
  return bases/(record.end-record.start+1);
}
export function chromosomeOrientations(genomes, blocks, reference, records=new Map()) {
  return genomes.map(g=>{
    if(g.id===reference)return {genome_id:g.id,direction:1,support:1,columns:0};
    let same=0,opposite=0;
    const spans={same:[[],[]],opposite:[[],[]]};
    for(const block of blocks){
      const a=block.members.find(m=>m.genome_id===reference),b=block.members.find(m=>m.genome_id===g.id);
      if(!a||!b||!['+','-'].includes(a.strand)||!['+','-'].includes(b.strand))continue;
      if(![a.start,a.end,b.start,b.end].every(Number.isSafeInteger)||a.start<1||b.start<1||a.end<a.start||b.end<b.start||!Number.isFinite(block.columns)||block.columns<=0)continue;
      const group=a.strand===b.strand?'same':'opposite';
      spans[group][0].push([a.start,a.end]);spans[group][1].push([b.start,b.end]);
      if(a.strand===b.strand)same+=block.columns;else opposite+=block.columns;
    }
    const columns=same+opposite,support=columns?Math.max(same,opposite)/columns:0;
    const winner=same>opposite?'same':'opposite';
    const reference_coverage=coveredFraction(spans[winner][0],records.get(reference));
    const genome_coverage=coveredFraction(spans[winner][1],records.get(g.id));
    const sufficient=reference_coverage>=0.5&&genome_coverage>=0.5;
    return {genome_id:g.id,direction:support>=0.8&&sufficient?(same>opposite?1:-1):null,support,columns,
      reference_coverage,genome_coverage,reason:!sufficient?'Insufficient chromosome coverage':support<0.8?'Conflicting orientations':null};
  });
}
export function circularMean(values) {
  if(!values.length)return null;
  const x=values.reduce((n,v)=>n+Math.cos(2*Math.PI*v),0);
  const y=values.reduce((n,v)=>n+Math.sin(2*Math.PI*v),0);
  if(Math.hypot(x,y)/values.length<1e-8)return null;
  return ((Math.atan2(y,x)/(2*Math.PI))%1+1)%1;
}
export function maximumCircularSeparation(positions) {
  if(positions.length<2)return null;
  let maximum=0;
  for(let i=0;i<positions.length;i++)for(let j=i+1;j<positions.length;j++){
    const difference=Math.abs(positions[i]-positions[j]);
    maximum=Math.max(maximum,Math.min(difference,1-difference));
  }
  return maximum;
}
export function analyzeOrigins(result, sources, genomes, replication, options={}) {
  const eligible=new Map(), excluded=[];
  for (const genome of genomes) {
    const records=sources.find(s=>s.genome_id===genome.id)?.metadata.records;
    const record=records?.length===1 ? records[0] : null;
    const normalized=['rotated','already at oriC'].includes(genome.ori_normalization?.status);
    const origin=normalized?1:record?.replication_origin;
    if(!record||record.topology!=='circular'||!Number.isSafeInteger(origin)||origin<record.start||origin>record.end){excluded.push({id:genome.id,name:genome.name});continue;}
    const model=replication.model(record,genome.ori_normalization);
    eligible.set(genome.id,{genome,record,origin,model,length:record.end-record.start+1});
  }
  const reference=eligible.has(options.reference)?options.reference:[...eligible.keys()][0];
  const orientations=chromosomeOrientations(genomes,options.blocks||[],reference,new Map([...eligible].map(([id,s])=>[id,s.record])));
  const directions=new Map(orientations.map(o=>[o.genome_id,o.direction]));
  const genes=[], ranges=[];
  for (const family of result.families) {
    const category=family.genomes===result.genomes.length ? 'core' : 'accessory';
    const distances=new Map();
    for (const gene of family.members) {
      const source=eligible.get(gene.genome_id);
      if (!source || gene.record!==source.record.name) continue;
      const position=midpoint(gene);
      if (position===null) continue;
      const clockwise=((position-source.origin)%source.length+source.length)%source.length;
      const bp=Math.min(clockwise,source.length-clockwise), fraction=bp/source.length;
      const direction=directions.get(gene.genome_id);
      const classification=replication.classify(source.model,gene.parts);
      const circularPosition=direction?((clockwise/source.length*direction)%1+1)%1:null;
      genes.push({family:family.id,category,...gene,position,distance_bp:bp,distance_fraction:fraction,replication:classification,
        circular_position_fraction:circularPosition,orientation:direction});
      if (!distances.has(gene.genome_id)) distances.set(gene.genome_id,[]);
      distances.get(gene.genome_id).push({bp,fraction,circularPosition});
    }
    if (category==='core' && distances.size>=2) {
      const means=[...distances].map(([genome_id,values])=>({genome_id,copies:values.length,
        bp:values.reduce((n,v)=>n+v.bp,0)/values.length,fraction:values.reduce((n,v)=>n+v.fraction,0)/values.length,
        circular_position_fraction:values.every(v=>v.circularPosition!==null)?circularMean(values.map(v=>v.circularPosition)):null}));
      const positions=means.filter(m=>m.circular_position_fraction!==null).map(m=>m.circular_position_fraction);
      ranges.push({family:family.id,reference_essentiality:family.essentiality?.status||'unknown',essential_reference:family.essentiality?.status.split(' / ').includes('essential') || false,name:family.members[0]?.name||family.members[0]?.locus_tag||'',genomes:means.length,
        position_genomes:positions.length,position_range_fraction:maximumCircularSeparation(positions),
        duplicated:means.some(m=>m.copies>1),range_bp:Math.max(...means.map(m=>m.bp))-Math.min(...means.map(m=>m.bp)),
        range_fraction:Math.max(...means.map(m=>m.fraction))-Math.min(...means.map(m=>m.fraction)),means});
    }
  }
  return {genes,ranges,eligible:[...eligible.keys()],excluded,orientations,reference,
    orientation_policy:{minimum_column_agreement:0.8,minimum_supporting_span_coverage:0.5,
      coverage:'Union of supporting block coordinate spans on each chromosome; overlaps counted once'}};
}

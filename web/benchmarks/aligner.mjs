// node web/benchmarks/aligner.mjs [genomes=16] [bases=100000]
import createMauve from '../mauve_web/static/wasm/progressiveMauve.mjs';
import {parseXMFA} from '../mauve_web/static/browser/core.mjs';
const genomes=Number(process.argv[2]||16), bases=Number(process.argv[3]||100000);
if(!Number.isInteger(genomes)||genomes<2||genomes>64||!Number.isInteger(bases)||bases<50)throw Error('Use 2–64 genomes and at least 50 bases.');
const module=await createMauve({noInitialRun:true,print:()=>{},printErr:()=>{}});
let seed=12345;const dna=new Uint8Array(bases), alphabet=new TextEncoder().encode('ACGT');
for(let i=0;i<bases;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;dna[i]=alphabet[seed>>>30];}
const names=[];
for(let g=0;g<genomes;g++){
 const copy=dna.slice();for(let i=100+g;i<bases;i+=997)copy[i]=alphabet[(g+i)%4];
 const path=`/genome-${g}.fa`;names.push(path);module.FS.writeFile(path, '>genome\n'+new TextDecoder().decode(copy)+'\n');
}
const start=performance.now();const exit=module.callMain(['--output=/alignment.xmfa',...names]);const alignment_ms=performance.now()-start;
if(exit!==0)throw Error('Alignment failed: '+exit);
const blob=new Blob([module.FS.readFile('/alignment.xmfa')]);
const meta=await parseXMFA(blob,()=>{});
console.log(JSON.stringify({genomes,bases,alignment_ms,output_bytes:blob.size,block_count:meta.block_count,
 complete_extents:meta.genomes.length===genomes&&meta.genomes.every(g=>g.extent===bases),peak_process_rss_kib:process.resourceUsage().maxRSS},null,2));

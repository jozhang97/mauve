"""Benchmark a running static build. Requires requirements-browser.txt.
Example: .venv/bin/python benchmarks/browser.py --url http://127.0.0.1:8766 --headful
"""
import argparse
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True)
parser.add_argument('--genomes', type=int, default=32)
parser.add_argument('--columns', type=int, default=1000000)
parser.add_argument('--headful', action='store_true', help='Use a visible browser to measure the actual GPU on macOS')
args = parser.parse_args()
with sync_playwright() as p:
    executable = os.environ.get('MAUVE_CHROME_PATH')
    if not executable and Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').exists():
        executable = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    browser = p.chromium.launch(headless=not args.headful, **({'executable_path': executable} if executable else {}))
    page = browser.new_page()
    page.goto(args.url)
    result = page.evaluate('''async ({genomes, columns}) => {
      const {Accelerator} = await import('./static/browser/gpu.mjs');
      const {pairCounts, indexMember, coordinateColumn} = await import('./static/browser/core.mjs');
      const gpu = new Accelerator(); await gpu.ready;
      const scans=[];
      for (const n of [1000000, 4000000, 16000000, 32000000]) {
        const a=new Uint8Array(n),b=new Uint8Array(n),alphabet=new TextEncoder().encode('ACGTN-RY');
        for(let i=0;i<n;i++){a[i]=alphabet[i%8];b[i]=alphabet[(i+(i%17===0?1:0))%8];}
        const width=Math.ceil(n/100),cpuTimes=[],gpuTimes=[];
        let correct=true;
        for(let r=0;r<4;r++) {
          let start=performance.now();const expected=pairCounts(a,b,width);const cpu=performance.now()-start;
          if(r)cpuTimes.push(cpu);
          if(gpu.device){start=performance.now();const actual=await gpu.gpuCounts(a,b,width);const elapsed=performance.now()-start;
            correct &&= expected.every((v,i)=>v===actual[i]);if(r)gpuTimes.push(elapsed);}
        }
        const median=a=>a.sort((x,y)=>x-y)[Math.floor(a.length/2)];
        scans.push({columns:n,cpu_ms:median(cpuTimes),gpu_ms:gpuTimes.length?median(gpuTimes):null,correct});
      }
      const chunks=[];const sequence='ACGT'.repeat(Math.ceil(columns/4)).slice(0,columns);
      for(let g=1;g<=genomes;g++) chunks.push(`> ${g}:1-${columns} + genome-${g}.fa\\n`,sequence,'\\n');chunks.push('=\\n');
      const raw=new Blob(chunks);let start=performance.now();
      const alignment=await mauveBrowser.request('/api/alignments?name=Scaling%20benchmark',{method:'POST',body:raw});const import_ms=performance.now()-start;
      start=performance.now();const profile=await mauveBrowser.request(`/api/alignments/${alignment.id}/blocks/1/profile?reference_id=1`);const profile_ms=performance.now()-start;
      start=performance.now();await mauveBrowser.request(`/api/alignments/${alignment.id}/blocks/1/profile?reference_id=1`);const cached_profile_ms=performance.now()-start;
      start=performance.now();const page=await mauveBrowser.request(`/api/alignments/${alignment.id}/blocks/1?offset=${columns-100}&limit=100`);const page_ms=performance.now()-start;
      const member=indexMember({sequence,genome_id:1,start:1,end:columns,strand:'-'});start=performance.now();
      for(let i=0;i<10000;i++)coordinateColumn(member,1+((i*7919)%columns));const jumps_ms=performance.now()-start;
      const result={mode:gpu.mode,adapter:gpu.adapter,genomes,columns,scans,import_ms,profile_ms,cached_profile_ms,page_ms,jumps_10000_ms:jumps_ms,
        correct:profile.members.every(m=>m.matches===columns&&m.substitutions===0)&&page.members.every(m=>m.positions[0]===columns-99)};
      gpu.device?.destroy();return result;
    }''', {'genomes': args.genomes, 'columns': args.columns})
    print(json.dumps(result, indent=2))
    browser.close()

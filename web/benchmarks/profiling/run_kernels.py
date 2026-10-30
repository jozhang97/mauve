"""Compare native and real-browser kernels, including exact score/path checksums."""
import argparse
import functools
import http.server
import json
from pathlib import Path
import re
import subprocess
import threading
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--native',type=Path,required=True)
p.add_argument('--browser',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
power={'native_before':subprocess.check_output(['pmset','-g','batt'],text=True)}
logs={'native':subprocess.check_output([str(a.native.resolve())],text=True,timeout=120)}
power['native_after']=subprocess.check_output(['pmset','-g','batt'],text=True)
class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy','same-origin')
        self.send_header('Cross-Origin-Embedder-Policy','credentialless')
        super().end_headers()
    def log_message(self,*args):pass
(a.browser/'driver.mjs').write_text('''import createModule from './kernels.mjs';
let log='';
const print=s=>{log+=s+'\\n';};
await createModule({print,printErr:print,onExit:code=>self.postMessage({code,log}),onAbort:message=>self.postMessage({code:-1,log:log+message})});
''')
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(a.browser)))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        page=browser.new_page();page.goto(f'http://127.0.0.1:{server.server_port}/')
        power['browser_before']=subprocess.check_output(['pmset','-g','batt'],text=True)
        result=page.evaluate('''()=>new Promise((resolve,reject)=>{
          const worker=new Worker('/driver.mjs',{type:'module'});
          const timer=setTimeout(()=>{worker.terminate();reject(Error('kernel timeout'));},120000);
          worker.onmessage=({data})=>{clearTimeout(timer);worker.terminate();resolve(data);};
          worker.onerror=e=>{clearTimeout(timer);worker.terminate();reject(Error(e.message));};
        })''')
        power['browser_after']=subprocess.check_output(['pmset','-g','batt'],text=True)
        assert result['code']==0,result
        logs['browser']=result['log']
        version=browser.version
        browser.close()
finally:server.shutdown();server.server_close()
rows=[]
expected={}
for target,log in logs.items():
    assert 'VALIDATION coverage' in log,log
    for name,repeat,ms,checksum in re.findall(r'KERNEL (\w+) (\d+) ([\d.]+) (\S+)',log):
        key='coverage' if name.startswith('coverage_') else name
        if key in expected:assert checksum==expected[key],(target,name,checksum,expected[key])
        expected[key]=checksum
        rows.append({'target':target,'kernel':name,'repeat':int(repeat),'ms':float(ms),'checksum':checksum})
report={'power':power,'browser':version,'rows':rows,'all_checksums_match':True,'validation':'100 randomized matrices plus exhaustive small range boundaries per target. Native and browser NW scores/path checksums match. Coverage timing uses 32x100000 bases with 20 overlapping ungapped matches; NW timings include 30 calls, after one warmup.','raw_logs':logs}
a.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(rows,indent=2))

"""Compare the browser port with the existing Python and native implementations."""
import json
import os
from pathlib import Path
import random
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mauve_web.xmfa import parse_xmfa, column_slice, identity_profile, next_difference
from mauve_web.annotations import parse_genbank


def node(script, value):
    return json.loads(subprocess.check_output(['node', '--input-type=module', '-e', script], input=json.dumps(value), text=True, cwd=ROOT))


def test_browser_math_matches_python_reference():
    rng = random.Random(9831)
    cases = []
    for _ in range(30):
        columns = rng.randrange(30, 10000)
        text = ''
        for gid in range(1, rng.randrange(3, 20)):
            seq = ''.join(rng.choices('ACGTN-RY', k=columns))
            start = gid * 100
            text += f'> {gid}:{start}-{start+len(seq.replace("-", ""))-1} {"+" if gid % 2 else "-"} g{gid}.fa\n{seq}\n'
        cases.append(text+'=\n')
    actual = node('''
      import {parseXMFA,columnSlice,profileMember,pairCounts,nextDifference} from './mauve_web/static/browser/core.mjs';
      let data='';for await(const s of process.stdin)data+=s;const output=[];
      for(const text of JSON.parse(data)){
        let block;await parseXMFA(new Blob([text]),b=>{block=b;});const width=Math.ceil(block.columns/37),ref=block.members[0];
        output.push({profile:{reference_id:1,present:true,members:block.members.slice(1).map(m=>profileMember(m,block.columns,width,pairCounts(m.sequence,ref.sequence,width)))},
          pages:block.members.map(m=>columnSlice(m,17,25)),next:nextDifference(block,23)});
      }console.log(JSON.stringify(output));
    ''', cases)
    for text, result in zip(cases, actual):
        block = parse_xmfa(text)['blocks'][0]
        assert result == {'profile': identity_profile(block, 1, 37), 'pages': [column_slice(m, 17, 25) for m in block['members']], 'next': next_difference(block, 23)}


def test_browser_genbank_matches_biopython_demo():
    text = (ROOT / 'demo.gbk').read_text()
    expected = parse_genbank(text, [m for b in parse_xmfa((ROOT / 'demo.alignment').read_text())['blocks'] for m in b['members'] if m['genome_id'] == 2], True)
    actual = node('''
      import {parseRecords,annotationData} from './mauve_web/static/browser/genbank.mjs';
      let data='';for await(const s of process.stdin)data+=s;
      const {sequence,...out}=annotationData(await parseRecords(new Blob([JSON.parse(data)])),true);console.log(JSON.stringify(out));
    ''', text)
    expected.pop('verified_bases')
    for f in expected['features']: f.pop('location')
    for f in actual['features']: f.pop('location')
    assert actual == expected


@pytest.mark.skipif(os.environ.get('MAUVE_NATIVE_TESTS') != '1', reason='Set MAUVE_NATIVE_TESTS=1 to compare the bundled native executable')
def test_wasm_alignment_matches_native(tmp_path):
    rng = random.Random(91)
    base = ''.join(rng.choices('ACGT', k=12000))
    reverse = base[4000:6000].translate(str.maketrans('ACGT', 'TGCA'))[::-1]
    other = base[:4000]+reverse+base[6000:8500]+'ACGTACGT'+base[8500:]
    names = ['first.fa', 'second.fa']
    texts = ['>first\n'+base+'\n', '>second\n'+other+'\n']
    for name, text in zip(names, texts): (tmp_path / name).write_text(text)
    executable = os.environ.get('MAUVE_ALIGNER', str(ROOT.parent / 'osx/progressiveMauve'))
    subprocess.run([executable, '--output=alignment.xmfa', *names], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    actual = node('''
      import create from './mauve_web/static/wasm/progressiveMauve.mjs';
      let data='';for await(const s of process.stdin)data+=s;const {names,texts}=JSON.parse(data);
      const m=await create({noInitialRun:true,print:()=>{},printErr:()=>{}});
      names.forEach((name,i)=>m.FS.writeFile('/'+name,texts[i]));m.callMain(['--output=/alignment.xmfa',...names.map(n=>'/'+n)]);
      console.log(JSON.stringify(m.FS.readFile('/alignment.xmfa',{encoding:'utf8'})));
    ''', {'names': names, 'texts': texts})
    expected = parse_xmfa((tmp_path / 'alignment.xmfa').read_text())
    actual = parse_xmfa(actual)
    assert actual == expected

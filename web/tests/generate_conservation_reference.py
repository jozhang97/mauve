"""Regenerate the Java oracle: JAVA_HOME=/path/to/jdk python tests/generate_conservation_reference.py.

Uses the repository's unmodified SimilarityIndex/ZoomHistogram with tiny input
adapters, so it does not require the legacy GUI dependencies.
"""
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ['JAVA_HOME']) / 'bin'
SOURCES = [ROOT / 'src/org/gel/mauve/SimilarityIndex.java', ROOT / 'src/org/gel/mauve/histogram/ZoomHistogram.java']
rng = random.Random(42)
ancestor = ''.join(rng.choice('ACGT') for _ in range(25000))
rows = [''.join(rng.choice('ACGT-NR') if rng.random() < .12 else base for base in ancestor) for _ in range(4)]
cases = [dict(name='identical', rows=['A'*40]*3),
         dict(name='mixed', rows=['ACGT-NRKMYSWBDHVNXACGTACGTACGTACGT', 'AC-TANACGTACGTACGTACGTACGTACGTACGT', 'ACGT-NACGTACGTACGTACGTACGTACGTACGT']),
         dict(name='missing', rows=['A'*40, 'A'*40, '-'*40]),
         dict(name='backbone', rows=['A'*40, 'A'*40, 'T'*40], backbone=[0,1]),
         dict(name='zoom', rows=rows), dict(name='reverse', rows=rows, reverse=[1, 3])]
with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    adapters = list((ROOT / 'web/tests/java_reference').rglob('*.java'))
    subprocess.run([JAVA/'javac', '-d', temp, *SOURCES, *adapters], check=True)
    for case in cases:
        assert len(set(map(len, case['rows']))) == 1, case['name']
        path = temp / 'rows'; path.write_text('\n'.join(case['rows']))
        case['expected'] = []
        for gid, row in enumerate(case['rows']):
            if len(row.replace('-', '')) <= 5:
                case['expected'].append(None); continue
            oriented = [row.translate(str.maketrans('ACGTRYKMSWBVDHNX-', 'TGCAYRMKSWVBHDNX-'))[::-1] for row in case['rows']] if gid in case.get('reverse', []) else case['rows']
            path.write_text('\n'.join(oriented))
            args = [JAVA/'java', '-cp', temp, 'org.gel.mauve.ConservationReference', path, str(gid)]
            if 'backbone' in case: args.append(','.join(map(str, case['backbone'])))
            case['expected'].append(json.loads(subprocess.check_output(args)))
fixture = dict(source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}, cases=cases)
(ROOT/'web/browser-tests/fixtures/conservation-java.json').write_text(json.dumps(fixture, separators=(',', ':'))+'\n')

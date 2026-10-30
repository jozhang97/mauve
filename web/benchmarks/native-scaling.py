"""Benchmark ARM64 thread scaling in fresh processes with exact artifact checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import statistics
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
CASES = [('similar', 12, 100000), ('divergent', 4, 20000), ('rearranged', 4, 50000), ('repeats', 4, 50000), ('ambiguous', 4, 20000)]

def benchmark(engine, output, threads, repeats, quick=False, genomes=None, bases=100000):
    cases = [(k, 4, 5000) for k, _, _ in CASES] if quick else CASES
    if genomes is not None:
        cases = [('similar', genomes, bases)]
    report = {'measured_at': datetime.now(timezone.utc).isoformat(), 'platform': platform.platform(),
              'engine': str(engine), 'engine_sha256': hashlib.sha256(engine.read_bytes()).hexdigest(),
              'timing': 'Whole native process wall time, including startup; each repetition reverses thread-count order.',
              'threads': threads, 'repeats': repeats, 'cases': []}
    with tempfile.TemporaryDirectory(prefix='mauve-native-bench-') as directory:
        work = Path(directory)
        for kind, count, length in cases:
            generator = "import {engineCase} from " + json.dumps((HERE / 'engine-cases.mjs').as_uri()) + ";console.log(JSON.stringify(engineCase(process.argv[1],Number(process.argv[2]),Number(process.argv[3]),12345)));"
            sequences = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', generator, kind, str(count), str(length)], text=True))
            for i, sequence in enumerate(sequences):
                (work / f'input-{i+1}.fa').write_text('>genome\n' + sequence + '\n')
            case = {'kind': kind, 'genomes': count, 'bases': length, 'runs': []}
            report['cases'].append(case)
            expected = None
            for repeat in range(repeats):
                for n in threads if repeat % 2 == 0 else threads[::-1]:
                    # Remove generated seed/index caches: every run starts equally cold.
                    for path in work.iterdir():
                        if not re.fullmatch(r'input-\d+\.fa', path.name):
                            path.unlink()
                    command = ['/usr/bin/time', '-l', '-o', str(work / 'time.txt'), str(engine),
                               '--output=alignment.xmfa', '--output-guide-tree=guide.tree', '--backbone-output=alignment.backbone',
                               *[f'input-{i+1}.fa' for i in range(count)]]
                    env = dict(os.environ, MAUVE_THREADS=str(n))
                    power_before = subprocess.check_output(["pmset", "-g", "batt"], text=True).strip() if platform.system() == "Darwin" else None
                    start = time.perf_counter()
                    child = subprocess.Popen(command, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        log, _ = child.communicate(timeout=600)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.communicate()
                        raise
                    code = child.returncode
                    (work / 'run.log').write_bytes(log)
                    elapsed = (time.perf_counter() - start) * 1000
                    if code:
                        raise RuntimeError((work / 'run.log').read_text()[-5000:])
                    artifacts = {}
                    for name in ['alignment.xmfa', 'guide.tree', 'alignment.backbone']:
                        data = (work / name).read_bytes()
                        artifacts[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    if expected is None:
                        expected = artifacts
                    if artifacts != expected:
                        raise RuntimeError(f'Output mismatch: {kind}, {n} threads, repeat {repeat}')
                    timing = (work / 'time.txt').read_text()
                    rss = int(re.search(r'(\d+)\s+maximum resident set size', timing)[1])
                    cpu = re.search(r'([\d.]+) real\s+([\d.]+) user\s+([\d.]+) sys', timing)
                    power_after = subprocess.check_output(['pmset', '-g', 'batt'], text=True).strip() if platform.system() == 'Darwin' else None
                    row = {'power_before': power_before, 'power_after': power_after, 'repeat': repeat, 'threads': n, 'wall_ms': elapsed, 'peak_rss_bytes': rss, 'artifacts': artifacts}
                    stages = {name: {'inclusive_ms': float(ms), 'calls': int(calls)} for name, ms, calls in re.findall(r'MAUVE_STAGE (\w+) ([\d.]+) (\d+)', log.decode())}
                    if stages:
                        row['stages'] = stages
                    if cpu:
                        row['cpu_seconds'] = float(cpu[2]) + float(cpu[3])
                        row['average_cpu_cores'] = row['cpu_seconds'] / (elapsed / 1000)
                    case['runs'].append(row)
                    print(f'{kind} {count}x{length} {n} threads: {elapsed:.1f} ms, {rss/1048576:.1f} MiB', flush=True)
                    output.write_text(json.dumps(report, indent=2) + '\n')
            case['median_ms'] = {str(n): statistics.median(r['wall_ms'] for r in case['runs'] if r['threads'] == n) for n in threads}
            case['artifacts_identical'] = True
            output.write_text(json.dumps(report, indent=2) + '\n')
    return report

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--threads', type=int, nargs='+', default=[1, 2, 4, 8, 16])
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--quick', action='store_true')
    p.add_argument('--genomes', type=int)
    p.add_argument('--bases', type=int, default=100000)
    a = p.parse_args()
    if a.repeats < 1 or any(n < 1 or n > 16 for n in a.threads) or (a.genomes is not None and not 2 <= a.genomes <= 128) or a.bases < 1000:
        p.error('Use 1–16 threads, positive repetitions, 2–128 genomes, and at least 1000 bases.')
    benchmark(a.engine.resolve(), a.output.resolve(), a.threads, a.repeats, a.quick, a.genomes, a.bases)

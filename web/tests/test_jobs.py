import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import time

import pytest
from fastapi.testclient import TestClient

from mauve_web.app import create_app
from mauve_web.xmfa import parse_xmfa
from Bio.Seq import Seq


@pytest.fixture
def fake_aligner(tmp_path):
    def make(mode='success'):
        path = tmp_path / f'aligner-{mode}'
        path.write_text(f'''#!{sys.executable}
import sys,time
from pathlib import Path
if '--version' in sys.argv:
    print('progressiveMauve test engine');sys.exit(0)
print('started',flush=True)
mode={mode!r}
if mode == 'slow': time.sleep(30)
if mode == 'failure': print('intentional failure',flush=True);sys.exit(7)
if mode == 'missing': sys.exit(0)
if mode == 'malformed': Path('alignment.xmfa').write_text('not xmfa');sys.exit(0)
Path('alignment.xmfa').write_text('> 1:1-50 + genome_1.fasta\\n'+'A'*50+'\\n> 2:1-50 + genome_2.fasta\\n'+'A'*50+'\\n=\\n')
Path('guide.tree').write_text('(a,b);')
Path('alignment.backbone').write_text('seq0_leftend\\tseq0_rightend\\n1\\t50\\n')
print('finished',flush=True)
''')
        path.chmod(0o755)
        return str(path)
    return make


def upload_pair(client):
    ids = []
    for name in ('first.fa', 'second.fa'):
        response = client.post('/api/inputs', params={'name': name}, content='>a\n' + 'A'*50 + '\n')
        assert response.status_code == 201
        ids.append(response.json()['id'])
    return ids


def wait_job(client, jid, predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = client.get('/api/jobs/' + jid).json()
        if predicate(job):
            return job
        time.sleep(.03)
    pytest.fail(f'Job did not reach expected state: {job}')


def finished(client, jid):
    return wait_job(client, jid, lambda j: j['status'] in ('succeeded','failed','cancelled','interrupted'))


def test_success_provenance_downloads_and_persistence(tmp_path, fake_aligner):
    data = tmp_path / 'data'
    app = create_app(data, fake_aligner())
    with TestClient(app) as client:
        assert client.get('/api/engine').json()['available']
        ids = upload_pair(client)
        response = client.post('/api/jobs', json={'name': 'My experiment', 'input_ids': ids, 'collinear': True, 'min_weight': 100})
        assert response.status_code == 201
        jid = response.json()['id']
        job = finished(client, jid)
        assert job['status'] == 'succeeded'
        assert 'finished' in job['log']
        alignment = client.get('/api/alignments/' + job['alignment_id']).json()
        assert [g['name'] for g in alignment['genomes']] == ['first.fa', 'second.fa']
        manifest = client.get(f'/api/jobs/{jid}/artifacts/manifest').json()
        assert '--collinear' in manifest['command']
        assert '--weight=100' in manifest['command']
        assert manifest['command'][-2:] == ['genome_1.fasta', 'genome_2.fasta']
        assert len(manifest['inputs'][0]['sha256']) == 64
        assert len(manifest['executable_sha256']) == 64
        assert manifest['engine']['version'] == 'progressiveMauve test engine'
        for key in ('xmfa','tree','backbone','log'):
            assert client.get(f'/api/jobs/{jid}/artifacts/{key}').status_code == 200
        assert client.get(f'/api/jobs/{jid}/artifacts/secret').status_code == 404
        assert client.post(f'/api/jobs/{jid}/cancel').status_code == 409
    with TestClient(create_app(data, fake_aligner())) as restarted:
        assert restarted.get('/api/jobs').json()[0]['status'] == 'succeeded'
        assert restarted.get(f'/api/jobs/{jid}').json()['alignment_id'] == job['alignment_id']


@pytest.mark.parametrize('mode,message', [('failure','code 7'),('missing','without producing'),('malformed','Unexpected content')])
def test_failures_are_visible_without_importing(tmp_path, fake_aligner, mode, message):
    with TestClient(create_app(tmp_path / 'data', fake_aligner(mode))) as client:
        ids = upload_pair(client)
        jid = client.post('/api/jobs', json={'input_ids': ids}).json()['id']
        job = finished(client, jid)
        assert job['status'] == 'failed'
        assert message in job['error']
        assert client.get('/api/alignments').json() == []


def test_cancel_running_and_queued_jobs(tmp_path, fake_aligner):
    app = create_app(tmp_path / 'data', fake_aligner('slow'))
    with TestClient(app) as client:
        ids = upload_pair(client)
        first = client.post('/api/jobs', json={'input_ids': ids}).json()['id']
        wait_job(client, first, lambda j: 'started' in j['log'])
        process = app.state.jobs.process
        second = client.post('/api/jobs', json={'input_ids': ids}).json()['id']
        assert client.post(f'/api/jobs/{second}/cancel').json()['status'] == 'cancelled'
        assert client.post(f'/api/jobs/{first}/cancel').status_code == 200
        assert finished(client, first)['status'] == 'cancelled'
        assert process.poll() is not None
        assert client.get('/api/alignments').json() == []


def test_shutdown_interrupts_running_jobs_and_stops_process(tmp_path, fake_aligner):
    data = tmp_path / 'data'
    app = create_app(data, fake_aligner('slow'))
    with TestClient(app) as client:
        jid = client.post('/api/jobs', json={'input_ids': upload_pair(client)}).json()['id']
        wait_job(client, jid, lambda j: 'started' in j['log'])
        process = app.state.jobs.process
    assert process.poll() is not None
    with TestClient(create_app(data, fake_aligner())) as client:
        assert client.get('/api/jobs/'+jid).json()['status'] == 'interrupted'
        assert client.get('/api/alignments').json() == []


def test_startup_recovery_and_exclusive_worker(tmp_path, fake_aligner):
    data = tmp_path / 'data'
    app = create_app(data, fake_aligner())
    with sqlite3.connect(data / 'jobs/jobs.sqlite3') as db:
        db.execute("INSERT INTO jobs(id,name,status,created,spec) VALUES ('old','old','running','2026-01-01','{}')")
    with TestClient(app) as client:
        assert client.get('/api/jobs/old').json()['status'] == 'interrupted'
        with pytest.raises(RuntimeError, match='already has an alignment worker'):
            with TestClient(create_app(data, fake_aligner())):
                pass


def test_unavailable_engine_and_input_validation(tmp_path):
    with TestClient(create_app(tmp_path / 'data', str(tmp_path / 'missing'))) as client:
        assert not client.get('/api/engine').json()['available']
        ids = upload_pair(client)
        assert client.post('/api/jobs', json={'input_ids': ids}).status_code == 503
        for data in ('garbage', '>x\nAC-G\n', '>x\n' + 'X'*100, '>x\nACGT'):
            assert client.post('/api/inputs', content=data).status_code == 422
        assert client.get('/api/jobs/missing').status_code == 404


def test_job_options_and_record_concatenation(tmp_path, fake_aligner):
    with TestClient(create_app(tmp_path / 'data', fake_aligner())) as client:
        ids = upload_pair(client)
        for extra in ({'min_weight': -1}, {'arbitrary_command': 'echo'}, {'input_ids': ids[:1]}):
            assert client.post('/api/jobs', json={'input_ids': ids, **extra}).status_code == 422
        assert client.post('/api/jobs', json={'input_ids': [ids[0],ids[0]]}).status_code == 422
        assert client.post('/api/jobs', json={'input_ids': [ids[0],'missing']}).status_code == 404
        multi = client.post('/api/inputs', content='>a\n'+'A'*50+'\n>b\n'+'A'*50).json()
        assert multi['records'][1]['start'] == 51
        body = {'input_ids': [ids[0], multi['id']]}
        assert client.post('/api/jobs', json=body).status_code == 422
        result = client.post('/api/jobs', json={**body, 'concatenate_records': True})
        assert result.status_code == 201
        assert finished(client, result.json()['id'])['status'] == 'succeeded'


@pytest.mark.skipif(os.environ.get('MAUVE_NATIVE_TESTS') != '1', reason='Set MAUVE_NATIVE_TESTS=1 to test the installed aligner')
def test_real_progressivemauve(tmp_path):
    rng = random.Random(17)
    sequence = ''.join(rng.choices('ACGT', k=5000))
    alternate = 'A' if sequence[2000] != 'A' else 'C'
    changed = sequence[:2000] + alternate + sequence[2001:]
    with TestClient(create_app(tmp_path / 'data')) as client:
        assert client.get('/api/engine').json()['available']
        ids = [client.post('/api/inputs', content=f'>genome\n{s}\n').json()['id'] for s in (sequence, changed)]
        jid = client.post('/api/jobs', json={'input_ids': ids}).json()['id']
        job = wait_job(client, jid, lambda j: j['status'] in ('succeeded','failed'), seconds=60)
        assert job['status'] == 'succeeded', job['error']
        alignment = client.get('/api/alignments/'+job['alignment_id']).json()
        assert [g['extent'] for g in alignment['genomes']] == [5000,5000]
        blocks = client.get('/api/alignments/'+job['alignment_id']+'/blocks').json()
        assert any(len(b['members']) == 2 for b in blocks)
        exported = client.get(f'/api/jobs/{jid}/artifacts/xmfa').text
        for block in parse_xmfa(exported)['blocks']:
            for member in block['members']:
                original = (sequence, changed)[member['genome_id'] - 1]
                expected = original[member['start'] - 1:member['end']]
                if member['strand'] == '-':
                    expected = str(Seq(expected).reverse_complement())
                assert member['sequence'].replace('-', '') == expected


def test_retry_saved_result_without_rerunning(tmp_path, fake_aligner, monkeypatch):
    monkeypatch.setattr('mauve_web.jobs.MAX_OUTPUT', 8)
    app = create_app(tmp_path / 'data', fake_aligner())
    with TestClient(app) as client:
        ids = upload_pair(client)
        jid = client.post('/api/jobs', json={'input_ids': ids}).json()['id']
        job = finished(client, jid)
        assert job['status'] == 'failed' and job['can_import_result']
        directory = app.state.jobs.root / jid
        original_log = (directory / 'run.log').stat().st_mtime_ns
        original_output = (directory / 'alignment.xmfa').read_bytes()
        monkeypatch.setattr('mauve_web.jobs.MAX_OUTPUT', 256 * 1024 * 1024)
        # Exercise migration from the exact old 50 MiB error without a marker.
        (directory / 'aligner-completed.json').unlink()
        app.state.jobs.query('UPDATE jobs SET error=? WHERE id=?',
                            ('Alignment exceeds the viewer’s 50 MiB import limit. Download the XMFA output instead.', jid))
        recovered = client.post(f'/api/jobs/{jid}/import').json()
        assert recovered['status'] == 'succeeded'
        assert recovered['error'] is None
        assert client.post(f'/api/jobs/{jid}/import').json()['alignment_id'] == recovered['alignment_id']
        assert len(client.get('/api/alignments').json()) == 1
        assert (directory / 'run.log').stat().st_mtime_ns == original_log
        assert (directory / 'alignment.xmfa').read_bytes() == original_output
        genomes = client.get('/api/alignments/' + recovered['alignment_id']).json()['genomes']
        assert [g['name'] for g in genomes] == ['first.fa', 'second.fa']


def test_retry_import_rejects_failed_aligner(tmp_path, fake_aligner):
    with TestClient(create_app(tmp_path / 'data', fake_aligner('failure'))) as client:
        jid = client.post('/api/jobs', json={'input_ids': upload_pair(client)}).json()['id']
        assert not finished(client, jid)['can_import_result']
        assert client.post(f'/api/jobs/{jid}/import').status_code == 409

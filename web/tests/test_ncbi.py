import io
import json
import os
import time
import zipfile

from fastapi.testclient import TestClient
import httpx
import pytest

from mauve_web.app import create_app
from mauve_web.ncbi import NCBIClient

ACCESSION = 'GCF_000027325.1'
OTHER = 'GCF_000146045.2'


def report(accession=ACCESSION, bases=80):
    return {'accession': accession, 'paired_accession': 'GCA_000027325.1',
            'organism': {'tax_id':243273, 'organism_name':'Test organism', 'infraspecific_names': {'strain':'G37'}},
            'assembly_info': {'assembly_level':'Complete Genome', 'assembly_status':'current', 'assembly_name':'Example', 'release_date':'2020-01-01'},
            'assembly_stats': {'total_sequence_length':str(bases), 'number_of_contigs':1}}


def package(accession=ACCESSION, fasta=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f'ncbi_dataset/data/{accession}/{accession}_genomic.fna', fasta or '>chromosome\n'+'ACGT'*20+'\n')
        archive.writestr('../../untrusted.txt', 'never extract me')
    return stream.getvalue()


def install_client(app, handler):
    app.state.ncbi = NCBIClient(transport=httpx.MockTransport(handler), interval=0)


def test_taxon_search_filters_pagination_and_cache(tmp_path):
    app = create_app(tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        if '/taxonomy/' in request.url.path:
            return httpx.Response(200, json={'reports':[{'taxonomy':{'tax_id':2097,'rank':'SPECIES','current_scientific_name':{'name':'Mycoplasmoides genitalium'}}}]})
        params = request.url.params
        assert params['filters.assembly_source'] == 'refseq'
        assert params['filters.assembly_version'] == 'all_assemblies'
        assert params['tax_exact_match'] == 'true'
        assert params['filters.search_text'] == 'G37'
        if params.get('page_token'):
            assert params['page_token'] == 'next-token'
            return httpx.Response(200, json={'reports':[report(OTHER)],'total_count':2})
        return httpx.Response(200, json={'reports':[report()],'total_count':2,'next_page_token':'next-token'})
    install_client(app, handler)
    client = TestClient(app)
    params = {'taxon_id':2097,'source':'refseq','versions':'all_assemblies','exact':True,'q':'G37','page_size':1}
    first = client.get('/api/ncbi/assemblies', params=params)
    assert first.status_code == 200
    data = first.json()
    assert data['taxon']['name'] == 'Mycoplasmoides genitalium'
    assert data['assemblies'][0]['paired_accession'] == 'GCA_000027325.1'
    assert data['assemblies'][0]['bases'] == 80
    assert not data['includes_descendants']
    second = client.get('/api/ncbi/assemblies', params={**params,'page_token':data['next_page_token']}).json()
    assert second['assemblies'][0]['accession'] == OTHER
    assert second['next_page_token'] == ''
    assert sum('/taxonomy/' in r.url.path for r in requests) == 1


def test_download_stages_fasta_and_provenance_without_extracting_paths(tmp_path):
    app = create_app(tmp_path)
    def handler(request):
        if request.url.path.endswith('/download'):
            assert request.url.params['include_annotation_type'] == 'GENOME_FASTA'
            return httpx.Response(200, content=package())
        return httpx.Response(200, json={'reports':[report()]})
    install_client(app, handler)
    client = TestClient(app)
    response = client.post(f'/api/ncbi/assemblies/{ACCESSION}/input')
    assert response.status_code == 201
    data = response.json()
    assert data['bases'] == 80
    assert data['name'] == ACCESSION+'.fna'
    assert data['provenance']['accession'] == ACCESSION
    assert data['provenance']['provider'] == 'NCBI Datasets'
    assert 'api-key' not in json.dumps(data)
    assert len(data['sha256']) == 64
    assert not list(tmp_path.rglob('untrusted.txt'))
    stored = app.state.jobs.query('SELECT data FROM inputs WHERE id=?', (data['id'],))[0]['data']
    assert json.loads(stored)['provenance']['accession'] == ACCESSION


@pytest.mark.parametrize('status,expected', [(429,429),(503,502),(404,422),(400,422)])
def test_upstream_errors(tmp_path, status, expected):
    app = create_app(tmp_path)
    install_client(app, lambda request: httpx.Response(status))
    response = TestClient(app).get('/api/ncbi/assemblies?taxon_id=2097')
    assert response.status_code == expected
    assert 'NCBI' in response.json()['detail']


def test_invalid_ids_and_empty_taxa(tmp_path):
    app = create_app(tmp_path)
    install_client(app, lambda request: httpx.Response(200,json={}))
    client = TestClient(app)
    for query in ('taxon_id=0','taxon_id=nope','taxon_id=1&source=other','taxon_id=1&page_size=1001'):
        assert client.get('/api/ncbi/assemblies?'+query).status_code == 422
    assert client.get('/api/ncbi/assemblies?taxon_id=999999').status_code == 404
    assert client.post('/api/ncbi/assemblies/not-an-accession/input').status_code == 422
    assert client.post(f'/api/ncbi/assemblies/{ACCESSION}/input').status_code == 404


@pytest.mark.parametrize('kind,expected', [('oversized',413),('wrong-accession',502),('bad-zip',502),('bad-fasta',422),('substitution',404)])
def test_download_rejects_unusable_packages(tmp_path, kind, expected):
    app = create_app(tmp_path)
    def handler(request):
        if request.url.path.endswith('/download'):
            content = b'not zip' if kind == 'bad-zip' else package(OTHER if kind == 'wrong-accession' else ACCESSION, 'invalid' if kind == 'bad-fasta' else None)
            return httpx.Response(200,content=content)
        return httpx.Response(200,json={'reports':[report(OTHER if kind == 'substitution' else ACCESSION, bases=100_000_000 if kind=='oversized' else 80)]})
    install_client(app, handler)
    assert TestClient(app).post(f'/api/ncbi/assemblies/{ACCESSION}/input').status_code == expected
    assert app.state.jobs.query('SELECT * FROM inputs') == []


def test_empty_assembly_results_are_not_a_missing_taxon(tmp_path):
    app=create_app(tmp_path)
    def handler(request):
        if '/taxonomy/' in request.url.path:
            return httpx.Response(200,json={'reports':[{'taxonomy':{'tax_id':1,'current_scientific_name':{'name':'root'}}}]})
        return httpx.Response(200,json={})
    install_client(app,handler)
    data=TestClient(app).get('/api/ncbi/assemblies?taxon_id=1').json()
    assert data['total']==0 and data['assemblies']==[]


@pytest.mark.skipif(os.environ.get('MAUVE_NCBI_TESTS')!='1', reason='Set MAUVE_NCBI_TESTS=1 for real NCBI requests')
def test_live_ncbi_search_and_download(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        result=client.get('/api/ncbi/assemblies',params={'taxon_id':2097,'source':'refseq','page_size':2})
        assert result.status_code==200, result.text
        assert result.json()['total']>=1
        response=client.post(f'/api/ncbi/assemblies/{ACCESSION}/input')
        assert response.status_code==201, response.text
        assert response.json()['bases']>500_000
        assert response.json()['provenance']['accession']==ACCESSION


@pytest.mark.skipif(os.environ.get('MAUVE_NCBI_TESTS') != '1' or os.environ.get('MAUVE_NATIVE_TESTS') != '1',
                    reason='Requires live NCBI downloads and a native aligner')
def test_real_ncbi_genomes_to_alignment(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        ids = []
        for accession in ('GCF_000027325.1', 'GCF_054926455.1'):
            response = client.post(f'/api/ncbi/assemblies/{accession}/input')
            assert response.status_code == 201, response.text
            ids.append(response.json()['id'])
        response = client.post('/api/jobs', json={'input_ids':ids, 'name':'NCBI integration', 'concatenate_records':True})
        assert response.status_code == 201, response.text
        jid = response.json()['id']
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = client.get('/api/jobs/' + jid).json()
            if job['status'] in ('succeeded', 'failed'):
                break
            time.sleep(.2)
        assert job['status'] == 'succeeded', job
        alignment = client.get('/api/alignments/' + job['alignment_id']).json()
        assert len(alignment['genomes']) == 2
        assert all(g['extent'] > 500_000 for g in alignment['genomes'])
        manifest = client.get(f'/api/jobs/{jid}/artifacts/manifest').json()
        assert [i['provenance']['accession'] for i in manifest['inputs']] == ['GCF_000027325.1', 'GCF_054926455.1']

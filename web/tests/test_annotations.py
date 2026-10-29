from io import StringIO
from pathlib import Path

import pytest
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation, CompoundLocation, BeforePosition
from Bio.SeqRecord import SeqRecord
from fastapi.testclient import TestClient

from mauve_web.annotations import parse_genbank
from mauve_web.app import create_app
from mauve_web.xmfa import parse_xmfa

ROOT = Path(__file__).resolve().parents[1]
XMFA = '> 1:1-4 +\nACGT\n> 2:1-4 -\nACGT\n=\n'


def genbank(sequences=('ACGT',), locations=None):
    records = []
    for i, sequence in enumerate(sequences):
        record = SeqRecord(Seq(sequence), id=f'contig{i+1}', name=f'contig{i+1}', annotations={'molecule_type': 'DNA'})
        location = locations[i] if locations else SimpleLocation(0, len(sequence), strand=-1)
        record.features = [SeqFeature(location, type='CDS', qualifiers={
            'gene': ['testGene'], 'locus_tag': [f'LOC_{i}'], 'product': ['test enzyme'], 'note': ['A long annotation that spans multiple lines in the GenBank feature table when exported to a file']})]
        records.append(record)
    output = StringIO()
    SeqIO.write(records, output, 'genbank')
    return output.getvalue()


def test_real_multirecord_fixture_mapping():
    members = [m for b in parse_xmfa((ROOT / 'demo.alignment').read_text())['blocks']
               for m in b['members'] if m['genome_id'] == 2]
    text = (ROOT / 'demo.gbk').read_text()
    with pytest.raises(ValueError, match='multiple records'):
        parse_genbank(text, members)
    result = parse_genbank(text, members, concatenate=True)
    assert result['length'] == 2000
    assert result['records'][1]['start'] == 1001
    assert result['verified_bases'] == 2000
    telomere = next(f for f in result['features'] if f['name'] == 'TEL01L-TR')
    assert (telomere['start'], telomere['end'], telomere['strand']) == (1, 62, '-')
    assert any(f['start'] > 1000 for f in result['features'])


def test_compound_fuzzy_reverse_and_offset():
    location = CompoundLocation([SimpleLocation(0, 2, strand=-1), SimpleLocation(4, 6, strand=-1)])
    text = genbank(('ACGTAC', 'GATT'), [location, SimpleLocation(BeforePosition(0), 4, strand=1)])
    result = parse_genbank(text, [{'start': 1, 'end': 6, 'strand': '-', 'sequence': 'GTACGT'}], True)
    assert [(p['start'], p['end']) for p in result['features'][0]['parts']] == [(1, 2), (5, 6)]
    assert result['features'][1]['start'] == 7
    assert result['features'][1]['end'] == 10
    assert result['features'][1]['parts'][0]['fuzzy'] is True


@pytest.mark.parametrize('text,members,message', [
    ('bad', [], 'No GenBank'),
    (genbank(), [{'start': 1, 'end': 5, 'strand': '+', 'sequence': 'ACGTT'}], 'shorter'),
    (genbank(), [{'start': 1, 'end': 4, 'strand': '+', 'sequence': 'AAAA'}], 'does not match'),
    (genbank(('NNNN',)), [{'start': 1, 'end': 4, 'strand': '+', 'sequence': 'NNNN'}], 'No unambiguous'),
])
def test_rejects_wrong_source(text, members, message):
    with pytest.raises(ValueError, match=message):
        parse_genbank(text, members)


def test_annotation_api_search_persistence_and_atomic_replace(tmp_path):
    client = TestClient(create_app(tmp_path))
    aid = client.post('/api/alignments', content=XMFA).json()['id']
    path = f'/api/alignments/{aid}'
    endpoint = f'{path}/genomes/2/annotations'
    response = client.post(endpoint, content=genbank())
    assert response.status_code == 200
    assert response.json()['verified_bases'] == 4
    for q in ('testgene', 'TESTGENE', 'LOC_0', 'enzyme', 'contig1'):
        result = client.get(f'{path}/features', params={'q': q, 'genome_id': 2}).json()
        assert result['total'] == 1
        assert result['items'][0]['strand'] == '-'
    assert client.get(f'{path}/features?q=%25').json()['total'] == 0
    assert client.get(f'{path}/features?genome_id=1').json()['total'] == 0
    assert client.get(f'{path}/features?start=5').json()['total'] == 0
    assert client.get(f'{path}/features?start=4&end=2').status_code == 422
    assert client.get(f'{path}/features?genome_id=99').status_code == 404
    assert client.get(f'{path}/features?limit=501').status_code == 422
    assert client.post(endpoint, content=genbank(('AAAA',))).status_code == 422
    assert client.get(f'{path}/features').json()['total'] == 1
    assert client.post(endpoint, content=genbank()).status_code == 200
    assert client.get(f'{path}/features').json()['total'] == 1  # replace, not duplicate
    restarted = TestClient(create_app(tmp_path))
    assert restarted.get(f'{path}/annotations').json()[0]['metadata']['feature_count'] == 1
    assert restarted.get(f'{path}/features').json()['total'] == 1
    assert client.post(f'{path}/genomes/99/annotations', content=genbank()).status_code == 404


def test_pagination_and_alignment_isolation(tmp_path):
    client = TestClient(create_app(tmp_path))
    aid = client.post('/api/demo').json()['id']
    base = f'/api/alignments/{aid}/features'
    first = client.get(base, params={'limit': 1}).json()
    second = client.get(base, params={'limit': 1, 'offset': 1}).json()
    assert first['total'] > 1
    assert first['items'][0]['id'] != second['items'][0]['id']
    other = client.post('/api/alignments', content=XMFA).json()['id']
    assert client.get(f'/api/alignments/{other}/features').json()['total'] == 0


def test_downloads_preserve_alignment_orientation_and_gaps(tmp_path):
    client = TestClient(create_app(tmp_path))
    text = '> 1:10-12 +\nAC-G\n> 2:21-23 -\nA-TG\n=\n'
    aid = client.post('/api/alignments', content=text).json()['id']
    response = client.get(f'/api/alignments/{aid}/blocks/1/fasta')
    assert response.status_code == 200
    assert response.headers['content-disposition'].startswith('attachment;')
    assert '>sequence_2 block=1 coordinates=21-23 strand=-\nA-TG\n' in response.text
    records = list(SeqIO.parse(StringIO(response.text), 'fasta'))
    assert [str(r.seq) for r in records] == ['AC-G', 'A-TG']
    table = client.get(f'/api/alignments/{aid}/blocks.tsv')
    assert '1\t4\t2\t21\t23\t-\n' in table.text
    assert 'start_1based' in table.text
    assert client.get(f'/api/alignments/{aid}/blocks/999/fasta').status_code == 404
    assert client.get('/api/alignments/missing/blocks.tsv').status_code == 404

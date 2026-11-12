"""Server CDS checksums must match the browser's strand/rotation contract."""
import json
from io import StringIO
from pathlib import Path
import pytest
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation, CompoundLocation
from Bio.SeqRecord import SeqRecord
from mauve_web.annotations import parse_genbank


@pytest.mark.parametrize('strand', [1, -1])
@pytest.mark.parametrize('rotation', [0, 17])
def test_coding_sequence_hash_survives_rotation_and_compound_strand(strand, rotation):
    fixture = json.loads((Path(__file__).resolve().parents[1] / 'data/essentiality/test-cds.json').read_text())[0]
    sequence = Seq(fixture['sequence'])
    if strand == -1:
        sequence = sequence.reverse_complement()
    record = SeqRecord(sequence, id='chr', annotations={'molecule_type':'DNA', 'topology':'circular'})
    parts = [SimpleLocation(0, 30, strand=strand), SimpleLocation(30, len(sequence), strand=strand)]
    if strand == -1:
        parts.reverse()
    record.features = [SeqFeature(CompoundLocation(parts), type='CDS')]
    out = StringIO(); SeqIO.write(record, out, 'genbank')
    rotated = sequence[rotation:] + sequence[:rotation]
    parsed = parse_genbank(out.getvalue(), [{'start':1, 'end':len(sequence), 'strand':'+', 'sequence':str(rotated)}], rotation=rotation)
    assert parsed['features'][0]['sequence_sha256'] == fixture['sha256']

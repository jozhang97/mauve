"""Build same-origin accession shards from DoriC's official CSV export."""
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

URL = 'https://tubic.org/doric/download/filtered.csv'


def update(output):
    output = Path(output)
    shards = {}
    with urlopen(URL, timeout=120) as response:
        reader = csv.DictReader(io.TextIOWrapper(response, encoding='utf-8-sig'))
        if not {'nc', 'orics', 'domain', 'topology', 'genome_type', 'seq_size', 'ori_id'}.issubset(reader.fieldnames or []):
            raise ValueError('Unexpected DoriC export schema')
        for row in reader:
            if row['domain'] != 'Bacteria' or row['genome_type'] != 'Chromosome' or row['topology'] != 'Circular':
                continue
            accession = row['nc']
            key = hashlib.sha256(accession.encode()).hexdigest()[:2]
            entries = shards.setdefault(key, {}).setdefault(accession, [])
            for origin in json.loads(row['orics']):
                entries.append({'id': row['ori_id'], 'start': origin['oric_start'],
                                'end': origin['oric_end'], 'length': int(row['seq_size']),
                                'sequence': origin['oric_seq'].upper()})
    if not shards:
        raise ValueError('DoriC export contained no circular bacterial chromosomes')
    output.mkdir(parents=True, exist_ok=True)
    for i in range(256):
        key = f'{i:02x}'
        target = output / f'{key}.json'
        temporary = output / f'{key}.json.tmp'
        temporary.write_text(json.dumps({'release': 'DoriC 14.0',
            'source': URL, 'records': shards.get(key, {})}, separators=(',', ':')))
        temporary.replace(target)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    update(parser.parse_args().output)

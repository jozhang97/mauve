"""Bounded NCBI Datasets queries and accession-specific genome downloads."""
from datetime import datetime, timezone
import io
import json
import os
import re
import threading
import time
import zipfile

import httpx
from fastapi import HTTPException

BASE = 'https://api.ncbi.nlm.nih.gov/datasets/v2'
ACCESSION = re.compile(r'^GC[AF]_\d{9}\.\d+$')
MAX_FASTA = 50 * 1024 * 1024
MAX_PACKAGE = 55 * 1024 * 1024


def assembly_summary(report):
    organism, info, stats = (report.get(k, {}) for k in ('organism', 'assembly_info', 'assembly_stats'))
    return {
        'accession': report['accession'], 'organism': organism.get('organism_name', ''),
        'taxon_id': organism.get('tax_id'), 'strain': organism.get('infraspecific_names', {}).get('strain', ''),
        'name': info.get('assembly_name', ''), 'level': info.get('assembly_level', ''),
        'status': info.get('assembly_status', ''), 'release_date': info.get('release_date', ''),
        'source': 'RefSeq' if report['accession'].startswith('GCF_') else 'GenBank',
        'paired_accession': report.get('paired_accession') or info.get('paired_assembly', {}).get('accession'),
        'reference_category': info.get('refseq_category', ''),
        'bases': int(stats.get('total_sequence_length', 0)),
        'contigs': stats.get('number_of_contigs'), 'contig_n50': stats.get('contig_n50'),
        'url': f"https://www.ncbi.nlm.nih.gov/datasets/genome/{report['accession']}/",
    }


class NCBIClient:
    def __init__(self, transport=None, interval=.35):
        self.transport = transport
        self.interval = interval
        self.rate_lock = threading.Lock()
        self.last_request = 0
        self.cache_lock = threading.Lock()
        self.taxon_cache = {}
        self.download_slots = threading.BoundedSemaphore(2)

    def _fetch(self, endpoint, params=None, limit=8 * 1024 * 1024):
        # Keep this process comfortably below the unauthenticated API rate limit.
        with self.rate_lock:
            delay = self.interval - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
        headers = {'User-Agent': 'MauveExplorer/0.4 (NCBI Datasets client)'}
        if os.environ.get('NCBI_API_KEY'):
            headers['api-key'] = os.environ['NCBI_API_KEY']
        try:
            deadline = time.monotonic() + 180
            with httpx.Client(transport=self.transport, timeout=httpx.Timeout(60, connect=15), follow_redirects=True) as client:
                with client.stream('GET', BASE + endpoint, params=params, headers=headers) as response:
                    if response.status_code == 429:
                        raise HTTPException(429, 'NCBI is rate limiting requests. Wait a moment and try again.')
                    if response.status_code in (400, 404):
                        raise HTTPException(422, 'NCBI could not resolve this taxon, accession, or query. Check the identifier and filters.')
                    if response.status_code != 200:
                        raise HTTPException(502, f'NCBI returned HTTP {response.status_code}. Please try again later.')
                    data = bytearray()
                    for chunk in response.iter_bytes(64 * 1024):
                        if time.monotonic() > deadline:
                            raise HTTPException(504, 'NCBI download took too long. Please try again.')
                        if len(data) + len(chunk) > limit:
                            raise HTTPException(413, 'NCBI response exceeds the current download size limit.')
                        data.extend(chunk)
                    return bytes(data)
        except httpx.TimeoutException as exc:
            raise HTTPException(504, 'NCBI did not respond in time. Please try again.') from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, 'Could not connect to NCBI. Check the server’s network connection.') from exc

    def _json(self, endpoint, params=None):
        try:
            data = json.loads(self._fetch(endpoint, params))
            if not isinstance(data, dict):
                raise ValueError('Expected object')
            return data
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(502, 'NCBI returned an invalid metadata response.') from exc

    def taxonomy(self, taxid):
        with self.cache_lock:
            cached = self.taxon_cache.get(taxid)
            if cached and cached[0] > time.monotonic():
                return cached[1]
        data = self._json(f'/taxonomy/taxon/{taxid}/dataset_report')
        records = [r['taxonomy'] for r in data.get('reports', []) if r.get('taxonomy')]
        if not records:
            raise HTTPException(404, f'NCBI taxonomy ID {taxid} was not found.')
        record = records[0]
        result = {'id': record.get('tax_id', taxid), 'name': record.get('current_scientific_name', {}).get('name', ''),
                  'rank': record.get('rank', '').lower()}
        with self.cache_lock:
            if len(self.taxon_cache) >= 128:
                self.taxon_cache.pop(next(iter(self.taxon_cache)))
            self.taxon_cache[taxid] = (time.monotonic() + 300, result)
        return result

    def search(self, taxid, source='all', exact=False, versions='current', query='', page_token='', page_size=25):
        taxon = self.taxonomy(taxid)
        params = {'page_size': page_size, 'tax_exact_match': str(exact).lower(),
                  'filters.assembly_source': source, 'filters.assembly_version': versions}
        if query:
            params['filters.search_text'] = query
        if page_token:
            params['page_token'] = page_token
        data = self._json(f'/genome/taxon/{taxid}/dataset_report', params)
        try:
            rows = [assembly_summary(r) for r in data.get('reports', [])]
            total = int(data.get('total_count', 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(502, 'NCBI returned unexpected assembly metadata.') from exc
        return {'taxon': taxon, 'assemblies': rows, 'total': total,
                'next_page_token': data.get('next_page_token', ''), 'includes_descendants': not exact}

    def download(self, accession, add_input):
        if not ACCESSION.fullmatch(accession):
            raise HTTPException(422, 'Use a versioned assembly accession, such as GCF_000027325.1.')
        if not self.download_slots.acquire(blocking=False):
            raise HTTPException(429, 'Two NCBI downloads are already in progress. Please try again shortly.')
        try:
            report = self._json(f'/genome/accession/{accession}/dataset_report')
            matches = [r for r in report.get('reports', []) if r.get('accession') == accession]
            if len(matches) != 1:
                raise HTTPException(404, 'NCBI did not return the requested assembly version; no substitute was downloaded.')
            try:
                summary = assembly_summary(matches[0])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(502, 'NCBI returned unexpected assembly metadata.') from exc
            if summary['bases'] > MAX_FASTA:
                raise HTTPException(413, 'This genome exceeds the current 50 MiB per-input limit. It can be browsed but not aligned in this version.')
            url_path = f'/genome/accession/{accession}/download'
            archive = self._fetch(url_path, {'include_annotation_type': 'GENOME_FASTA'}, MAX_PACKAGE)
            try:
                with zipfile.ZipFile(io.BytesIO(archive)) as package:
                    # Read only the requested accession's genomic sequence, never extract paths.
                    files = [f for f in package.infolist() if
                             f.filename.startswith(f'ncbi_dataset/data/{accession}/') and f.filename.endswith('_genomic.fna')]
                    if len(files) != 1:
                        raise ValueError('Package must contain exactly one genomic FASTA for the requested accession.')
                    if files[0].file_size > MAX_FASTA:
                        raise HTTPException(413, 'The downloaded genomic FASTA exceeds the 50 MiB input limit.')
                    with package.open(files[0]) as stream:
                        raw = stream.read(MAX_FASTA + 1)
                    if len(raw) > MAX_FASTA:
                        raise HTTPException(413, 'The downloaded genomic FASTA exceeds the 50 MiB input limit.')
            except (ValueError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                raise HTTPException(502, f'NCBI returned an unusable genome package: {exc}') from exc
            provenance = {**summary, 'provider': 'NCBI Datasets', 'downloaded_at': datetime.now(timezone.utc).isoformat(),
                          'download_url': BASE + url_path + '?include_annotation_type=GENOME_FASTA'}
            return add_input(raw, f'{accession}.fna', provenance=provenance)
        finally:
            self.download_slots.release()

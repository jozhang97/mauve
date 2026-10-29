import json
import csv
import io
import os
import sqlite3
import uuid
import tempfile
from contextlib import closing, asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .xmfa import basename, column_slice, identity_profile, coordinate_column, iter_xmfa, next_difference
from .cache import BlockCache
from .annotations import parse_genbank
from .jobs import JobManager, JobRequest
from .limits import MAX_ALIGNMENT
from .ncbi import NCBIClient

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 50 * 1024 * 1024


def create_app(data_dir=None, aligner_path=None):
    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(jobs.start)
        try:
            yield
        finally:
            await run_in_threadpool(jobs.close)

    app = FastAPI(title='Mauve Explorer', version='0.4.0', lifespan=lifespan)
    storage = Path(data_dir or os.environ.get('MAUVE_DATA_DIR', ROOT / '.data'))
    storage.mkdir(parents=True, exist_ok=True)
    database = storage / 'alignments.sqlite3'
    block_cache = BlockCache()
    with closing(sqlite3.connect(database, timeout=30)) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS alignments (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP,
                genomes TEXT NOT NULL, block_count INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS blocks (
                alignment_id TEXT NOT NULL, id INTEGER NOT NULL, columns INTEGER NOT NULL,
                members TEXT NOT NULL, PRIMARY KEY (alignment_id, id));
            CREATE TABLE IF NOT EXISTS block_overviews (
                alignment_id TEXT NOT NULL, id INTEGER NOT NULL, columns INTEGER NOT NULL,
                members TEXT NOT NULL, PRIMARY KEY (alignment_id, id));
            CREATE TABLE IF NOT EXISTS annotation_sources (
                alignment_id TEXT NOT NULL, genome_id INTEGER NOT NULL,
                name TEXT NOT NULL, metadata TEXT NOT NULL,
                PRIMARY KEY (alignment_id, genome_id));
            CREATE TABLE IF NOT EXISTS features (
                id INTEGER PRIMARY KEY, alignment_id TEXT NOT NULL, genome_id INTEGER NOT NULL,
                start INTEGER NOT NULL, end INTEGER NOT NULL, search_text TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS feature_region ON features(alignment_id, genome_id, start, end);
        ''')

        # Upgrade existing libraries one block at a time; overview requests must
        # never deserialize all aligned DNA just to display coordinates.
        with db:
            for aid, bid, columns, encoded in db.execute(
                'SELECT b.* FROM blocks b LEFT JOIN block_overviews o '
                'ON b.alignment_id=o.alignment_id AND b.id=o.id WHERE o.id IS NULL'
            ):
                members = [{k: v for k, v in m.items() if k != 'sequence'} for m in json.loads(encoded)]
                db.execute('INSERT INTO block_overviews VALUES (?,?,?,?)',
                           (aid, bid, columns, json.dumps(members)))

    def query(sql, args=()):
        with closing(sqlite3.connect(database, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, args)]

    def get_alignment(aid):
        rows = query('SELECT * FROM alignments WHERE id=?', (aid,))
        if not rows:
            raise HTTPException(404, 'Alignment not found.')
        row = rows[0]
        row['genomes'] = json.loads(row['genomes'])
        return row

    def get_genome(aid, gid):
        genome = next((g for g in get_alignment(aid)['genomes'] if g['id'] == gid), None)
        if genome is None:
            raise HTTPException(404, 'Genome not found in this alignment.')
        return genome

    def get_block(aid, bid):
        def load():
            rows = query('SELECT * FROM blocks WHERE alignment_id=? AND id=?', (aid, bid))
            if not rows:
                raise HTTPException(404, 'Block not found.')
            b = rows[0]
            b['members'] = json.loads(b['members'])
            return b
        return block_cache.get((aid, bid), load)

    async def read_upload(request):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_UPLOAD:
                raise HTTPException(413, 'This version supports files up to 50 MiB.')
            raw.extend(chunk)
        return raw

    def save_annotations(aid, gid, raw, name, concatenate):
        get_genome(aid, gid)
        members = [m for b in query('SELECT members FROM blocks WHERE alignment_id=?', (aid,))
                   for m in json.loads(b['members']) if m['genome_id'] == gid]
        try:
            parsed = parse_genbank(raw.decode('utf-8-sig'), members, concatenate)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        metadata = {k: v for k, v in parsed.items() if k != 'features'}
        metadata['feature_count'] = len(parsed['features'])
        # A complete validated import replaces annotations atomically for this genome.
        with closing(sqlite3.connect(database, timeout=30)) as db, db:
            db.execute('DELETE FROM features WHERE alignment_id=? AND genome_id=?', (aid, gid))
            db.execute('INSERT OR REPLACE INTO annotation_sources VALUES (?,?,?,?)',
                       (aid, gid, basename(name)[:200], json.dumps(metadata)))
            db.executemany('INSERT INTO features(alignment_id,genome_id,start,end,search_text,data) VALUES (?,?,?,?,?,?)',
                           [(aid, gid, f['start'], f['end'],
                             ' '.join(f[k] for k in ('name', 'type', 'locus_tag', 'product', 'note', 'record')).casefold(),
                             json.dumps(f)) for f in parsed['features']])
        return metadata

    def save(raw, name, inputs=None):
        aid = uuid.uuid4().hex
        genomes = {}
        count = 0
        # Native jobs and uploads use disk streams. Bytes remain supported for
        # the small bundled demo and internal callers.
        stream = (raw.open('r', encoding='utf-8-sig') if isinstance(raw, Path)
                  else io.TextIOWrapper(io.BytesIO(raw), encoding='utf-8-sig'))
        try:
            with stream, closing(sqlite3.connect(database, timeout=30)) as db, db:
                for block in iter_xmfa(stream, genomes):
                    count += 1
                    overview = [{k: v for k, v in m.items() if k != 'sequence'} for m in block['members']]
                    db.execute('INSERT INTO blocks VALUES (?,?,?,?)',
                               (aid, block['id'], block['columns'], json.dumps(block['members'])))
                    db.execute('INSERT INTO block_overviews VALUES (?,?,?,?)',
                               (aid, block['id'], block['columns'], json.dumps(overview)))
                genome_list = sorted((g for g in genomes.values() if g['extent']), key=lambda g: g['id'])
                if inputs is not None:
                    for genome in genome_list:
                        if not 1 <= genome['id'] <= len(inputs):
                            raise ValueError('Aligner output contains an unexpected sequence ID.')
                        genome['name'] = inputs[genome['id'] - 1]['name']
                db.execute('INSERT INTO alignments(id,name,genomes,block_count) VALUES (?,?,?,?)',
                           (aid, basename(name)[:200] or 'Untitled alignment', json.dumps(genome_list), count))
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return get_alignment(aid)

    jobs = JobManager(storage, save, executable=aligner_path)
    app.state.jobs = jobs
    app.state.ncbi = NCBIClient()

    @app.get('/api/ncbi/assemblies')
    def ncbi_assemblies(taxon_id: int = Query(..., ge=1, le=2_147_483_647),
                        source: Literal['all', 'refseq', 'genbank'] = 'all', exact: bool = False,
                        versions: Literal['current', 'all_assemblies'] = 'current',
                        q: str = Query('', max_length=200), page_token: str = Query('', max_length=4096),
                        page_size: int = Query(25, ge=1, le=100)):
        return app.state.ncbi.search(taxon_id, source, exact, versions, q, page_token, page_size)

    @app.post('/api/ncbi/assemblies/{accession}/input', status_code=201)
    def ncbi_input(accession: str):
        return app.state.ncbi.download(accession, jobs.add_input)

    @app.get('/api/engine')
    def engine():
        return jobs.engine()

    @app.post('/api/inputs', status_code=201)
    async def upload_input(request: Request, name: str = Query('genome.fasta', max_length=500)):
        return await run_in_threadpool(jobs.add_input, await read_upload(request), name)

    @app.post('/api/jobs', status_code=201)
    def create_job(request: JobRequest):
        return jobs.create(request)

    @app.get('/api/jobs')
    def list_jobs():
        return jobs.list()

    @app.get('/api/jobs/{jid}')
    def get_job(jid: str):
        return jobs.get(jid)

    @app.post('/api/jobs/{jid}/cancel')
    def cancel_job(jid: str):
        return jobs.cancel(jid)

    @app.post('/api/jobs/{jid}/import')
    def import_job_result(jid: str):
        return jobs.retry_import(jid)

    @app.get('/api/jobs/{jid}/artifacts/{key}')
    def job_artifact(jid: str, key: str):
        path = jobs.artifact(jid, key)
        return FileResponse(path, filename=path.name)

    @app.get('/api/alignments')
    def list_alignments():
        return query('SELECT id,name,created,block_count FROM alignments ORDER BY created DESC, rowid DESC')

    @app.post('/api/alignments', status_code=201)
    async def upload(request: Request, name: str = Query('alignment.xmfa', max_length=500)):
        # Spool uploads to disk rather than holding the whole file plus its
        # decoded text and parsed sequences in RAM.
        with tempfile.NamedTemporaryFile(suffix='.xmfa') as stream:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_ALIGNMENT:
                    raise HTTPException(413, 'Alignment files must be at most 256 MiB.')
                stream.write(chunk)
            stream.flush()
            return await run_in_threadpool(save, Path(stream.name), name)

    @app.post('/api/demo')
    def demo():
        existing = query("SELECT id FROM alignments WHERE name='Yeast demo' LIMIT 1")
        alignment = get_alignment(existing[0]['id']) if existing else save((ROOT / 'demo.alignment').read_bytes(), 'Yeast demo')
        if not query('SELECT genome_id FROM annotation_sources WHERE alignment_id=? AND genome_id=2', (alignment['id'],)):
            save_annotations(alignment['id'], 2, (ROOT / 'demo.gbk').read_bytes(), 'Yeast demo annotations', True)
        return alignment

    @app.get('/api/alignments/{aid}')
    def alignment(aid: str):
        return get_alignment(aid)

    @app.get('/api/alignments/{aid}/blocks')
    def blocks(aid: str):
        get_alignment(aid)
        # Overview contains coordinates only, never entire aligned sequences.
        return [{'id': b['id'], 'columns': b['columns'],
                 'members': json.loads(b['members'])}
                for b in query('SELECT * FROM block_overviews WHERE alignment_id=? ORDER BY id', (aid,))]

    @app.get('/api/alignments/{aid}/blocks/{bid}')
    def block(aid: str, bid: int, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
              genome_id: int | None = None, position: int | None = Query(None, ge=1)):
        b = get_block(aid, bid)
        if (genome_id is None) != (position is None):
            raise HTTPException(422, 'Provide both a genome ID and genomic position.')
        if position is not None:
            member = next((m for m in b['members'] if m['genome_id'] == genome_id), None)
            if member is None:
                raise HTTPException(422, 'This genome is absent from the selected block.')
            try:
                offset = coordinate_column(member, position)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        if offset >= b['columns']:
            raise HTTPException(422, 'Column offset is outside this block.')
        return {'id': bid, 'columns': b['columns'], 'offset': offset,
                'members': [column_slice(m, offset, limit) for m in b['members']]}

    @app.get('/api/alignments/{aid}/blocks/{bid}/next-difference')
    def next_difference_page(aid: str, bid: int, after: int = Query(0, ge=0)):
        return {'offset': next_difference(get_block(aid, bid), after)}

    @app.get('/api/alignments/{aid}/blocks/{bid}/profile')
    def profile(aid: str, bid: int, reference_id: int, bins: int = Query(100, ge=1, le=200)):
        get_genome(aid, reference_id)
        return identity_profile(get_block(aid, bid), reference_id, bins)

    @app.post('/api/alignments/{aid}/genomes/{gid}/annotations')
    async def import_annotations(aid: str, gid: int, request: Request,
                                 name: str = Query('annotations.gbk', max_length=500), concatenate: bool = False):
        get_genome(aid, gid)
        return await run_in_threadpool(save_annotations, aid, gid, await read_upload(request), name, concatenate)

    @app.get('/api/alignments/{aid}/annotations')
    def annotation_sources(aid: str):
        get_alignment(aid)
        return [{**row, 'metadata': json.loads(row['metadata'])} for row in
                query('SELECT genome_id,name,metadata FROM annotation_sources WHERE alignment_id=? ORDER BY genome_id', (aid,))]

    @app.get('/api/alignments/{aid}/features')
    def features(aid: str, genome_id: int | None = None, q: str = Query('', max_length=200),
                 start: int = Query(1, ge=1), end: int | None = Query(None, ge=1),
                 offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        get_alignment(aid)
        if end is not None and end < start:
            raise HTTPException(422, 'End must be greater than or equal to start.')
        conditions, args = ['alignment_id=?', 'end>=?'], [aid, start]
        if end is not None:
            conditions.append('start<=?')
            args.append(end)
        if genome_id is not None:
            get_genome(aid, genome_id)
            conditions.append('genome_id=?')
            args.append(genome_id)
        if q:
            conditions.append('instr(search_text,?)>0')
            args.append(q.casefold())
        where = ' AND '.join(conditions)
        total = query(f'SELECT count(*) AS n FROM features WHERE {where}', args)[0]['n']
        rows = query(f'SELECT id,genome_id,data FROM features WHERE {where} ORDER BY genome_id,start,id LIMIT ? OFFSET ?',
                     [*args, limit, offset])
        return {'total': total, 'items': [{'id': r['id'], 'genome_id': r['genome_id'], **json.loads(r['data'])} for r in rows]}

    @app.get('/api/alignments/{aid}/blocks/{bid}/fasta')
    def export_fasta(aid: str, bid: int):
        b = get_block(aid, bid)
        lines = []
        for m in b['members']:
            lines.append(f">sequence_{m['genome_id']} block={bid} coordinates={m['start']}-{m['end']} strand={m['strand']}")
            lines.extend(m['sequence'][i:i + 80] for i in range(0, len(m['sequence']), 80))
        return Response('\n'.join(lines) + '\n', media_type='text/plain',
                        headers={'Content-Disposition': f'attachment; filename="block-{bid}.fasta"'})

    @app.get('/api/alignments/{aid}/blocks.tsv')
    def export_blocks(aid: str):
        get_alignment(aid)
        output = io.StringIO()
        writer = csv.writer(output, delimiter='\t', lineterminator='\n')
        writer.writerow(['block_id', 'alignment_columns', 'genome_id', 'start_1based', 'end_inclusive', 'strand'])
        for b in query('SELECT * FROM block_overviews WHERE alignment_id=? ORDER BY id', (aid,)):
            for m in json.loads(b['members']):
                writer.writerow([b['id'], b['columns'], m['genome_id'], m['start'], m['end'], m['strand']])
        return Response(output.getvalue(), media_type='text/tab-separated-values',
                        headers={'Content-Disposition': 'attachment; filename="alignment-blocks.tsv"'})

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'mauve_web/static/index.html')

    app.mount('/static', StaticFiles(directory=ROOT / 'mauve_web/static'), name='static')
    return app

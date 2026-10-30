"""Single-server, serial progressiveMauve jobs with durable provenance.

Only server-configured executables and generated input/output paths are used.
No command strings or filesystem paths are accepted from the browser.
"""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import sqlite3
import subprocess
import threading
import uuid
import warnings

from Bio import BiopythonParserWarning, SeqIO
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .limits import MAX_ALIGNMENT

MAX_INPUT = 50 * 1024 * 1024
MAX_TOTAL_BASES = 100_000_000

MAX_OUTPUT = MAX_ALIGNMENT
ARTIFACTS = {'xmfa': 'alignment.xmfa', 'tree': 'guide.tree', 'backbone': 'alignment.backbone',
             'log': 'run.log', 'manifest': 'manifest.json'}


def now():
    return datetime.now(timezone.utc).isoformat()


class JobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(default='New alignment', min_length=1, max_length=200)
    input_ids: list[str] = Field(min_length=2, max_length=8)
    collinear: bool = False
    seed_family: bool = False
    min_weight: int | None = Field(default=None, ge=0, le=1_000_000_000)
    concatenate_records: bool = False


def normalize_input(raw):
    try:
        text = raw.decode('utf-8-sig').strip()
        format_name = 'fasta' if text.startswith('>') else 'genbank' if text.startswith('LOCUS') else None
        if not format_name:
            raise ValueError('Expected a FASTA or GenBank file with DNA sequences.')
        with warnings.catch_warnings():
            warnings.simplefilter('error', BiopythonParserWarning)
            records = list(SeqIO.parse(StringIO(text), format_name))
        if not records:
            raise ValueError('No sequence records found.')
        pieces, record_info, offset = [], [], 0
        for record in records:
            sequence = str(record.seq).upper()
            if not sequence or not re.fullmatch('[ACGTRYSWKMBDHVN]+', sequence):
                raise ValueError('Inputs must contain non-empty, ungapped DNA sequences (IUPAC bases).')
            if '\n' in record.id or '\r' in record.id:
                raise ValueError('Invalid sequence identifier.')
            record_info.append({'name': record.id, 'start': offset + 1, 'end': offset + len(sequence)})
            pieces.append(sequence)
            offset += len(sequence)
        if offset < 50:
            raise ValueError('Each genome must contain at least 50 bases for this alignment workflow.')
        # One uploaded file is one genome. Multiple records are concatenated only
        # after the job request explicitly confirms that coordinate convention.
        sequence = ''.join(pieces)
        normalized = ('>genome\n' + '\n'.join(sequence[i:i+80] for i in range(0, len(sequence), 80)) + '\n').encode()
        return normalized, {'format': format_name, 'records': record_info, 'bases': offset}
    except (ValueError, UnicodeError, BiopythonParserWarning) as exc:
        raise HTTPException(422, str(exc)) from exc


class JobManager:
    def __init__(self, storage, importer, executable=None):
        self.root = Path(storage).resolve() / 'jobs'
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'inputs').mkdir(exist_ok=True)
        self.db = self.root / 'jobs.sqlite3'
        self.importer = importer
        self.configured_executable = executable
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.lock_file = None
        self.process = None
        self.engine_cache = None
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS inputs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
                    created TEXT NOT NULL, started TEXT, finished TEXT, alignment_id TEXT,
                    error TEXT, spec TEXT NOT NULL);
            ''')

    def query(self, sql, args=()):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(sql, args)]

    def start(self):
        if os.name != 'posix':
            return  # The viewer still works; the initial runner supports macOS/Linux.
        import fcntl
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.lock_file = (self.root / 'worker.lock').open('a')
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.lock_file.close()
                self.lock_file = None
                raise RuntimeError('This workspace already has an alignment worker. Run one server worker per data directory.')
            self.query("UPDATE jobs SET status='interrupted',finished=?,error=? WHERE status IN ('queued','running','cancelling','importing')",
                       (now(), 'Server stopped before this job finished. Submit a new job to rerun it.'))
            self.stop.clear()
            self.thread = threading.Thread(target=self._work, name='mauve-aligner', daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join()  # The running process is stopped by its monitor loop.
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    def engine(self):
        with self.lock:
            if self.engine_cache is not None:
                return self.engine_cache
            configured = self.configured_executable if self.configured_executable is not None else os.environ.get('MAUVE_ALIGNER')
            repo = Path(__file__).resolve().parents[2]
            bundled = repo / ('osx/progressiveMauve' if platform.system() == 'Darwin' else 'linux-x64/progressiveMauve')
            arm64 = repo / 'web/native/bin/progressiveMauve'
            if platform.system() == 'Darwin' and platform.machine() == 'arm64' and arm64.is_file() and os.access(arm64, os.X_OK):
                bundled = arm64
            candidate = configured or shutil.which('progressiveMauve') or str(bundled)
            path = Path(candidate).expanduser().resolve()
            info = {'available': False, 'path': str(path), 'version': None, 'reason': None}
            if os.name != 'posix':
                info['reason'] = 'Alignment jobs currently require macOS or Linux.'
            elif not path.is_file() or not os.access(path, os.X_OK):
                info['reason'] = 'No executable progressiveMauve found. Set MAUVE_ALIGNER to its path and restart the server.'
            else:
                try:
                    p = subprocess.run([str(path), '--version'], capture_output=True, timeout=10)
                    version = (p.stdout + p.stderr).decode('utf-8', errors='replace').strip()[:2000]
                    if p.returncode != 0:
                        raise ValueError(version or f'Exit code {p.returncode}')
                    info.update(available=True, version=version, sha256=sha256(path.read_bytes()).hexdigest())
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    info['reason'] = f'progressiveMauve could not run: {exc}'
            self.engine_cache = info
            return info

    def add_input(self, raw, name, provenance=None):
        if len(raw) > MAX_INPUT:
            raise HTTPException(413, 'Sequence files must be at most 50 MiB.')
        normalized, metadata = normalize_input(raw)
        if provenance is not None:
            metadata['provenance'] = provenance
        iid = uuid.uuid4().hex
        clean_name = name.replace('\\', '/').rsplit('/', 1)[-1].replace('\n', ' ').replace('\r', ' ')[:200]
        metadata.update(id=iid, name=clean_name or 'genome', sha256=sha256(raw).hexdigest(),
                        normalized_sha256=sha256(normalized).hexdigest())
        directory = self.root / 'inputs' / iid
        directory.mkdir()
        (directory / 'original').write_bytes(raw)
        (directory / 'genome.fasta').write_bytes(normalized)
        self.query('INSERT INTO inputs VALUES (?,?)', (iid, json.dumps(metadata)))
        return metadata

    def create(self, request):
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                raise HTTPException(503, 'Alignment worker is not running.')
            engine = self.engine()
            if not engine['available']:
                raise HTTPException(503, engine['reason'])
            if len(set(request.input_ids)) != len(request.input_ids):
                raise HTTPException(422, 'Choose distinct input files for this job.')
            inputs = []
            for iid in request.input_ids:
                rows = self.query('SELECT data FROM inputs WHERE id=?', (iid,))
                if not rows:
                    raise HTTPException(404, 'An input file was not found; upload it again.')
                inputs.append(json.loads(rows[0]['data']))
            if sum(i['bases'] for i in inputs) > MAX_TOTAL_BASES:
                raise HTTPException(413, 'This version supports at most 100 million total input bases per job.')
            if any(len(i['records']) > 1 for i in inputs) and not request.concatenate_records:
                raise HTTPException(422, 'Multiple records detected. Enable concatenation in file order to treat each file as one genome.')
            if self.query("SELECT count(*) AS n FROM jobs WHERE status IN ('queued','running','importing','cancelling')")[0]['n'] >= 10:
                raise HTTPException(409, 'The queue is full. Wait for a job to finish.')
            jid = uuid.uuid4().hex
            directory = self.root / jid
            directory.mkdir()
            names = []
            for index, source in enumerate(inputs, 1):
                filename = f'genome_{index}.fasta'
                shutil.copyfile(self.root / 'inputs' / source['id'] / 'genome.fasta', directory / filename)
                names.append(filename)
            command = [engine['path'], '--output=alignment.xmfa', '--output-guide-tree=guide.tree',
                       '--backbone-output=alignment.backbone']
            if request.collinear:
                command.append('--collinear')
            if request.seed_family:
                command.append('--seed-family')
            if request.min_weight is not None:
                command.append(f'--weight={request.min_weight}')
            command.extend(names)
            spec = {'inputs': inputs, 'options': request.model_dump(exclude={'input_ids'}), 'engine': engine,
                    'command': command, 'created': now(), 'coordinates': '1-based inclusive; records concatenated in file order',
                    'executable_sha256': engine['sha256']}
            (directory / 'manifest.json').write_text(json.dumps(spec, indent=2) + '\n')
            self.query('INSERT INTO jobs(id,name,status,created,spec) VALUES (?,?,?,?,?)',
                       (jid, request.name.strip() or 'New alignment', 'queued', spec['created'], json.dumps(spec)))
            self.wake.set()
            return self.get(jid)

    def list(self):
        return self.query('SELECT id,name,status,created,started,finished,alignment_id,error FROM jobs ORDER BY created DESC LIMIT 100')

    def get(self, jid):
        rows = self.query('SELECT * FROM jobs WHERE id=?', (jid,))
        if not rows:
            raise HTTPException(404, 'Job not found.')
        job = rows[0]
        job['spec'] = json.loads(job['spec'])
        directory = self.root / jid
        log = directory / 'run.log'
        job['log'] = ''
        if log.is_file():
            with log.open('rb') as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - 32768))
                job['log'] = stream.read().decode('utf-8', errors='replace')
            job['log_truncated'] = size > 32768
        job['artifacts'] = [key for key, filename in ARTIFACTS.items() if (directory / filename).is_file()]
        legacy_limit = job['error'] == 'Alignment exceeds the viewer’s 50 MiB import limit. Download the XMFA output instead.'
        completed = (directory / 'aligner-completed.json').is_file() or legacy_limit
        job['can_import_result'] = (job['status'] in ('failed', 'interrupted') and completed
                                    and (directory / 'alignment.xmfa').is_file())
        return job

    def artifact(self, jid, key):
        self.get(jid)  # Validate ID before constructing paths.
        if key not in ARTIFACTS:
            raise HTTPException(404, 'Artifact not found.')
        path = self.root / jid / ARTIFACTS[key]
        if not path.is_file():
            raise HTTPException(404, 'Artifact not available.')
        return path

    def _import_result(self, jid, name, inputs):
        output = self.root / jid / 'alignment.xmfa'
        if not output.is_file() or output.stat().st_size == 0:
            raise ValueError('The aligner completed without producing an XMFA alignment.')
        if output.stat().st_size > MAX_OUTPUT:
            raise ValueError('Alignment completed, but the result exceeds the viewer’s 256 MiB alignment limit. The saved XMFA can be downloaded.')
        imported = self.importer(output, name, inputs)
        self._finish(jid, 'succeeded', alignment_id=imported['id'])

    def retry_import(self, jid):
        # Serialize recovery attempts so repeated clicks cannot create duplicate
        # library entries. The native aligner and inputs are never rerun here.
        with self.lock:
            job = self.get(jid)
            if job['status'] == 'succeeded':
                return job
            if not job['can_import_result']:
                raise HTTPException(409, 'No completed alignment output is available to retry importing.')
            self.query("UPDATE jobs SET status='importing',error=NULL WHERE id=?", (jid,))
            try:
                self._import_result(jid, job['name'], job['spec']['inputs'])
            except Exception as exc:
                message = exc.detail if isinstance(exc, HTTPException) else str(exc)
                # Persist proof of completion for recovery of legacy size-limit
                # failures even when another import attempt fails validation.
                (self.root / jid / 'aligner-completed.json').write_text(json.dumps({'completed': True}))
                self._finish(jid, 'failed', f'Alignment completed; result import failed: {message}')
            return self.get(jid)

    def cancel(self, jid):
        with self.lock:
            job = self.get(jid)
            if job['status'] == 'queued':
                self.query("UPDATE jobs SET status='cancelled',finished=? WHERE id=?", (now(), jid))
            elif job['status'] in ('running', 'cancelling'):
                self.query("UPDATE jobs SET status='cancelling' WHERE id=?", (jid,))
            else:
                raise HTTPException(409, 'Only queued or running jobs can be cancelled; importing results is atomic.')
        self.wake.set()
        return self.get(jid)

    def _finish(self, jid, status, error=None, alignment_id=None):
        self.query('UPDATE jobs SET status=?,finished=?,error=?,alignment_id=? WHERE id=?',
                   (status, now(), error, alignment_id, jid))

    @staticmethod
    def _terminate(process):
        # Terminate descendants as well (aligner subprocesses can outlive their parent).
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()

    def _work(self):
        while not self.stop.is_set():
            with self.lock:
                rows = self.query("SELECT id,spec,name FROM jobs WHERE status='queued' ORDER BY created LIMIT 1")
                if rows:
                    job = rows[0]
                    self.query("UPDATE jobs SET status='running',started=? WHERE id=?", (now(), job['id']))
            if not rows:
                self.wake.wait(.25)
                self.wake.clear()
                continue
            jid = job['id']
            directory = self.root / jid
            spec = json.loads(job['spec'])
            process = None
            try:
                # Detect changed executable/inputs instead of silently changing provenance.
                if sha256(Path(spec['engine']['path']).read_bytes()).hexdigest() != spec['executable_sha256']:
                    raise ValueError('Aligner executable changed after submission. Submit a new job.')
                for index, source in enumerate(spec['inputs'], 1):
                    if sha256((directory / f'genome_{index}.fasta').read_bytes()).hexdigest() != source['normalized_sha256']:
                        raise ValueError('A job input changed after submission.')
                with (directory / 'run.log').open('wb') as log:
                    process = subprocess.Popen(spec['command'], cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, start_new_session=True)
                    self.process = process
                    failure = None
                    while process.poll() is None:
                        if self.stop.is_set() or self.query('SELECT status FROM jobs WHERE id=?', (jid,))[0]['status'] == 'cancelling':
                            self._terminate(process)
                            break
                        if (directory / 'run.log').stat().st_size > 25 * 1024 * 1024:
                            failure = 'Log exceeded the 25 MiB limit.'
                            self._terminate(process)
                            break
                        self.stop.wait(.15)
                with self.lock:
                    if self.stop.is_set():
                        self._finish(jid, 'interrupted', 'Server stopped while the aligner was running.')
                        continue
                    if self.query('SELECT status FROM jobs WHERE id=?', (jid,))[0]['status'] == 'cancelling':
                        self._finish(jid, 'cancelled')
                        continue
                    if failure or process.returncode != 0:
                        raise ValueError(failure or f'progressiveMauve exited with code {process.returncode}. See the log.')
                    self.query("UPDATE jobs SET status='importing' WHERE id=?", (jid,))
                (directory / 'aligner-completed.json').write_text(json.dumps({'exit_code': process.returncode, 'completed': now()}))
                self._import_result(jid, job['name'], spec['inputs'])
            except Exception as exc:
                if process and process.poll() is None:
                    self._terminate(process)
                message = exc.detail if isinstance(exc, HTTPException) else str(exc)
                self._finish(jid, 'failed', str(message))
            finally:
                self.process = None
        self.query("UPDATE jobs SET status='interrupted',finished=?,error=? WHERE status='queued'",
                   (now(), 'Server stopped before this queued job ran.'))

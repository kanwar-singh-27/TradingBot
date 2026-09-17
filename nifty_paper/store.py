"""Transactional session journal and process lifetime lock; no account data."""

from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .models import UTC


def encoded(value):
    return json.dumps(value, default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x), allow_nan=False)


class RunLock:
    def __init__(self, root):
        self.root = Path(root)
        self.file = None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.file = (self.root/'worker.lock').open('a+b')
        try:
            if os.fstat(self.file.fileno()).st_size == 0:
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError('A paper worker already owns this output directory') from exc
        return self

    def __exit__(self, *args):
        if self.file:
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()


class Store:
    def __init__(self, root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root/'paper.sqlite3', timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, started TEXT NOT NULL, heartbeat TEXT NOT NULL,
                pid INTEGER NOT NULL, config TEXT NOT NULL, state TEXT NOT NULL, stop INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, recorded TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, recorded TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS equity_samples (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                recorded TEXT NOT NULL,
                source_at TEXT,
                equity REAL NOT NULL,
                equity_lower_bound REAL NOT NULL,
                cash REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                fees_paid REAL NOT NULL,
                last_spot REAL,
                mark_status TEXT NOT NULL
            );
        ''')

    def create(self, config):
        previous = self.latest()
        if previous and previous['state'].get('position'):
            raise RuntimeError('Previous simulated exposure is unresolved; inspect it, do not silently reset the portfolio')
        session = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self.db:
            self.db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,0)',
                            (session, now, now, os.getpid(), encoded(asdict(config)), encoded({'status': 'STARTING'})))
        return session

    def save(self, session, state, events=(), snapshot=None):
        now = datetime.now(UTC).isoformat()
        with self.db:
            self.db.execute('UPDATE sessions SET heartbeat=?, state=? WHERE id=?', (now, encoded(state), session))
            self.db.executemany('INSERT INTO events(session_id,recorded,payload) VALUES (?,?,?)',
                                [(session, now, encoded(event)) for event in events])
            if snapshot:
                self.db.execute('INSERT INTO snapshots(session_id,recorded,payload) VALUES (?,?,?)',
                                (session, now, encoded(asdict(snapshot))))
                self.db.execute(
                    '''INSERT INTO equity_samples(
                           session_id, recorded, source_at, equity, equity_lower_bound,
                           cash, realized_pnl, fees_paid, last_spot, mark_status
                       ) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (
                        session,
                        now,
                        snapshot.at.isoformat(),
                        state['equity'],
                        state['equity_lower_bound'],
                        state['cash'],
                        state['realized_pnl'],
                        state['fees_paid'],
                        state.get('last_spot'),
                        state['mark_status'],
                    ),
                )

    def latest(self):
        row = self.db.execute('SELECT * FROM sessions ORDER BY rowid DESC LIMIT 1').fetchone()
        if not row:
            return None
        result = dict(row)
        result['state'], result['config'] = json.loads(result['state']), json.loads(result['config'])
        return result

    def events(self, session, limit=20):
        return [json.loads(row[0]) for row in self.db.execute(
            'SELECT payload FROM events WHERE session_id=? ORDER BY seq DESC LIMIT ?', (session, limit))][::-1]

    def stop(self, session):
        with self.db:
            self.db.execute('UPDATE sessions SET stop=1 WHERE id=?', (session,))

    def stop_requested(self, session):
        row = self.db.execute('SELECT stop FROM sessions WHERE id=?', (session,)).fetchone()
        return bool(row and row[0])

    def close(self):
        self.db.close()
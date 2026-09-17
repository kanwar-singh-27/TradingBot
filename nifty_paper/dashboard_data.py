"""Read-only journal access for the local paper dashboard."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


SOURCE_OUTPUTS = {
    'public': Path('runtime/public'),
    'public_loose': Path('runtime/public-loose'),
    'demo': Path('runtime/validation-demo'),
}


class JournalReader:
    def __init__(self, workspace_root):
        self.workspace_root = Path(workspace_root)

    def output_root(self, source):
        try:
            return (self.workspace_root / SOURCE_OUTPUTS[source]).resolve()
        except KeyError as exc:
            raise ValueError('Unsupported paper source') from exc

    def db_path(self, source):
        return self.output_root(source) / 'paper.sqlite3'

    @contextmanager
    def connect(self, source):
        db_path = self.db_path(source)
        if not db_path.exists():
            yield None
            return
        connection = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA busy_timeout=2000')
        try:
            yield connection
        finally:
            connection.close()

    def _table_exists(self, connection, name):
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return bool(row)

    def _session_from_row(self, row):
        if row is None:
            return None
        result = dict(row)
        result['config'] = json.loads(result['config'])
        result['state'] = json.loads(result['state'])
        return result

    def load_latest(self, source):
        output = self.output_root(source)
        with self.connect(source) as connection:
            if connection is None or not self._table_exists(connection, 'sessions'):
                return {'status': 'NOT_STARTED', 'source': source, 'output': str(output)}
            row = connection.execute('SELECT * FROM sessions ORDER BY rowid DESC LIMIT 1').fetchone()
            latest = self._session_from_row(row)
            if latest is None:
                return {'status': 'NOT_STARTED', 'source': source, 'output': str(output)}
            latest['status'] = latest['state'].get('status', 'UNKNOWN')
            latest['source'] = source
            latest['output'] = str(output)
            return latest

    def list_sessions(self, source, limit=20, offset=0):
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        with self.connect(source) as connection:
            if connection is None or not self._table_exists(connection, 'sessions'):
                return []
            rows = connection.execute(
                'SELECT * FROM sessions ORDER BY rowid DESC LIMIT ? OFFSET ?',
                (limit, offset),
            ).fetchall()
            return [self._session_from_row(row) for row in rows]

    def _events(self, connection, session_id, limit):
        if not self._table_exists(connection, 'events'):
            return []
        rows = connection.execute(
            'SELECT recorded, payload FROM events WHERE session_id=? ORDER BY seq DESC LIMIT ?',
            (session_id, max(1, min(int(limit), 500))),
        ).fetchall()
        result = []
        for row in reversed(rows):
            payload = json.loads(row['payload'])
            payload['recorded'] = row['recorded']
            result.append(payload)
        return result

    def _snapshots(self, connection, session_id, limit):
        if not self._table_exists(connection, 'snapshots'):
            return []
        rows = connection.execute(
            'SELECT recorded, payload FROM snapshots WHERE session_id=? ORDER BY seq DESC LIMIT ?',
            (session_id, max(1, min(int(limit), 500))),
        ).fetchall()
        result = []
        for row in reversed(rows):
            payload = json.loads(row['payload'])
            payload['recorded'] = row['recorded']
            result.append(payload)
        return result

    def _equity_history(self, connection, session_id):
        if not self._table_exists(connection, 'equity_samples'):
            return 'UNAVAILABLE', []
        rows = connection.execute(
            '''SELECT recorded, source_at, equity, equity_lower_bound, cash, realized_pnl,
                      fees_paid, last_spot, mark_status
               FROM equity_samples WHERE session_id=? ORDER BY seq''',
            (session_id,),
        ).fetchall()
        if not rows:
            return 'UNAVAILABLE', []
        return 'AVAILABLE', [dict(row) for row in rows]

    def load_session(self, source, session_id, event_limit=200, snapshot_limit=200):
        with self.connect(source) as connection:
            if connection is None or not self._table_exists(connection, 'sessions'):
                raise LookupError('No paper journal exists for that source')
            row = connection.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
            session = self._session_from_row(row)
            if session is None:
                raise LookupError('Session not found')
            status, equity_history = self._equity_history(connection, session_id)
            session['events'] = self._events(connection, session_id, event_limit)
            session['snapshots'] = self._snapshots(connection, session_id, snapshot_limit)
            session['equity_history_status'] = status
            session['equity_history'] = equity_history
            session['source'] = source
            session['output'] = str(self.output_root(source))
            return session
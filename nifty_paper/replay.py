"""Read-only, causal snapshot diagnostic replay. Never starts a feed or worker."""

from dataclasses import replace
from datetime import datetime
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3

from .diagnostics import summarize
from .engine import Engine
from .models import Config, Quote, Snapshot


def decode_snapshot(payload):
    raw = json.loads(payload)
    return Snapshot(datetime.fromisoformat(raw['at']), datetime.fromisoformat(raw['received_at']), raw['spot'],
                    tuple((datetime.fromisoformat(t), p) for t,p in raw['bars']),
                    tuple(Quote(**{**q, **{k: float('nan') for k in ('strike','bid','ask','iv') if q.get(k) is None},
                                   'expiry': datetime.fromisoformat(q['expiry']) if q.get('expiry') else None}) for q in raw['quotes']),
                    raw['source'], raw['kind'])


def diagnose(output, session_id=None):
    path = Path(output) / 'paper.sqlite3'
    if not path.exists():
        raise ValueError('No recorded journal exists; diagnose never starts a session')
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        session = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone() if session_id else db.execute('SELECT * FROM sessions ORDER BY rowid DESC LIMIT 1').fetchone()
        if session is None:
            raise ValueError('Recorded session not found')
        config = Config(**json.loads(session['config']))
        recorded_state = json.loads(session['state'])
        if recorded_state.get('entries', 0):
            raise ValueError('Flat-book diagnostic replay supports zero-entry sessions only; use persisted diagnostics for traded sessions')
        engine = Engine(replace(config, diagnostic=True))
        events = defaultdict(list)
        recorded_reasons = Counter()
        for row in db.execute('SELECT recorded,payload FROM events WHERE session_id=? ORDER BY seq', (session['id'],)):
            event = json.loads(row['payload'])
            events[row['recorded']].append(event)
            recorded_reasons[event.get('reason', 'UNKNOWN')] += 1
        reports = []
        for row in db.execute('SELECT recorded,payload FROM snapshots WHERE session_id=? ORDER BY seq', (session['id'],)):
            snapshot = decode_snapshot(row['payload'])
            reasons = {event.get('reason') for event in events.get(row['recorded'], [])}
            # Save time is an explicit conservative proxy: exact historical
            # engine evaluation time was not persisted by the old schema.
            now = snapshot.at if config.source == 'demo' else datetime.fromisoformat(row['recorded'])
            engine.step(snapshot, now, closing=bool(reasons & {'SESSION_CLOSING_OR_RISK_HALT', 'DURATION_EXPIRED_DURING_FETCH'}))
            reports.append(engine.last_decision)
        return {'status': 'OFFLINE_DIAGNOSTIC_REPLAY', 'session_id': session['id'], 'output': str(Path(output).resolve()),
                'recorded_reasons': dict(recorded_reasons),
                'original_config': json.loads(session['config']), 'summary': summarize(reports),
                'latest': reports[-1] if reports else None,
                'notice': 'Current-code, zero-position counterfactual on stored observations; not reconstructed historical trades. Save timestamps proxy old decision times. No network, fees, fills or journal writes.'}
    finally:
        db.close()
"""Fixed commands: start/run/status/report/stop/check. There is no live route."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from .feeds import PublicFeed, DemoFeed, KiteFeed
from .models import Config, UTC, is_public_source, market_open
from .paths import resolve_output
from .diagnostics import journal_diagnostics
from .replay import diagnose
from .runtime import run
from .store import RunLock, Store, encoded

ROOT = Path(__file__).resolve().parents[1]


def parser():
    result = argparse.ArgumentParser(description='NIFTY-only public-snapshot paper simulator. No real orders.')
    commands = result.add_subparsers(dest='command', required=True)
    for command in ('start', 'run', '_worker'):
        item = commands.add_parser(command)
        item.add_argument('--source', choices=('public', 'public_loose', 'demo', 'kite'), default='public')
        item.add_argument('--duration-minutes', type=float, required=True)
        item.add_argument('--poll-seconds', type=float)
        item.add_argument('--capital', type=float, default=1_000_000)
        item.add_argument('--output', type=Path)
        item.add_argument('--diagnostic', action='store_true', help='Evaluate entries without creating intents, positions or charges')
    for command in ('status', 'report', 'stop', 'check'):
        item = commands.add_parser(command)
        item.add_argument('--source', choices=('public', 'public_loose', 'demo', 'kite'), default='public')
        item.add_argument('--output', type=Path)
    item = commands.add_parser('diagnose', help='Read-only diagnostic replay of a recorded zero-entry session; never fetches data')
    item.add_argument('--source', choices=('public', 'public_loose', 'demo'), default='public')
    item.add_argument('--output', type=Path)
    item.add_argument('--session-id')
    return result


def inspect(output, include_events=False):
    if not (output/'paper.sqlite3').exists():
        return {'status': 'NOT_STARTED', 'output': str(output)}
    store = Store(output)
    try:
        latest = store.latest()
        if not latest:
            return {'status': 'NOT_STARTED', 'output': str(output)}
        try:
            with RunLock(output):
                lock_held = False
        except RuntimeError:
            lock_held = True
        latest['worker_lock_held'] = lock_held
        latest['heartbeat_age_seconds'] = round((datetime.now(UTC)-datetime.fromisoformat(latest['heartbeat'])).total_seconds(), 1)
        latest['process_status'] = ('RUNNING' if latest['heartbeat_age_seconds'] < 90 else 'HEARTBEAT_STALE') if lock_held else 'NOT_RUNNING'
        if not lock_held and latest['state'].get('status') in ('STARTING', 'RUNNING'):
            latest['process_status'] = 'INTERRUPTED_WITH_UNRESOLVED_EXPOSURE' if latest['state'].get('position') else 'INTERRUPTED'
        latest['warning'] = 'Simulated fills only; public reference data and unvalidated model do not establish tradability or alpha.'
        latest['output'] = str(output)
        if include_events:
            latest['events'] = store.events(latest['id'], 100)
            latest['diagnostics'] = journal_diagnostics(store.db, latest['id'])
        return latest
    finally:
        store.close()


def launch(config, output):
    output.mkdir(parents=True, exist_ok=True)
    with RunLock(output):
        current = inspect(output)
        if current.get('state', {}).get('position'):
            raise RuntimeError('Previous paper position unresolved; inspect report before starting a new book')
    args = [sys.executable, '-I', str(ROOT/'paper.py'), '_worker', '--source', config.source,
            '--duration-minutes', str(config.duration_minutes), '--poll-seconds', str(config.poll_seconds),
            '--capital', str(config.capital), '--output', str(output)]
    if config.diagnostic:
        args.append('--diagnostic')
    # Do not pass broker/AI secrets from the editor environment into this subprocess.
    allowed = ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'LOCALAPPDATA')
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment['PYTHONUTF8'] = '1'
    kwargs = {'start_new_session': True} if os.name != 'nt' else {
        'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    with (output/'worker.log').open('ab') as log:
        process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   env=environment, close_fds=True, **kwargs)
    # This is a spawn acknowledgment, not proof the child acquired its lock or a quote.
    return {'status': 'START_REQUESTED', 'pid': process.pid, 'source': config.source,
            'output': str(output), 'duration_minutes': config.duration_minutes,
            'next_action': 'Run status to confirm worker lock, heartbeat and session configuration'}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        output = resolve_output(ROOT, args.source, args.output)
        if args.command == 'diagnose':
            print(encoded(diagnose(output, args.session_id)))
            return 0
        if args.command in ('start', 'run', '_worker'):
            config = Config(source=args.source, duration_minutes=args.duration_minutes,
                            poll_seconds=args.poll_seconds if args.poll_seconds is not None else 60 if is_public_source(args.source) else 1,
                            capital=args.capital, diagnostic=args.diagnostic)
            if args.command == 'start':
                print(encoded(launch(config, output)))
                return 0
            return run(config, output)
        if args.command in ('status', 'report'):
            print(json.dumps(inspect(output, args.command == 'report'), indent=2))
            return 0
        if args.command == 'stop':
            result = inspect(output)
            if result.get('id') and result.get('worker_lock_held'):
                store = Store(output)
                try:
                    store.stop(result['id'])
                finally:
                    store.close()
                result = {'status': 'STOP_REQUESTED', 'session_id': result['id'],
                          'note': 'May take two polling intervals plus in-flight fetch to obtain an honest exit; otherwise UNRESOLVED'}
            print(encoded(result))
            return 0
        if args.command == 'check':
            if args.source == 'demo':
                feed = DemoFeed()
            elif args.source == 'kite':
                feed = KiteFeed()
            else:
                feed = PublicFeed()
            snapshot = feed.fetch()
            now = snapshot.at if args.source == 'demo' else datetime.now(UTC)
            print(encoded({'status': 'SOURCE_RESPONSE_RECEIVED', 'kind': snapshot.kind,
                           'as_of': snapshot.at, 'received_at': snapshot.received_at,
                           'age_seconds': (now-snapshot.at).total_seconds(),
                           'spot': snapshot.spot, 'options': len(snapshot.quotes), 'completed_bars': len(snapshot.bars),
                           'market_open': market_open(now), 'lot_sizes': sorted({q.lot_size for q in snapshot.quotes}),
                           'source': snapshot.source, 'note': 'A response is not proof of fresh individual leg quotes or usable forecast context'}))
            return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(encoded({'status': 'ERROR', 'error': str(exc)}), file=sys.stderr)
        return 1
    return 1
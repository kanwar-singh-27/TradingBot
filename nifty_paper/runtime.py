"""Duration-bounded worker independent of a chat turn; all trades are simulated."""

from datetime import datetime, timedelta
import signal
import threading
import time

from .engine import Engine
from .feeds import DemoFeed, FeedError, PublicFeed, KiteFeed
from .models import UTC, is_public_source, market_open
from .store import RunLock, Store, encoded


def run(config, output):
    interrupted = threading.Event()
    previous_signals = {}
    for name in ('SIGINT', 'SIGTERM'):
        signum = getattr(signal, name, None)
        if signum is not None:
            previous_signals[signum] = signal.signal(signum, lambda *_: interrupted.set())
    store = None
    try:
        with RunLock(output):
            store = Store(output)
            session = store.create(config)
            engine = Engine(config)
            if config.source == 'demo':
                feed = DemoFeed()
            elif config.source == 'kite':
                feed = KiteFeed()
            else:
                feed = PublicFeed()
            end = time.monotonic() + config.duration_minutes*60
            engine.state['session_id'] = session
            engine.state['planned_end_utc'] = (datetime.now(UTC)+timedelta(minutes=config.duration_minutes)).isoformat()
            store.save(session, engine.state)
            print(encoded({'event': 'STARTED', 'session_id': session, 'source': config.source,
                           'virtual_capital': config.capital, 'duration_minutes': config.duration_minutes}), flush=True)
            next_fetch, next_heartbeat, failures = 0.0, 0.0, 0
            stopping = False
            try:
                while time.monotonic() < end:
                    clock = time.monotonic()
                    if interrupted.is_set() or store.stop_requested(session):
                        if not stopping:
                            end = min(end, clock + 2*config.poll_seconds + 15)
                            stopping = True
                            engine.state['stop_requested'] = True
                        if not engine.state['position']:
                            break
                    if clock >= next_fetch:
                        closing = stopping or end-clock <= 3*config.poll_seconds
                        # Leave time to hold and request/fill a subsequent-snapshot exit.
                        required = (config.hold_minutes*60 if is_public_source(config.source)
                                    else config.hold_minutes*config.poll_seconds) + 4*config.poll_seconds
                        no_new_entries = end-clock < required
                        now = datetime.now(UTC)
                        if is_public_source(config.source) and not market_open(now):
                            engine.unavailable()
                            events = [engine.event('NO_TRADE', 'MARKET_CLOSED')]
                            store.save(session, engine.state, events)
                            next_fetch = clock + config.poll_seconds
                        else:
                            try:
                                snapshot = feed.fetch()
                                if time.monotonic() >= end:
                                    # Never fill an intent after the requested duration just because HTTP returned late.
                                    store.save(session, engine.state, [{'action': 'NO_FILL', 'reason': 'DURATION_EXPIRED_DURING_FETCH'}], snapshot)
                                    break
                                reference_now = snapshot.at if config.source == 'demo' else datetime.now(UTC)
                                # Outside a remaining entry window, finish pending BUYs but do not open new ones.
                                close_for_entry_only = no_new_entries and not engine.state['position']
                                events = engine.step(snapshot, reference_now, closing=closing or close_for_entry_only)
                                engine.state['source_as_of'] = snapshot.at.isoformat()
                                engine.state['source_received_at'] = snapshot.received_at.isoformat()
                                engine.state['source_url'] = snapshot.source
                                engine.state['last_error'] = None
                                store.save(session, engine.state, events, snapshot)
                                failures = 0
                            except FeedError as exc:
                                failures += 1
                                engine.unavailable()
                                engine.state['last_error'] = str(exc)
                                events = [engine.event('NO_TRADE', 'DATA_UNAVAILABLE', detail=str(exc))]
                                store.save(session, engine.state, events)
                            next_fetch = time.monotonic() + min(300, config.poll_seconds*max(1, 2**min(failures, 3)))
                        print(encoded({'session_id': session, 'status': engine.state['status'],
                                       'reason': engine.state['reason'], 'events': events,
                                       'equity': engine.state['equity']}), flush=True)
                    if clock >= next_heartbeat:
                        store.save(session, engine.state)
                        next_heartbeat = clock + 1
                    # Scheduling wait, not a chat/terminal polling loop. Stop is checked at least each second.
                    threading.Event().wait(max(0, min(1, next_fetch-time.monotonic(), end-time.monotonic())))
            except Exception:
                engine.finish(interrupted=True)
                store.save(session, engine.state, [{'action': 'ERROR', 'reason': 'WORKER_FAILED'}])
                raise
            engine.finish(interrupted=interrupted.is_set())
            store.save(session, engine.state, [{'action': 'END', 'reason': engine.state['reason']}])
            print(encoded({'event': 'FINISHED', 'session_id': session, 'state': engine.state}), flush=True)
            return 0
    finally:
        if store:
            store.close()
        for signum, handler in previous_signals.items():
            signal.signal(signum, handler)
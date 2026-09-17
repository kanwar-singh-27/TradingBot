from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]

from nifty_paper.engine import Engine
from nifty_paper.models import Config, Quote, Snapshot, UTC
from nifty_paper.store import Store


class DashboardBackendTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 9, 17, 5, 0, tzinfo=timezone.utc)
        self.cfg = Config(source='demo', duration_minutes=30, poll_seconds=1, capital=1_000_000)

    def snapshot(self, offset_minutes=0, bid=99.0, ask=100.0, **changes):
        at = self.at + timedelta(minutes=offset_minutes)
        quote = Quote('DEMO-NIFTY-CE', 'CE', 23200, self.at + timedelta(days=7), bid, ask, 650, 650, 65, 0.18)
        bars = tuple((at - timedelta(minutes=60 - i), 23000 * (1.00015 ** i)) for i in range(61))
        return Snapshot(at, at, bars[-1][1], bars, (replace(quote, **changes),), 'synthetic://fixture', 'DEMO_SYNTHETIC')

    def create_session(self, root: Path, source='demo', position=False):
        from nifty_paper.dashboard_data import JournalReader

        cfg = replace(self.cfg, source=source)
        store = Store(root)
        session_id = store.create(cfg)
        engine = Engine(cfg)
        first = self.snapshot(0)
        second = self.snapshot(1)
        events = [{'action': 'NO_TRADE', 'reason': 'CASH_BETTER_AFTER_COSTS'}]
        store.save(session_id, engine.state, events=events, snapshot=first)
        if position:
            engine.state['position'] = {
                'instrument': 'DEMO-NIFTY-CE', 'right': 'CE', 'strike': 23200, 'expiry': (self.at + timedelta(days=7)).isoformat(),
                'units': 65, 'entry_price': 100.1, 'entry_fee': 38.01, 'entered_at': self.at.isoformat(),
                'last_bid': 99.0, 'mark_at': first.at.isoformat(),
            }
            engine.state['mark_status'] = 'STALE_LAST_KNOWN'
            engine.state['equity'] = 999_000
            engine.state['equity_lower_bound'] = 993_500
            engine.state['risk_equity'] = 993_500
        store.save(session_id, engine.state, events=[{'action': 'HOLD', 'reason': 'POSITION_MONITORED'}], snapshot=second)
        store.close()
        reader = JournalReader(ROOT)
        return reader, session_id

    def test_missing_database_is_reported_without_creating_it(self):
        from nifty_paper.dashboard_data import JournalReader

        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            reader = JournalReader(workspace)
            result = reader.load_latest('public')
            self.assertEqual(result['status'], 'NOT_STARTED')
            self.assertFalse((workspace / 'runtime' / 'public' / 'paper.sqlite3').exists())

    def test_session_queries_are_source_scoped_and_bounded(self):
        from nifty_paper.dashboard_data import JournalReader

        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            public_root = workspace / 'runtime' / 'public'
            demo_root = workspace / 'runtime' / 'validation-demo'
            public_root.mkdir(parents=True)
            demo_root.mkdir(parents=True)

            for index in range(3):
                store = Store(public_root)
                public_cfg = replace(self.cfg, source='public', poll_seconds=60)
                session_id = store.create(public_cfg)
                engine = Engine(public_cfg)
                engine.state['reason'] = f'PUBLIC_{index}'
                store.save(session_id, engine.state, events=[{'action': 'NO_TRADE', 'reason': f'PUBLIC_{index}'}])
                store.close()

            store = Store(demo_root)
            session_id = store.create(self.cfg)
            engine = Engine(self.cfg)
            engine.state['reason'] = 'DEMO_ONLY'
            store.save(session_id, engine.state, events=[{'action': 'NO_TRADE', 'reason': 'DEMO_ONLY'}])
            store.close()

            reader = JournalReader(workspace)
            public_sessions = reader.list_sessions('public', limit=2)
            demo_sessions = reader.list_sessions('demo', limit=5)

            self.assertEqual(len(public_sessions), 2)
            self.assertTrue(all(item['config']['source'] == 'public' for item in public_sessions))
            self.assertEqual(len(demo_sessions), 1)
            self.assertEqual(demo_sessions[0]['state']['reason'], 'DEMO_ONLY')

    def test_old_sessions_report_missing_equity_history(self):
        from nifty_paper.dashboard_data import JournalReader

        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / 'runtime' / 'validation-demo'
            root.mkdir(parents=True)
            store = Store(root)
            session_id = store.create(self.cfg)
            engine = Engine(self.cfg)
            store.save(session_id, engine.state, events=[{'action': 'NO_TRADE', 'reason': 'STARTING'}])
            store.close()

            reader = JournalReader(workspace)
            details = reader.load_session('demo', session_id, event_limit=10, snapshot_limit=10)
            self.assertEqual(details['equity_history_status'], 'UNAVAILABLE')
            self.assertEqual(details['equity_history'], [])

    def test_snapshot_saves_persist_equity_history_for_future_sessions(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root)
            session_id = store.create(self.cfg)
            engine = Engine(self.cfg)
            store.save(session_id, engine.state, snapshot=self.snapshot(0))
            store.save(session_id, engine.state, snapshot=self.snapshot(1))
            rows = store.db.execute('SELECT session_id, equity, equity_lower_bound, mark_status FROM equity_samples ORDER BY seq').fetchall()
            store.close()

            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row[0] == session_id for row in rows))
            self.assertTrue(all(row[3] for row in rows))

    def test_start_rejects_duplicate_active_worker_without_shelling_out(self):
        from nifty_paper.dashboard_control import PaperSessionController

        controller = PaperSessionController(ROOT)
        with patch.object(controller, 'status', return_value={'status': 'RUNNING', 'id': 'active', 'worker_lock_held': True}) as status_mock:
            with patch.object(controller, '_run_cli') as run_mock:
                with self.assertRaisesRegex(RuntimeError, 'already active'):
                    controller.start(source='public', duration_minutes=60, capital=1_000_000)
        status_mock.assert_called_once_with('public')
        run_mock.assert_not_called()

    def test_stop_targets_expected_session(self):
        from nifty_paper.dashboard_control import PaperSessionController

        controller = PaperSessionController(ROOT)
        with patch.object(controller, 'status', return_value={'status': 'RUNNING', 'id': 'newer', 'worker_lock_held': True}):
            with patch.object(controller, '_run_cli') as run_mock:
                with self.assertRaisesRegex(RuntimeError, 'different session'):
                    controller.stop('public', expected_session_id='older')
        run_mock.assert_not_called()

    def test_source_check_uses_fixed_validation_demo_output(self):
        from nifty_paper.dashboard_control import PaperSessionController

        controller = PaperSessionController(ROOT)
        completed = Mock(stdout='{"status":"SOURCE_RESPONSE_RECEIVED"}', stderr='', returncode=0)
        with patch.object(controller, '_run_cli', return_value=completed) as run_mock:
            controller.check('demo')
        argv = run_mock.call_args.args[0]
        self.assertIn('check', argv)
        self.assertIn('demo', argv)
        self.assertIn(str(ROOT / 'runtime' / 'validation-demo'), argv)


if __name__ == '__main__':
    unittest.main()
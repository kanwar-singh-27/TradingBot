"""Offline synthetic tests: these fixtures demonstrate mechanics, not alpha."""

from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nifty_paper.engine import Engine
from nifty_paper.models import Config, Quote, Snapshot, UTC
from nifty_paper.strategy import select_candidate
from nifty_paper.store import Store


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 9, 17, 5, 0, tzinfo=UTC)
        self.cfg = Config(source='public_loose', capital=3_000_000)

    def snapshot(self, seconds=0, **cheap_changes):
        at = self.at + timedelta(seconds=seconds)
        bars = tuple((at - timedelta(minutes=60-i), 23000.0) for i in range(61))
        expiry = self.at + timedelta(days=5)
        expensive = Quote('SYNTHETIC-NIFTY-EXPENSIVE-PE', 'PE', 23050, expiry,
                          199.5, 200, 650, 650, 65, .40)
        cheap = Quote('SYNTHETIC-NIFTY-AFFORDABLE-PE', 'PE', 23000, expiry,
                      69.5, 70, 130, 130, 65, .15)
        return Snapshot(at, at, 23000, bars, (expensive, replace(cheap, **cheap_changes)),
                        'synthetic://diagnostic-fixture', 'PUBLIC_SNAPSHOT_SIMULATION')

    def test_affordable_positive_alternative_reaches_later_ask_fill(self):
        first = self.snapshot()
        self.assertEqual(select_candidate(first, self.cfg)[0], first.quotes[0])
        engine = Engine(self.cfg)
        event = engine.step(first, first.at)[0]
        self.assertEqual(event['action'], 'PAPER_ENTRY_INTENT')
        self.assertEqual(event['instrument'], first.quotes[1].instrument)
        second = self.snapshot(60, ask_units=65, bid_units=195)
        event = engine.step(second, second.at)[0]
        self.assertEqual(event['action'], 'PAPER_BUY')
        self.assertEqual(engine.state['position']['units'], 65)
        self.assertEqual(self.cfg.risk_fraction, .0025)
        self.assertLessEqual(event['price']*65 + 2*event['fee'], 7500)

    def test_all_failures_and_not_evaluated_are_explicit(self):
        engine = Engine(self.cfg)
        snap = self.snapshot(iv=0, ask=500, bid=490, ask_units=1)
        engine.step(snap, snap.at)
        self.assertTrue(hasattr(engine, 'last_decision'), 'Missing candidate diagnostics')
        trace = engine.last_decision['candidates'][1]
        self.assertEqual(trace['first_failed_gate'], 'INVALID_IV')
        self.assertTrue({'INVALID_IV', 'SPREAD_TOO_WIDE', 'INSUFFICIENT_DEPTH', 'RISK_TOO_HIGH'} <= set(trace['failed_gates']))
        self.assertEqual(trace['validations']['score']['status'], 'NOT_EVALUATED')
        self.assertIsNone(trace['quote_age_seconds'])
        self.assertEqual(trace['timestamp_scope'], 'CHAIN_SNAPSHOT_ONLY')
        self.assertIsNone(trace['score'])
        json.dumps(engine.last_decision, allow_nan=False)

    def test_strict_90_second_snapshot_age(self):
        snap = self.snapshot()
        engine = Engine(self.cfg)
        engine.step(snap, snap.at + timedelta(seconds=105))
        self.assertEqual(engine.state['reason'], 'STALE_OR_FUTURE_DATA')
        self.assertIsNone(engine.state['pending'])

    def test_diagnostic_mode_never_creates_exposure_or_charges(self):
        self.assertIn('diagnostic', Config.__dataclass_fields__, 'Missing dry-run config')
        engine = Engine(replace(self.cfg, diagnostic=True))
        for offset in (0, 60, 120):
            snap = self.snapshot(offset)
            engine.step(snap, snap.at)
            self.assertIsNone(engine.state['position'])
            self.assertIsNone(engine.state['pending'])
        self.assertEqual(engine.state['cash'], self.cfg.capital)
        self.assertEqual(engine.state['fees_paid'], 0)
        self.assertEqual(engine.state['entries'], 0)
        self.assertEqual(engine.last_decision['selected_decision'], 'WOULD_CREATE_ENTRY_INTENT')

    def test_no_strategy_proposal_can_bypass_risk(self):
        snap = self.snapshot()
        engine = Engine(self.cfg)
        with patch('nifty_paper.engine.select_candidate', return_value=(snap.quotes[0], {'net_ev_rupees': 9999})):
            engine.step(snap, snap.at)
        self.assertIsNone(engine.state['position'])
        self.assertIsNone(engine.state['pending'])

    def test_decisions_persist_without_heartbeat_double_counting(self):
        snap = self.snapshot()
        engine = Engine(self.cfg)
        events = engine.step(snap, snap.at)
        self.assertTrue(hasattr(engine, 'last_decision'), 'Missing candidate diagnostics')
        with TemporaryDirectory() as directory:
            store = Store(directory)
            sid = store.create(self.cfg)
            store.save(sid, engine.state, events, snap, decision=engine.last_decision)
            store.save(sid, engine.state)
            store.save(sid, engine.state, decision=engine.last_decision)
            from nifty_paper.diagnostics import journal_diagnostics
            report = journal_diagnostics(store.db, sid)
            self.assertEqual(report['summary']['evaluations'], 1)
            self.assertEqual(report['summary']['funnel']['discovered'], 2)
            self.assertEqual(report['summary']['funnel']['after_risk'], 1)
            self.assertEqual(report['summary']['funnel']['after_score'], 1)
            self.assertEqual(len(report['latest']['candidates']), 2)
            self.assertEqual(report['summary']['score_statistics']['count'], 2)
            store.close()

    def test_trace_is_deterministic_and_uses_no_future_bars(self):
        snap = self.snapshot()
        future = replace(snap, bars=snap.bars + ((snap.at+timedelta(minutes=1), 999999.0),))
        a, b = Engine(self.cfg), Engine(self.cfg)
        a.step(snap, snap.at)
        b.step(future, future.at)
        self.assertEqual(a.last_decision['candidates'], b.last_decision['candidates'])
        self.assertEqual(a.last_decision['decision_id'], b.last_decision['decision_id'])

    def test_summary_uses_exact_score_buckets(self):
        from nifty_paper.diagnostics import statistics
        stats = statistics([-2, 0, 2, 4])
        self.assertEqual((stats['negative'], stats['zero'], stats['positive']), (1, 1, 2))
        self.assertEqual(stats['mean'], 1)
        self.assertEqual(stats['median'], 1)
        self.assertEqual(stats['percentiles']['25'], -0.5)

    def test_cash_gate_is_independent_of_risk_gate(self):
        engine = Engine(self.cfg)
        engine.state['cash'] = 100
        snap = self.snapshot()
        engine.step(snap, snap.at)
        trace = engine.last_decision['candidates'][1]
        self.assertEqual(trace['validations']['cash']['status'], 'FAIL')
        self.assertIn('INSUFFICIENT_CASH', trace['failed_gates'])
        self.assertIsNone(engine.state['pending'])

    def test_hard_entry_limits_are_not_overridden_by_proposals(self):
        for change, code in (({'entries': 6}, 'MAX_ENTRIES_REACHED'),
                             ({'consecutive_losses': 3}, 'CONSECUTIVE_LOSS_LIMIT'),
                             ({'halted': True}, 'HALT_LATCHED')):
            with self.subTest(code=code):
                engine = Engine(self.cfg)
                engine.state.update(change)
                snap = self.snapshot()
                with patch('nifty_paper.engine.select_candidate', return_value=(snap.quotes[1], {'net_ev_rupees': 999})):
                    engine.step(snap, snap.at)
                self.assertIsNone(engine.state['pending'])
                self.assertIn(code, engine.last_decision['candidates'][1]['failed_gates'])

    def test_snapshot_duplicate_has_no_second_fill(self):
        engine = Engine(self.cfg)
        snap = self.snapshot()
        engine.step(snap, snap.at)
        engine.step(snap, snap.at+timedelta(seconds=1))
        self.assertEqual(engine.state['entries'], 0)
        self.assertIn('DUPLICATE_OR_OUT_OF_ORDER', engine.last_decision['candidates'][1]['failed_gates'])

    def test_ask_envelope_rejection_is_specific(self):
        engine = Engine(self.cfg)
        snap = self.snapshot()
        engine.step(snap, snap.at)
        later = self.snapshot(60, bid=71.5, ask=72)
        engine.step(later, later.at)
        self.assertEqual(engine.state['entries'], 0)
        self.assertIn('ASK_ENVELOPE_EXCEEDED', engine.last_decision['candidates'][1]['failed_gates'])

    def test_execution_checks_are_explicit_before_intent(self):
        engine = Engine(self.cfg)
        snap = self.snapshot()
        engine.step(snap, snap.at)
        gates = engine.last_decision['candidates'][1]['validations']
        self.assertIn('later_snapshot', gates)
        self.assertEqual(gates['later_snapshot']['status'], 'NOT_EVALUATED')

    def test_missing_quote_fields_cannot_crash_diagnostics(self):
        engine = Engine(self.cfg)
        snap = self.snapshot(iv=float('nan'), expiry=None)
        engine.step(snap, snap.at)
        trace = engine.last_decision['candidates'][1]
        self.assertIn('INVALID_IV', trace['failed_gates'])
        self.assertIn('INVALID_EXPIRY', trace['failed_gates'])
        json.dumps(engine.last_decision, allow_nan=False)

    def test_old_journal_report_exposes_reasons_without_fake_traces(self):
        from nifty_paper.diagnostics import journal_diagnostics
        with TemporaryDirectory() as directory:
            store = Store(directory)
            sid = store.create(self.cfg)
            engine = Engine(self.cfg)
            engine.state.pop('diagnostic_schema_version', None)
            store.save(sid, engine.state, [{'action': 'NO_TRADE', 'reason': 'MARKET_CLOSED'}])
            report = journal_diagnostics(store.db, sid)
            store.close()
            self.assertEqual(report['status'], 'UNAVAILABLE')
            self.assertIsNone(report['latest'])
            self.assertEqual(report.get('recorded_reasons'), {'MARKET_CLOSED': 1})

    def test_replay_is_read_only_and_creates_no_worker(self):
        from nifty_paper.replay import diagnose
        with TemporaryDirectory() as directory:
            store = Store(directory)
            sid = store.create(self.cfg)
            engine = Engine(self.cfg)
            snap = self.snapshot()
            store.save(sid, engine.state, [{'action': 'NO_TRADE', 'reason': 'LOT_EXCEEDS_RISK_BUDGET'}], snap)
            # Old decision-time proxy must be contemporaneous with the fixture.
            stamp = snap.at.isoformat()
            store.db.execute('UPDATE snapshots SET recorded=?', (stamp,))
            store.db.execute('UPDATE events SET recorded=?', (stamp,))
            store.db.commit()
            store.close()
            path = Path(directory) / 'paper.sqlite3'
            before = path.read_bytes()
            with patch('subprocess.Popen', side_effect=AssertionError('No workers')), patch('socket.create_connection', side_effect=AssertionError('Offline only')):
                report = diagnose(directory, sid)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(report['summary']['trades_taken'], 0)
            self.assertEqual(report['summary']['funnel']['after_score'], 1)
            self.assertEqual(report['latest']['selected_decision'], 'WOULD_CREATE_ENTRY_INTENT')

    def test_unrelated_malformed_candidate_cannot_block_protective_exit(self):
        for changes in ({'strike': 5e-324}, {'ask': 1e30}, {'bid_units': 10**309}):
            with self.subTest(changes=changes):
                engine = Engine(self.cfg)
                for offset in (0, 60, 120):
                    snap = self.snapshot(offset)
                    engine.step(snap, snap.at, closing=offset == 120)
                later = self.snapshot(180)
                later = replace(later, quotes=(replace(later.quotes[0], **changes), later.quotes[1]))
                result = engine.step(later, later.at, closing=True)
                self.assertEqual(result[0]['action'], 'PAPER_SELL')
                self.assertIsNone(engine.state['position'])

    def test_nonfinite_iv_does_not_lose_exit_event_during_save(self):
        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                sid = store.create(self.cfg)
                engine = Engine(self.cfg)
                for offset in (0, 60, 120, 180):
                    snap = self.snapshot(offset, iv=float('nan')) if offset == 180 else self.snapshot(offset)
                    events = engine.step(snap, snap.at, closing=offset >= 120)
                    store.save(sid, engine.state, events, snap, decision=engine.last_decision)
                self.assertIn('PAPER_SELL', [e['action'] for e in store.events(sid)])
                self.assertEqual(store.latest()['state']['completed_trades'], 1)
            finally:
                store.close()

    def test_current_mark_loss_breach_is_reflected_in_trace(self):
        engine = Engine(replace(self.cfg, daily_loss_fraction=.0001))
        for offset in (0, 60):
            snap = self.snapshot(offset)
            engine.step(snap, snap.at)
        snap = self.snapshot(120, bid=65, ask=65.5)
        engine.step(snap, snap.at)
        self.assertTrue(engine.state['halted'])
        self.assertEqual(engine.last_decision['candidates'][1]['validations']['daily_loss']['status'], 'FAIL')
        self.assertEqual(engine.last_decision['candidates'][1]['validations']['halt']['status'], 'FAIL')

    def test_closing_records_pending_buy_cancellation(self):
        engine = Engine(self.cfg)
        snap = self.snapshot()
        engine.step(snap, snap.at)
        snap = self.snapshot(60)
        events = engine.step(snap, snap.at, closing=True)
        self.assertEqual(events[0]['action'], 'CANCEL_PAPER')
        self.assertEqual(events[0]['instrument'], snap.quotes[1].instrument)
        self.assertIsNone(engine.state['pending'])

    def test_new_no_data_session_is_not_labelled_as_old_schema(self):
        from nifty_paper.diagnostics import journal_diagnostics
        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                sid = store.create(self.cfg)
                engine = Engine(self.cfg)
                store.save(sid, engine.state, [{'action': 'NO_TRADE', 'reason': 'DATA_UNAVAILABLE'}])
                report = journal_diagnostics(store.db, sid)
                self.assertEqual(report['status'], 'NO_EVALUATIONS')
                self.assertEqual(report['summary']['funnel']['discovered'], 0)
                self.assertEqual(report['recorded_reasons']['DATA_UNAVAILABLE'], 1)
            finally:
                store.close()

    def test_null_normalized_quote_renders_without_inventing_values(self):
        from nifty_paper.store import observation_payload
        from nifty_paper.dashboard_view import option_rows
        snap = self.snapshot(ask=float('nan'))
        rows = option_rows(observation_payload(snap), strike_distance=500)
        row = next(row for row in rows if row['instrument'] == snap.quotes[1].instrument)
        self.assertIsNone(row['ask'])
        self.assertIsNone(row['spread'])

    def test_replay_counts_every_event_with_same_recording_time(self):
        from nifty_paper.replay import diagnose
        with TemporaryDirectory() as directory:
            store = Store(directory)
            sid = store.create(self.cfg)
            store.save(sid, Engine(self.cfg).state, [
                {'action': 'NO_TRADE', 'reason': 'DATA_UNAVAILABLE'},
                {'action': 'END', 'reason': 'SESSION_FINISHED'}])
            store.close()
            report = diagnose(directory, sid)
            self.assertEqual(report['recorded_reasons'], {'DATA_UNAVAILABLE': 1, 'SESSION_FINISHED': 1})


class JournalRoutingTests(unittest.TestCase):
    def test_alternate_book_activity_blocks_start(self):
        from nifty_paper.dashboard_control import PaperSessionController
        with TemporaryDirectory() as directory:
            controller = PaperSessionController(directory)
            with patch.object(controller, 'status', return_value={'worker_lock_held': False, 'alternate_book_blocked': True}), patch.object(controller, '_run_cli') as run_cli:
                with self.assertRaisesRegex(RuntimeError, 'alternate'):
                    controller.start('public_loose', 60, 4_000_000)
                run_cli.assert_not_called()

    def test_cli_and_dashboard_choose_same_default_book(self):
        from nifty_paper import cli
        from nifty_paper.dashboard_data import JournalReader
        self.assertTrue(hasattr(cli, 'resolve_output'), 'Missing shared journal routing')
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(cli.resolve_output(root, 'public_loose'), JournalReader(root).output_root('public_loose'))

    def test_two_existing_loose_books_require_explicit_choice(self):
        from nifty_paper import cli
        self.assertTrue(hasattr(cli, 'resolve_output'), 'Missing journal ambiguity guard')
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('public-loose', 'public_loose'):
                folder = root / 'runtime' / name
                folder.mkdir(parents=True)
                sqlite3.connect(folder / 'paper.sqlite3').close()
            with self.assertRaisesRegex(ValueError, 'Multiple'):
                cli.resolve_output(root, 'public_loose')
            explicit = root / 'runtime' / 'public-loose'
            self.assertEqual(cli.resolve_output(root, 'public_loose', explicit), explicit)


if __name__ == '__main__':
    unittest.main()
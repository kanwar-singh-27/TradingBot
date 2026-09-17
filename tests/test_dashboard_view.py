from datetime import datetime, timedelta, timezone
import unittest


from nifty_paper.models import Config


class DashboardViewTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 17, 5, 5, tzinfo=timezone.utc)
        self.config = Config(source='demo', duration_minutes=30, poll_seconds=1, capital=1_000_000)
        self.session = {
            'id': 'demo-session',
            'started': '2026-09-17T05:00:00+00:00',
            'heartbeat': '2026-09-17T05:04:55+00:00',
            'config': {
                'source': 'demo',
                'duration_minutes': 30,
                'poll_seconds': 1,
                'capital': 1_000_000,
                'risk_fraction': 0.0025,
                'daily_loss_fraction': 0.01,
                'max_spread_fraction': 0.01,
                'max_age_seconds': 90,
                'hold_minutes': 15,
                'fee_per_order': 25,
                'fee_rate': 0.002,
                'slippage_fraction': 0.001,
            },
            'state': {
                'status': 'RUNNING',
                'reason': 'POSITION_MONITORED',
                'cash': 993461.99,
                'equity': 999900.0,
                'equity_lower_bound': 993436.99,
                'realized_pnl': -120.0,
                'fees_paid': 76.02,
                'entries': 1,
                'completed_trades': 0,
                'consecutive_losses': 1,
                'halted': False,
                'risk_equity': 993436.99,
                'mark_status': 'STALE_LAST_KNOWN',
                'last_spot': 23125.0,
                'position': {
                    'instrument': 'DEMO-NIFTY-CE',
                    'right': 'CE',
                    'strike': 23200,
                    'expiry': '2026-09-24T05:00:00+00:00',
                    'units': 65,
                    'entry_price': 100.1,
                    'entry_fee': 38.01,
                    'entered_at': '2026-09-17T05:01:00+00:00',
                    'last_bid': 99.0,
                    'mark_at': '2026-09-17T05:02:00+00:00',
                    'trade_id': 'trade-1',
                },
                'pending': {'side': 'SELL', 'instrument': 'DEMO-NIFTY-CE', 'at': '2026-09-17T05:04:00+00:00', 'reason': 'SESSION_END_OR_STOP'},
                'planned_end_utc': '2026-09-17T05:30:00+00:00',
                'source_as_of': '2026-09-17T05:04:00+00:00',
                'source_received_at': '2026-09-17T05:04:00+00:00',
                'source_url': 'synthetic://deterministic-demo',
                'analysis': {'reason': 'POSITIVE_BASELINE_SCENARIO_SCORE', 'net_ev_rupees': 100.0},
            },
            'events': [],
            'snapshots': [],
            'equity_history_status': 'UNAVAILABLE',
            'equity_history': [],
        }

    def test_reason_catalog_exposes_plain_language_and_raw_code(self):
        from nifty_paper.dashboard_view import explain_reason

        details = explain_reason('EXIT_QUOTE_UNAVAILABLE')
        self.assertEqual(details['code'], 'EXIT_QUOTE_UNAVAILABLE')
        self.assertIn('Exit quote unavailable', details['title'])
        self.assertIn('later usable bid', details['detail'])

    def test_overview_marks_stale_equity_as_not_currently_usable(self):
        from nifty_paper.dashboard_view import build_overview

        overview = build_overview(self.session, now=self.now)
        self.assertEqual(overview['valuation_status'], 'STALE_LAST_KNOWN')
        self.assertIsNone(overview['usable_equity'])
        self.assertLess(overview['conservative_equity'], overview['last_known_equity'])
        self.assertIsNone(overview['equity_history_notice'])

    def test_overview_reports_missing_historical_equity(self):
        from nifty_paper.dashboard_view import build_overview

        completed = {**self.session, 'state': {**self.session['state'], 'status': 'COMPLETED', 'position': None, 'pending': None, 'mark_status': 'NO_POSITION'}}
        overview = build_overview(completed, now=self.now)
        self.assertEqual(overview['equity_history_notice'], 'Historical equity samples unavailable.')

    def test_completed_trades_require_stable_trade_ids(self):
        from nifty_paper.dashboard_view import completed_trades

        events = [
            {'action': 'PAPER_BUY', 'instrument': 'X', 'price': 10, 'units': 1, 'fee': 1, 'recorded': '2026-09-17T05:01:00+00:00'},
            {'action': 'PAPER_SELL', 'instrument': 'X', 'price': 11, 'units': 1, 'fee': 1, 'net_pnl': 0, 'recorded': '2026-09-17T05:10:00+00:00'},
        ]

        trades, notice = completed_trades(events)
        self.assertEqual(trades, [])
        self.assertIn('Auditable buy/sell linkage unavailable', notice)

    def test_selection_metrics_expose_candidate_diagnostics(self):
        from nifty_paper.dashboard_view import selection_metrics

        session = {
            **self.session,
            'state': {
                **self.session['state'],
                'analysis': {
                    'reason': 'CASH_BETTER_AFTER_COSTS',
                    'model': 'shrunk-normal-baseline-v1-UNVALIDATED',
                    'horizon_minutes': 15,
                    'expected_log_return': -0.0002,
                    'return_std': 0.0008,
                    'p_up_model_only': 0.41,
                    'candidate_counts': {
                        'total': 192,
                        'valid': 147,
                        'days_window': 147,
                        'strike_window': 20,
                        'spread_ok': 20,
                        'depth_ok': 20,
                        'positive_score': 0,
                    },
                    'top_candidates': [
                        {
                            'instrument': 'OPTIDXNIFTY22-09-2026CE23450.00',
                            'right': 'CE',
                            'strike': 23450.0,
                            'ask': 43.4,
                            'lot_size': 65,
                            'score': -2917.66,
                            'spread_pct': 0.346,
                            'scenario_means': [-1638.16, -676.47, 418.39],
                            'depth_ask': 2015,
                        }
                    ],
                },
            },
        }

        metrics = selection_metrics(session)
        self.assertEqual(metrics['candidate_counts']['positive_score'], 0)
        self.assertEqual(metrics['top_candidates'][0]['instrument'], 'OPTIDXNIFTY22-09-2026CE23450.00')
        self.assertEqual(metrics['top_candidates'][0]['entry_cost_one_lot'], 2823.82)
        self.assertEqual(metrics['top_candidates'][0]['min_cash_for_entry'], 2854.47)
        self.assertEqual(metrics['top_candidates'][0]['min_capital_for_risk_gate'], 1154048.0)

    def test_overview_preserves_public_loose_source_label(self):
        from nifty_paper.dashboard_view import build_overview

        session = {**self.session, 'config': {**self.session['config'], 'source': 'public_loose', 'poll_seconds': 60}}
        overview = build_overview(session, now=self.now)
        self.assertEqual(overview['source'], 'public_loose')


if __name__ == '__main__':
    unittest.main()
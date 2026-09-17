import unittest
from unittest.mock import Mock, patch

from pathlib import Path


try:
    from streamlit.testing.v1 import AppTest
except ModuleNotFoundError:
    AppTest = None


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'dashboard.py'


@unittest.skipIf(AppTest is None, 'streamlit not installed yet')
class DashboardUiTests(unittest.TestCase):
    def test_empty_state_renders_without_starting_a_worker(self):
        from nifty_paper.dashboard_app import main

        reader = Mock()
        reader.list_sessions.return_value = []
        reader.load_latest.return_value = {'status': 'NOT_STARTED', 'source': 'public', 'output': 'runtime/public'}
        controller = Mock()

        with patch('nifty_paper.dashboard_app.make_reader', return_value=reader), patch('nifty_paper.dashboard_app.make_controller', return_value=controller):
            app = AppTest.from_file(str(APP))
            app.run()

        controller.start.assert_not_called()
        self.assertIn('No paper sessions recorded yet.', '\n'.join(element.value for element in app.info))

    def test_rerun_without_button_click_does_not_restart_worker(self):
        from nifty_paper.dashboard_app import main

        reader = Mock()
        reader.list_sessions.return_value = []
        reader.load_latest.return_value = {'status': 'NOT_STARTED', 'source': 'public', 'output': 'runtime/public'}
        controller = Mock()

        with patch('nifty_paper.dashboard_app.make_reader', return_value=reader), patch('nifty_paper.dashboard_app.make_controller', return_value=controller):
            app = AppTest.from_file(str(APP))
            app.run()
            app.run()

        controller.start.assert_not_called()

    def test_dashboard_has_no_live_trading_toggle_or_manual_buy_button(self):
        from nifty_paper.dashboard_app import main

        reader = Mock()
        reader.list_sessions.return_value = []
        reader.load_latest.return_value = {'status': 'NOT_STARTED', 'source': 'public', 'output': 'runtime/public'}
        controller = Mock()

        with patch('nifty_paper.dashboard_app.make_reader', return_value=reader), patch('nifty_paper.dashboard_app.make_controller', return_value=controller):
            app = AppTest.from_file(str(APP))
            app.run()

        text = '\n'.join(element.value for element in app.markdown)
        button_labels = [button.label for button in app.button]
        self.assertNotIn('Live trading', text)
        self.assertNotIn('Buy', button_labels)
        self.assertNotIn('Sell', button_labels)

    def test_dashboard_offers_public_loose_source(self):
        reader = Mock()
        reader.list_sessions.return_value = []
        reader.load_latest.return_value = {'status': 'NOT_STARTED', 'source': 'public', 'output': 'runtime/public'}
        controller = Mock()

        with patch('nifty_paper.dashboard_app.make_reader', return_value=reader), patch('nifty_paper.dashboard_app.make_controller', return_value=controller):
            app = AppTest.from_file(str(APP))
            app.run()

        radio_options = []
        for radio in app.radio:
            radio_options.extend(radio.options)
        self.assertIn('public_loose', radio_options)

    def test_public_loose_defaults_to_higher_virtual_capital(self):
        from nifty_paper.dashboard_app import default_virtual_capital

        self.assertEqual(default_virtual_capital('public_loose'), 4_000_000.0)
        self.assertEqual(default_virtual_capital('public'), 1_000_000.0)
        self.assertEqual(default_virtual_capital('demo'), 1_000_000.0)

    def test_dashboard_defaults_refresh_cadence_to_off(self):
        reader = Mock()
        reader.list_sessions.return_value = []
        reader.load_latest.return_value = {'status': 'NOT_STARTED', 'source': 'public', 'output': 'runtime/public'}
        controller = Mock()

        with patch('nifty_paper.dashboard_app.make_reader', return_value=reader), patch('nifty_paper.dashboard_app.make_controller', return_value=controller):
            app = AppTest.from_file(str(APP))
            app.run()

        refresh_select = next(item for item in app.selectbox if item.label == 'UI refresh cadence')
        self.assertEqual(refresh_select.value, 'Off')

    def test_forecast_hides_one_lot_capital_needed_block(self):
        reader = Mock()
        reader.list_sessions.return_value = [{'id': 'demo-session', 'started': '2026-09-17T05:00:00+00:00', 'state': {'status': 'RUNNING'}}]
        reader.load_latest.return_value = {
            'id': 'demo-session',
            'status': 'RUNNING',
            'source': 'public',
            'output': 'runtime/public',
            'state': {'status': 'RUNNING'}
        }
        reader.load_session.return_value = {
            'id': 'demo-session',
            'started': '2026-09-17T05:00:00+00:00',
            'heartbeat': '2026-09-17T05:04:55+00:00',
            'config': {
                'source': 'public',
                'duration_minutes': 60,
                'poll_seconds': 60,
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
                'reason': 'CASH_BETTER_AFTER_COSTS',
                'cash': 1_000_000,
                'equity': 1_000_000,
                'equity_lower_bound': 1_000_000,
                'realized_pnl': 0,
                'fees_paid': 0,
                'entries': 0,
                'completed_trades': 0,
                'consecutive_losses': 0,
                'halted': False,
                'risk_equity': 1_000_000,
                'mark_status': 'NO_POSITION',
                'pending': None,
                'position': None,
                'planned_end_utc': '2026-09-17T06:00:00+00:00',
                'source_as_of': '2026-09-17T05:04:00+00:00',
                'source_received_at': '2026-09-17T05:04:30+00:00',
                'source_url': 'fixture',
                'classification': 'PUBLIC_SNAPSHOT_SIMULATION',
                'analysis': {
                    'reason': 'CASH_BETTER_AFTER_COSTS',
                    'model': 'shrunk-normal-baseline-v1-UNVALIDATED',
                    'horizon_minutes': 15,
                    'expected_log_return': 0.0,
                    'return_std': 0.001,
                    'p_up_model_only': 0.5,
                    'candidate_counts': {'total': 1, 'valid': 1, 'days_window': 1, 'strike_window': 1, 'spread_ok': 1, 'depth_ok': 1, 'positive_score': 0},
                    'top_candidates': [{'instrument': 'X', 'right': 'CE', 'strike': 23000, 'lot_size': 65, 'bid': 10, 'ask': 10.1, 'spread_pct': 0.2, 'depth_bid': 65, 'depth_ask': 65, 'iv': 0.1, 'scenario_means': [1, 2, 3], 'score': -1}],
                },
            },
            'events': [],
            'snapshots': [],
            'equity_history_status': 'UNAVAILABLE',
            'equity_history': [],
            'source': 'public',
            'output': 'runtime/public',
        }
        controller = Mock()
        controller.status.return_value = {'status': 'NOT_STARTED', 'source': 'public', 'output': 'runtime/public'}

        with patch('nifty_paper.dashboard_app.make_reader', return_value=reader), patch('nifty_paper.dashboard_app.make_controller', return_value=controller):
            app = AppTest.from_file(str(APP))
            app.run()

        markdown_text = '\n'.join(element.value for element in app.markdown)
        self.assertNotIn('One-Lot Capital Needed', markdown_text)


if __name__ == '__main__':
    unittest.main()
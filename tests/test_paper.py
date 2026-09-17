import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
READY = (ROOT / 'nifty_paper' / 'engine.py').exists()
if READY:
    from nifty_paper.models import Config, Quote, Snapshot, UTC, IST
    from nifty_paper.feeds import parse_chain, parse_lots, parse_yahoo, FeedError, DemoFeed
    from nifty_paper.kite_auth import build_login_url, exchange_request_token, session_environment
    from nifty_paper.strategy import option_value, select_candidate
    from nifty_paper.engine import Engine
    from nifty_paper.store import Store, RunLock


class InstallationTests(unittest.TestCase):
    def test_paper_runtime_is_implemented(self):
        self.assertTrue(READY, 'Missing paper runtime: implement models, feeds, strategy, engine and store')


@unittest.skipUnless(READY, 'Runtime not implemented yet')
class PaperTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 9, 17, 5, 0, tzinfo=timezone.utc)
        self.cfg = Config(source='demo', duration_minutes=60, poll_seconds=1)

    def snapshot(self, offset=0, bid=99.0, ask=100.0, **changes):
        at = self.at + timedelta(seconds=offset)
        quote = Quote('NIFTY-TEST-CE', 'CE', 23000, at.replace(hour=10) + timedelta(days=5),
                      bid, ask, 650, 650, 65, .15)
        bars = tuple((at - timedelta(minutes=60-i), 23000 * (1.0001 ** i)) for i in range(61))
        return Snapshot(at, at, bars[-1][1], bars, (replace(quote, **changes),), 'fixture', 'DEMO_SYNTHETIC')

    def enter(self, engine):
        first = self.snapshot()
        with patch('nifty_paper.engine.select_candidate', return_value=(first.quotes[0], {'net_ev_rupees': 100})):
            engine.step(first, first.received_at)
            self.assertIsNone(engine.state['position'])
            self.assertEqual(engine.state['pending']['side'], 'BUY')
            second = self.snapshot(60)
            engine.step(second, second.received_at)
        return second

    def test_config_rejects_live_nan_and_fast_public_poll(self):
        for kwargs in ({'source': 'live'}, {'capital': float('nan')}, {'duration_minutes': 0},
                       {'duration_minutes': 376}, {'source': 'public', 'poll_seconds': 1},
                       {'risk_fraction': .5}, {'fee_rate': -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Config(**kwargs)
        Config(source='public_loose', duration_minutes=60, poll_seconds=60)

    def test_public_loose_can_select_candidate_when_conservative_public_stays_in_cash(self):
        bars = tuple((self.at - timedelta(minutes=60-i), 23000 / (1.00005 ** (60 - i))) for i in range(61))
        quote = Quote('NIFTY-TEST-PE', 'PE', 23050, self.at.replace(hour=10) + timedelta(days=5),
                      120, 121, 650, 650, 65, .10)
        snap = Snapshot(self.at, self.at, 23000, bars, (quote,), 'fixture', 'PUBLIC_SNAPSHOT_SIMULATION')

        conservative_quote, conservative_details = select_candidate(snap, Config(source='public', duration_minutes=60, poll_seconds=60))
        loose_quote, loose_details = select_candidate(snap, Config(source='public_loose', duration_minutes=60, poll_seconds=60))

        self.assertIsNone(conservative_quote)
        self.assertEqual(conservative_details['reason'], 'CASH_BETTER_AFTER_COSTS')
        self.assertIsNotNone(loose_quote)
        self.assertEqual(loose_details['reason'], 'POSITIVE_BASELINE_SCENARIO_SCORE')

    def test_option_parity_and_expiry_payoff(self):
        call = option_value(23000, 23000, 5 / 365, .15, 'CE')
        put = option_value(23000, 23000, 5 / 365, .15, 'PE')
        self.assertAlmostEqual(call, put, places=8)
        self.assertEqual(option_value(23100, 23000, 0, .15, 'CE'), 100)

    def test_lot_size_is_month_scoped_and_never_guessed(self):
        text = 'UNDERLYING,SYMBOL,SEP-26,OCT-26\nNIFTY 50,NIFTY,65,75\n'
        self.assertEqual(parse_lots(text, self.at.date()), 65)
        with self.assertRaises(FeedError):
            parse_lots(text, self.at.replace(month=11).date())

    def test_kite_env_file_provides_credentials_for_session_exchange(self):
        from nifty_paper.feeds import KiteFeed

        class FakeConnect:
            def __init__(self, api_key=None):
                self.api_key = api_key
                self.calls = []

            def set_access_token(self, token):
                self.calls.append(('set_access_token', token))

            def generate_session(self, request_token, api_secret):
                self.calls.append(('generate_session', request_token, api_secret))
                return {'access_token': 'generated_token'}

        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / '.env'
            env_path.write_text('KITE_API_KEY=demo_key\nKITE_API_SECRET=demo_secret\nKITE_REQUEST_TOKEN=demo_request\n', encoding='utf-8')
            with patch.dict('os.environ', {}, clear=True):
                with patch('nifty_paper.feeds._candidate_env_paths', return_value=[env_path]), \
                     patch('nifty_paper.feeds.KiteConnect', FakeConnect):
                    feed = KiteFeed()
                    self.assertEqual(feed.access_token, 'generated_token')
                    self.assertIn(('generate_session', 'demo_request', 'demo_secret'), feed.kite.calls)

    def test_exchange_request_token_uses_api_secret_and_returns_access_token(self):
        class FakeConnect:
            def __init__(self, api_key=None):
                self.api_key = api_key
                self.calls = []

            def generate_session(self, request_token, api_secret):
                self.calls.append(('generate_session', request_token, api_secret))
                return {'access_token': 'live_session_token'}

        token = exchange_request_token('demo_key', 'demo_secret', 'demo_request', kite_class=FakeConnect)
        self.assertEqual(token, 'live_session_token')

    def test_session_environment_uses_access_token_and_drops_request_token(self):
        env = session_environment({'KITE_API_KEY': 'demo_key', 'KITE_REQUEST_TOKEN': 'stale'}, 'live_session_token')
        self.assertEqual(env['KITE_ACCESS_TOKEN'], 'live_session_token')
        self.assertNotIn('KITE_REQUEST_TOKEN', env)

    def test_build_login_url_includes_redirect_uri(self):
        url = build_login_url('demo_key', 'http://127.0.0.1:8000')
        self.assertIn('api_key=demo_key', url)
        self.assertIn('redirect_uri=http%3A%2F%2F127.0.0.1%3A8000', url)

    def test_kite_feed_accepts_date_expiry_from_sdk_instruments(self):
        from nifty_paper.feeds import KiteFeed

        class FakeConnect:
            def __init__(self, api_key=None):
                self.api_key = api_key

            def set_access_token(self, token):
                self.access_token = token

            def instruments(self, exchange):
                return [
                    {
                        'name': 'NIFTY',
                        'segment': 'NFO-OPT',
                        'expiry': date(2026, 9, 24),
                        'lot_size': 75,
                        'strike': 23000,
                        'tradingsymbol': 'NIFTY26SEP23000CE',
                        'instrument_token': 123,
                    }
                ]

            def quote(self, symbols):
                return {'NSE:NIFTY50': {'last_price': 23000.0}}

        with patch.dict('os.environ', {'KITE_API_KEY': 'demo_key', 'KITE_ACCESS_TOKEN': 'session_token'}, clear=True):
            with patch('nifty_paper.feeds.KiteConnect', FakeConnect):
                feed = KiteFeed()
                self.assertEqual(feed.expiry, None)
                with self.assertRaises(FeedError) as context:
                    feed.fetch()
        self.assertNotIn('strptime() argument 1 must be str, not datetime.date', str(context.exception))

    def test_v3_chain_maps_fields_and_timestamp(self):
        leg = {'identifier': 'NIFTY-CE', 'underlying': 'NIFTY', 'expiryDate': '22-09-2026',
               'strikePrice': 23000, 'buyPrice1': 100, 'sellPrice1': 101,
               'buyQuantity1': 130, 'sellQuantity1': 195, 'impliedVolatility': 15}
        data = {'records': {'timestamp': '17-Sep-2026 10:30:00', 'underlyingValue': 23000,
                            'data': [{'CE': leg}]}}
        quotes, stamp, spot = parse_chain(data, 65)
        self.assertEqual(stamp, self.at)
        self.assertEqual((quotes[0].bid, quotes[0].ask, quotes[0].lot_size), (100, 101, 65))
        self.assertEqual(spot, 23000)
        leg['underlying'] = 'BANKNIFTY'
        with self.assertRaises(FeedError):
            parse_chain(data, 65)

    def test_yahoo_excludes_unfinished_and_wrong_day_bars(self):
        stamps = [self.at - timedelta(days=1), self.at - timedelta(minutes=2), self.at]
        data = {'chart': {'result': [{'timestamp': [int(t.timestamp()) for t in stamps],
                        'indicators': {'quote': [{'close': [22900, 23000, 23100]}]}}]}}
        bars = parse_yahoo(data, self.at)
        self.assertEqual(bars, ((stamps[1] + timedelta(minutes=1), 23000.0),))

    def test_expensive_option_loses_to_cash(self):
        snap = self.snapshot(bid=990, ask=1000)
        quote, details = select_candidate(snap, self.cfg)
        self.assertIsNone(quote)
        self.assertIn('candidate_counts', details)
        self.assertIn('top_candidates', details)

    def test_full_premium_budget_blocks_one_lot(self):
        engine = Engine(replace(self.cfg, capital=10000))
        snap = self.snapshot()
        with patch('nifty_paper.engine.select_candidate', return_value=(snap.quotes[0], {})):
            engine.step(snap, snap.received_at)
        self.assertIsNone(engine.state['pending'])
        self.assertEqual(engine.state['reason'], 'LOT_EXCEEDS_RISK_BUDGET')

    def test_entry_requires_later_snapshot_and_revalidated_budget(self):
        engine = Engine(replace(self.cfg, capital=4000000))
        self.enter(engine)
        self.assertEqual(engine.state['position']['units'], 65)
        self.assertGreater(engine.state['position']['entry_price'], 100)

    def test_duplicate_snapshot_cannot_fill(self):
        engine = Engine(replace(self.cfg, capital=4000000))
        snap = self.snapshot()
        with patch('nifty_paper.engine.select_candidate', return_value=(snap.quotes[0], {})):
            engine.step(snap, snap.received_at)
            engine.step(snap, snap.received_at + timedelta(seconds=1))
        self.assertIsNone(engine.state['position'])
        self.assertEqual(engine.state['reason'], 'DUPLICATE_OR_OUT_OF_ORDER')

    def test_stale_and_future_data_never_enters(self):
        for delta in (200, -20):
            engine = Engine(self.cfg)
            snap = self.snapshot()
            engine.step(snap, snap.at + timedelta(seconds=delta))
            self.assertIsNone(engine.state['pending'])
            self.assertEqual(engine.state['reason'], 'STALE_OR_FUTURE_DATA')

    def test_public_snapshot_allows_one_poll_interval_of_extra_age(self):
        engine = Engine(replace(self.cfg, source='public', poll_seconds=60))
        snap = replace(self.snapshot(), kind='PUBLIC_SNAPSHOT_SIMULATION')
        snap = replace(snap, at=snap.at.replace(hour=4, minute=0), received_at=snap.at.replace(hour=4, minute=1, second=45))
        with patch('nifty_paper.engine.select_candidate', return_value=(None, {'reason': 'NO_EDGE'})):
            engine.step(snap, snap.at + timedelta(seconds=105))
        self.assertEqual(engine.state['reason'], 'NO_EDGE')

    def test_invalid_quotes_never_fill(self):
        for changes in ({'bid': -1}, {'ask': 0}, {'bid': 102}, {'iv': float('nan')}, {'ask_units': 0}):
            snap = self.snapshot(**changes)
            self.assertFalse(snap.quotes[0].valid())

    def test_exit_uses_later_bid_and_fees(self):
        engine = Engine(replace(self.cfg, capital=4000000))
        self.enter(engine)
        exit_signal = self.snapshot(120, bid=120, ask=121)
        engine.step(exit_signal, exit_signal.at, closing=True)
        self.assertIsNotNone(engine.state['position'])
        fill = self.snapshot(180, bid=119, ask=120)
        engine.step(fill, fill.at, closing=True)
        self.assertIsNone(engine.state['position'])
        self.assertEqual(engine.state['completed_trades'], 1)
        self.assertGreater(engine.state['realized_pnl'], 0)
        self.assertLess(engine.state['realized_pnl'], (119 - 100) * 65)

    def test_fill_events_include_trade_identity_and_instrument_metadata(self):
        engine = Engine(replace(self.cfg, capital=4000000))
        first = self.snapshot()
        with patch('nifty_paper.engine.select_candidate', return_value=(first.quotes[0], {'net_ev_rupees': 100})):
            intent = engine.step(first, first.received_at)[0]
            buy = engine.step(self.snapshot(60), self.snapshot(60).received_at)[0]
        sell_intent = engine.step(self.snapshot(120, bid=120, ask=121), self.snapshot(120, bid=120, ask=121).at, closing=True)[0]
        sell = engine.step(self.snapshot(180, bid=119, ask=120), self.snapshot(180, bid=119, ask=120).at, closing=True)[0]

        self.assertEqual(intent['instrument'], 'NIFTY-TEST-CE')
        self.assertEqual(buy['instrument'], 'NIFTY-TEST-CE')
        self.assertEqual(buy['right'], 'CE')
        self.assertIn('trade_id', buy)
        self.assertEqual(sell_intent['trade_id'], buy['trade_id'])
        self.assertEqual(sell['trade_id'], buy['trade_id'])
        self.assertEqual(sell['instrument'], 'NIFTY-TEST-CE')

    def test_missing_exit_quote_retains_unresolved_position(self):
        engine = Engine(replace(self.cfg, capital=4000000))
        self.enter(engine)
        engine.finish()
        self.assertEqual(engine.state['status'], 'UNRESOLVED')
        self.assertIsNotNone(engine.state['position'])
        self.assertLess(engine.state['equity_lower_bound'], self.cfg.capital * 4)

    def test_depth_shortfall_defers_exit_without_fake_fill(self):
        engine = Engine(replace(self.cfg, capital=4000000))
        self.enter(engine)
        snap = self.snapshot(120)
        engine.step(snap, snap.at, closing=True)
        snap = self.snapshot(180, bid_units=0)
        engine.step(snap, snap.at, closing=True)
        self.assertIsNotNone(engine.state['position'])
        self.assertEqual(engine.state['reason'], 'EXIT_QUOTE_UNAVAILABLE')

    def test_exit_does_not_require_iv_or_ask_depth(self):
        engine = Engine(replace(self.cfg, capital=4000000))
        self.enter(engine)
        snap = self.snapshot(120)
        engine.step(snap, snap.at, closing=True)
        snap = self.snapshot(180, iv=0, ask_units=0)
        engine.step(snap, snap.at, closing=True)
        self.assertIsNone(engine.state['position'])

    def test_source_classification_cannot_change_mid_session(self):
        engine = Engine(self.cfg)
        snap = replace(self.snapshot(), kind='PUBLIC_SNAPSHOT_SIMULATION')
        engine.step(snap, snap.at)
        self.assertIsNone(engine.state['pending'])
        self.assertEqual(engine.state['reason'], 'SOURCE_CLASSIFICATION_MISMATCH')

    def test_missing_mark_is_explicit_and_risk_uses_loss_bound(self):
        engine = Engine(replace(self.cfg, capital=4000000))
        self.enter(engine)
        snap = replace(self.snapshot(120), quotes=())
        engine.step(snap, snap.at)
        self.assertEqual(engine.state['mark_status'], 'STALE_LAST_KNOWN')
        self.assertEqual(engine.state['risk_equity'], engine.state['equity_lower_bound'])

    def test_pending_entry_is_cancelled_outside_public_entry_window(self):
        engine = Engine(replace(self.cfg, source='public', poll_seconds=60, capital=4000000))
        snap = replace(self.snapshot(), kind='PUBLIC_SNAPSHOT_SIMULATION')
        snap = replace(snap, at=snap.at.replace(hour=8, minute=59), received_at=snap.at.replace(hour=8, minute=59))
        with patch('nifty_paper.engine.select_candidate', return_value=(snap.quotes[0], {})):
            engine.step(snap, snap.at)
            self.assertIsNotNone(engine.state['pending'])
            later = replace(snap, at=snap.at+timedelta(minutes=1), received_at=snap.at+timedelta(minutes=1))
            engine.step(later, later.at)
        self.assertIsNone(engine.state['position'])
        self.assertIsNone(engine.state['pending'])

    def test_yahoo_denial_does_not_disable_nse_exit_feed(self):
        from urllib.error import HTTPError
        from nifty_paper.feeds import PublicFeed, YAHOO, NSE_INFO
        feed = PublicFeed()
        with patch('nifty_paper.feeds.urlopen', side_effect=HTTPError(YAHOO, 429, 'rate limit', {}, None)):
            with self.assertRaises(FeedError):
                feed.get(YAHOO)
        with patch('nifty_paper.feeds.urlopen') as opening:
            opening.return_value.__enter__.return_value.read.return_value = b'{"expiryDates": []}'
            self.assertEqual(feed.get(NSE_INFO), {'expiryDates': []})

    def test_demo_is_explicit_and_exercises_roundtrip(self):
        feed = DemoFeed()
        engine = Engine(self.cfg)
        for i in range(25):
            snap = feed.fetch()
            engine.step(snap, snap.at, closing=i >= 21)
        engine.finish()
        self.assertEqual(snap.kind, 'DEMO_SYNTHETIC')
        self.assertGreaterEqual(engine.state['completed_trades'], 1)

    def test_store_roundtrip_and_lock_exclusivity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with RunLock(root):
                with self.assertRaises(RuntimeError):
                    with RunLock(root):
                        pass
            store = Store(root)
            session = store.create(self.cfg)
            engine = Engine(self.cfg)
            store.save(session, engine.state, [{'action': 'NO_TRADE', 'reason': 'test'}])
            self.assertEqual(store.latest()['state']['cash'], self.cfg.capital)
            store.stop(session)
            self.assertTrue(store.stop_requested(session))
            store.close()


if __name__ == '__main__':
    unittest.main()
"""Public reference data; explicit failures, no authentication or access bypass."""

import csv
import io
import json
import math
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .models import IST, UTC, Quote, Snapshot

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None

NSE_INFO = 'https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY'
NSE_CHAIN = 'https://www.nseindia.com/api/option-chain-v3?'
NSE_LOTS = 'https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv'
YAHOO = 'https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1m&range=1d'


def _candidate_env_paths():
    repo_root = Path(__file__).resolve().parents[1]
    cwd = Path.cwd()
    candidates = [cwd / '.env', repo_root / '.env']
    seen = set()
    result = []
    for path in candidates:
        normalized = path.resolve()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def load_env_file(path=None):
    candidates = [Path(path)] if path else _candidate_env_paths()
    for env_path in candidates:
        try:
            if not env_path.exists():
                continue
            for raw in env_path.read_text(encoding='utf-8').splitlines():
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = [part.strip() for part in line.split('=', 1)]
                if key and key not in os.environ and value:
                    os.environ[key] = value
        except OSError:
            continue


class FeedError(RuntimeError):
    pass


def parse_date(value):
    if isinstance(value, date):
        return value
    for fmt in ('%d-%b-%Y', '%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except (ValueError, TypeError):
            continue
    raise FeedError('Unknown expiry date format')


def parse_lots(text, expiry: date):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise FeedError('Empty lot reference')
    header = [cell.strip().upper() for cell in rows[0]]
    month = expiry.strftime('%b-%y').upper()
    try:
        column, symbol = header.index(month), header.index('SYMBOL')
        row = next(r for r in rows[1:] if len(r) > max(column, symbol) and r[symbol].strip() == 'NIFTY')
        lot = int(row[column].strip())
        if lot <= 0:
            raise ValueError('Nonpositive lot')
        return lot
    except (ValueError, StopIteration, IndexError) as exc:
        raise FeedError('No official NIFTY lot size for selected expiry month; do not guess') from exc


def parse_chain(data, lot):
    try:
        records = data['records']
        at = datetime.strptime(records['timestamp'], '%d-%b-%Y %H:%M:%S').replace(tzinfo=IST).astimezone(UTC)
        spot = float(records['underlyingValue'])
        if not math.isfinite(spot) or spot <= 0:
            raise ValueError('Invalid underlying')
        quotes = []
        for row in records['data']:
            for right in ('CE', 'PE'):
                leg = row.get(right)
                if not leg or leg.get('underlying') != 'NIFTY':
                    continue
                try:
                    expiry = datetime.combine(parse_date(leg['expiryDate']), datetime.min.time(), IST).replace(hour=15, minute=30)
                    quote = Quote(str(leg['identifier']), right, float(leg['strikePrice']), expiry.astimezone(UTC),
                                  float(leg.get('buyPrice1', leg.get('bidprice', 0))),
                                  float(leg.get('sellPrice1', leg.get('askPrice', 0))),
                                  int(leg.get('buyQuantity1', leg.get('bidQty', 0))),
                                  int(leg.get('sellQuantity1', leg.get('askQty', 0))),
                                  lot, float(leg.get('impliedVolatility', 0)) / 100)
                    quotes.append(quote)
                except (KeyError, ValueError, TypeError, FeedError):
                    continue
        if not quotes:
            raise FeedError('No parseable NIFTY options in source response')
        return tuple(quotes), at, spot
    except (KeyError, ValueError, TypeError) as exc:
        raise FeedError('NSE schema/timestamp changed; source not usable') from exc


def parse_yahoo(data, now):
    try:
        result = data['chart']['result'][0]
        closes = result['indicators']['quote'][0]['close']
        bars = {}
        for stamp, price in zip(result['timestamp'], closes):
            end = datetime.fromtimestamp(stamp, UTC) + timedelta(minutes=1)
            if price is None or end > now or end.astimezone(IST).date() != now.astimezone(IST).date():
                continue
            price = float(price)
            if math.isfinite(price) and price > 0:
                bars[end] = price
        return tuple(sorted(bars.items()))
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        raise FeedError('Yahoo minute-bar schema is unavailable') from exc


class PublicFeed:
    kind = 'PUBLIC_SNAPSHOT_SIMULATION'

    def __init__(self):
        self.expiry = None
        self.lot = None
        self.disabled_hosts = set()
        self.retry_after = {}
        self.failures = {}

    def failed(self, host):
        self.failures[host] = self.failures.get(host, 0)+1
        self.retry_after[host] = time.monotonic()+min(300, 60*2**min(self.failures[host]-1, 3))

    def get(self, url, as_json=True):
        host = urlsplit(url).netloc
        if host in self.disabled_hosts:
            raise FeedError('Public source disabled for session after access denial/rate limit')
        if time.monotonic() < self.retry_after.get(host, 0):
            raise FeedError('Public source is in bounded error backoff')
        try:
            request = Request(url, headers={'User-Agent': 'NiftyPaperResearch/0.1', 'Accept': 'application/json,text/csv'})
            with urlopen(request, timeout=10) as response:
                payload = response.read(5_000_001)
            if len(payload) > 5_000_000:
                raise FeedError('Source payload exceeded bounded response size')
            text = payload.decode('utf-8-sig')
            result = json.loads(text) if as_json else text
            self.failures[host] = 0
            return result
        except HTTPError as exc:
            if exc.code in (401, 403, 429):
                self.disabled_hosts.add(host)
            self.failed(host)
            raise FeedError(f'Public HTTP {exc.code}; no bypass or immediate retry') from exc
        except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.failed(host)
            raise FeedError(f'Public response unavailable ({type(exc).__name__})') from exc

    def fetch(self):
        now = datetime.now(UTC)
        if self.expiry is None:
            info = self.get(NSE_INFO)
            eligible = sorted(parse_date(value) for value in info.get('expiryDates', [])
                              if 3 <= (parse_date(value) - now.astimezone(IST).date()).days <= 15)
            if not eligible:
                raise FeedError('No eligible 3–15-day expiry reported')
            self.expiry = eligible[0]
        if self.lot is None:
            self.lot = parse_lots(self.get(NSE_LOTS, as_json=False), self.expiry)
        query = urlencode({'type': 'Indices', 'symbol': 'NIFTY', 'expiry': self.expiry.strftime('%d-%b-%Y')})
        data = self.get(NSE_CHAIN + query)
        quotes, at, spot = parse_chain(data, self.lot)
        # Context failure must not disable known-position exits using valid NSE bids.
        bars = ()
        try:
            bars = parse_yahoo(self.get(YAHOO), datetime.now(UTC))
        except FeedError:
            pass
        return Snapshot(at, datetime.now(UTC), spot, bars, quotes,
                        NSE_CHAIN + query + ' | context=' + YAHOO + ' | lots=' + NSE_LOTS, self.kind)


class DemoFeed:
    """Intentionally mispriced synthetic options exercise the pipeline, not alpha."""
    kind = 'DEMO_SYNTHETIC'

    def __init__(self):
        self.index = 0
        self.base = datetime(2026, 9, 17, 5, 0, tzinfo=UTC)

    def fetch(self):
        at = self.base + timedelta(minutes=self.index)
        bars = tuple((at - timedelta(minutes=60-i), 23000 * (1.00015 ** (i+self.index))) for i in range(61))
        ask = 30 + self.index * .2
        quote = Quote('DEMO-NIFTY-CE', 'CE', 23200, self.base + timedelta(days=5),
                      ask - .1, ask, 650, 650, 65, .18)
        self.index += 1
        return Snapshot(at, at, bars[-1][1], bars, (quote,), 'synthetic://deterministic-demo', self.kind)


class KiteFeed:
    """Zerodha Kite WebSocket real-time feed for NIFTY options."""
    kind = 'ZERODHA_KITE_WEBSOCKET'

    def __init__(self, api_key=None, api_secret=None, request_token=None, access_token=None):
        if not KiteConnect:
            raise FeedError('kiteconnect not installed; run: pip install kiteconnect')
        load_env_file()
        self.api_key = api_key or os.environ.get('KITE_API_KEY')
        self.api_secret = api_secret or os.environ.get('KITE_API_SECRET')
        self.request_token = request_token or os.environ.get('KITE_REQUEST_TOKEN')
        self.access_token = access_token or os.environ.get('KITE_ACCESS_TOKEN')
        if not self.api_key:
            raise FeedError('KITE_API_KEY required in environment or as argument')
        if not self.api_secret and not self.access_token:
            raise FeedError('KITE_API_SECRET or KITE_ACCESS_TOKEN required; a request_token is needed to exchange for an access_token')

        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)
        else:
            if not self.request_token:
                raise FeedError('KITE_REQUEST_TOKEN required to exchange api_key + api_secret for access_token. Open the Kite login flow and paste the request_token from the redirect URL.')
            try:
                session = self.kite.generate_session(self.request_token, self.api_secret)
            except Exception as exc:  # pragma: no cover - depends on live broker auth
                raise FeedError(f'Kite session exchange failed: {type(exc).__name__}: {exc}') from exc
            self.access_token = session.get('access_token') or session.get('data', {}).get('access_token')
            if not self.access_token:
                raise FeedError('Kite token exchange returned no access_token')
            self.kite.set_access_token(self.access_token)
            # Keep the token in-process only; do not write it to env files or persistent storage.
        self.expiry = None
        self.lot = None
        self.nifty_token = 'NSE:NIFTY50'  # Underlying token for tick data
        self.option_tokens = {}
        self.quote_cache = {}
        self.last_fetch = 0
        self.failures = 0
        self.retry_after = 0

    def failed(self):
        self.failures += 1
        self.retry_after = time.monotonic() + min(300, 60 * 2 ** min(self.failures - 1, 3))

    def fetch(self):
        now = datetime.now(UTC)
        if time.monotonic() < self.retry_after:
            raise FeedError('Kite feed in bounded error backoff')
        try:
            # Fetch instruments list (cached per expiry)
            if self.expiry is None:
                try:
                    instruments = self.kite.instruments('NFO')
                except Exception as exc:
                    raise FeedError(f'Kite instruments lookup failed: {type(exc).__name__}: {exc}') from exc
                nifty_options = [i for i in instruments if i['name'] == 'NIFTY' and i['segment'] == 'NFO-OPT']
                eligible_expiries = sorted(set(
                    parse_date(i['expiry'])
                    for i in nifty_options
                ))
                eligible_expiries = [e for e in eligible_expiries if 3 <= (e - now.astimezone(IST).date()).days <= 15]
                if not eligible_expiries:
                    raise FeedError('No eligible 3–15-day expiry in Kite instruments')
                self.expiry = eligible_expiries[0]

            # Fetch lot size if not cached
            if self.lot is None:
                try:
                    instruments = self.kite.instruments('NFO')
                except Exception as exc:
                    raise FeedError(f'Kite instruments lookup failed: {type(exc).__name__}: {exc}') from exc
                nifty_opt = next((i for i in instruments if i['name'] == 'NIFTY' and i['segment'] == 'NFO-OPT' 
                                  and self.expiry == parse_date(i['expiry'])), None)
                if not nifty_opt:
                    raise FeedError('NIFTY option expiry not found in Kite')
                self.lot = int(nifty_opt.get('lot_size', 0))
                if self.lot <= 0:
                    raise FeedError('Invalid lot size from Kite')

            # Fetch current option chain quote
            query_expiry = self.expiry.strftime('%d-%b-%y')
            try:
                quote = self.kite.quote('NSE:NIFTY50')
            except Exception as exc:
                raise FeedError(f'Kite spot quote failed: {type(exc).__name__}: {exc}') from exc
            if 'NSE:NIFTY50' not in quote or 'last_price' not in quote['NSE:NIFTY50']:
                raise FeedError('Failed to fetch NIFTY spot from Kite')
            spot = float(quote['NSE:NIFTY50']['last_price'])
            at = datetime.fromtimestamp(quote['NSE:NIFTY50']['timestamp'], UTC) if quote['NSE:NIFTY50'].get('timestamp') else datetime.now(UTC)

            # Fetch options chain for eligible strikes and expirations
            try:
                instruments = self.kite.instruments('NFO')
            except Exception as exc:
                raise FeedError(f'Kite instruments lookup failed: {type(exc).__name__}: {exc}') from exc
            nifty_options = [i for i in instruments 
                           if i['name'] == 'NIFTY' and i['segment'] == 'NFO-OPT' 
                           and parse_date(i['expiry']) == self.expiry
                           and abs(math.log(float(i['strike']) / spot)) <= .01]  # ±1% OTM
            
            if not nifty_options:
                raise FeedError('No NIFTY options found for current spot and expiry')

            # Fetch quotes for all eligible options
            try:
                quotes_data = self.kite.quote(*[f"NFO:{i['tradingsymbol']}" for i in nifty_options])
            except Exception as exc:
                raise FeedError(f'Kite option quote failed: {type(exc).__name__}: {exc}') from exc
            
            quotes = []
            for instrument in nifty_options:
                symbol = f"NFO:{instrument['tradingsymbol']}"
                if symbol not in quotes_data:
                    continue
                q = quotes_data[symbol]
                try:
                    bid = float(q.get('bid', 0))
                    ask = float(q.get('ask', 0))
                    bid_units = int(q.get('bid_quantity', 0))
                    ask_units = int(q.get('ask_quantity', 0))
                    iv = float(q.get('vega', 0)) / 100 if q.get('vega') else 0.15  # Fallback to 15% IV
                    
                    if bid > 0 and ask > 0:
                        expiry_dt = datetime.combine(parse_date(instrument['expiry']), datetime.min.time(), IST).replace(hour=15, minute=30).astimezone(UTC)
                        quote_obj = Quote(
                            symbol, 
                            instrument.get('instrument_type', 'CE' if symbol.endswith('CE') else 'PE'),
                            float(instrument['strike']),
                            expiry_dt,
                            bid, ask, bid_units, ask_units,
                            self.lot, iv
                        )
                        quotes.append(quote_obj)
                except (KeyError, ValueError, TypeError):
                    continue

            if not quotes:
                raise FeedError('No valid NIFTY option quotes from Kite')

            # Fetch 1-minute bars for context (last 61 bars)
            bars = ()
            try:
                bars_data = self.kite.historical_data(
                    256265,
                    datetime.now(IST) - timedelta(hours=2),
                    datetime.now(IST),
                    'minute',
                )
                bars = tuple((
                    datetime.fromisoformat(b['date']).astimezone(UTC) if isinstance(b['date'], str)
                    else b['date'].astimezone(UTC),
                    float(b['close'])
                ) for b in bars_data[-61:] if b.get('close'))
            except Exception:
                pass  # Bar context failure should not block exit trades

            self.failures = 0
            return Snapshot(at, datetime.now(UTC), spot, bars, tuple(quotes),
                          f'kite://nifty-expiry={query_expiry}', self.kind)

        except Exception as exc:
            self.failed()
            if isinstance(exc, FeedError):
                raise
            raise FeedError(f'Kite API error: {type(exc).__name__}: {str(exc)}') from exc
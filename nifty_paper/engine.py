"""Long-only paper intents and fills. No external side effects or broker calls."""

from datetime import datetime
import math
import uuid

from .models import IST, is_public_source, market_open, money
from .strategy import select_candidate


class Engine:
    def __init__(self, config):
        self.config = config
        self.state = {'status': 'RUNNING', 'reason': 'STARTING', 'cash': money(config.capital),
                      'equity': money(config.capital), 'equity_lower_bound': money(config.capital),
                      'realized_pnl': 0, 'fees_paid': 0, 'entries': 0, 'completed_trades': 0,
                      'consecutive_losses': 0, 'position': None, 'pending': None, 'last_at': None,
                      'last_spot': None, 'analysis': {}, 'halted': False,
                      'risk_equity': money(config.capital), 'mark_status': 'NO_POSITION',
                      'classification': 'DEMO_SYNTHETIC' if config.source == 'demo' else 'PUBLIC_SNAPSHOT_SIMULATION'}

    def event(self, action, reason, **extra):
        self.state['reason'] = reason
        return {'action': action, 'reason': reason, **extra}

    def _quote_metadata(self, quote):
        return {
            'instrument': quote.instrument,
            'right': quote.right,
            'strike': quote.strike,
            'expiry': quote.expiry.isoformat(),
        }

    def _position_metadata(self, position):
        return {
            'instrument': position['instrument'],
            'right': position['right'],
            'strike': position['strike'],
            'expiry': position['expiry'],
            'trade_id': position['trade_id'],
        }

    def _risk(self, quote, price):
        cfg, state = self.config, self.state
        cost = price * quote.lot_size
        budget = cfg.risk_fraction * min(cfg.capital, state['equity'])
        return cost + cfg.fee(cost)*2 <= budget and cost + cfg.fee(cost) <= state['cash']

    def _mark(self, quote, at):
        p, s = self.state['position'], self.state
        if p and quote and quote.exit_valid(p['units']):
            p['last_bid'], p['mark_at'] = quote.bid, at.isoformat()
            s['mark_status'] = 'CURRENT_PUBLIC_SNAPSHOT' if is_public_source(self.config.source) else 'SYNTHETIC_MARK'
        elif p:
            s['mark_status'] = 'STALE_LAST_KNOWN'
        if p:
            value = p['last_bid']*(1-self.config.slippage_fraction)*p['units']
            s['equity'] = money(s['cash'] + value - self.config.fee(value))
            s['equity_lower_bound'] = money(s['cash'] - self.config.fee_per_order)
        else:
            s['equity'] = s['equity_lower_bound'] = s['cash']
            s['mark_status'] = 'NO_POSITION'
        s['risk_equity'] = s['equity_lower_bound'] if s['mark_status'] == 'STALE_LAST_KNOWN' else s['equity']

    def unavailable(self):
        self._mark(None, None)
        if self.state['risk_equity'] <= self.config.capital*(1-self.config.daily_loss_fraction):
            self.state['halted'] = True

    def step(self, snap, now, closing=False):
        s, cfg = self.state, self.config
        if snap.kind != s['classification']:
            return [self.event('NO_TRADE', 'SOURCE_CLASSIFICATION_MISMATCH')]
        created_exit = False
        if closing and s['pending'] and s['pending']['side'] == 'BUY':
            s['pending'] = None
        if closing and s['position'] and not s['pending']:
            s['pending'] = {'side': 'SELL', 'instrument': s['position']['instrument'],
                            'at': snap.at.isoformat(), 'reason': 'SESSION_END_OR_STOP'}
            created_exit = True
        age = (now-snap.at).total_seconds()
        max_age = cfg.max_age_seconds + (cfg.poll_seconds if is_public_source(cfg.source) else 0)
        if not -5 <= age <= max_age or not math.isfinite(snap.spot) or snap.spot <= 0:
            self.unavailable()
            return [self.event('NO_TRADE', 'STALE_OR_FUTURE_DATA')]
        if is_public_source(cfg.source) and (not market_open(snap.at) or snap.at.astimezone(IST).date() != now.astimezone(IST).date()):
            return [self.event('NO_TRADE', 'MARKET_CLOSED')]
        if s['last_at'] and snap.at <= datetime.fromisoformat(s['last_at']):
            return [self.event('NO_TRADE', 'DUPLICATE_OR_OUT_OF_ORDER')]
        s['last_at'], s['last_spot'] = snap.at.isoformat(), snap.spot
        quotes = {q.instrument: q for q in snap.quotes}
        p = s['position']
        self._mark(quotes.get(p['instrument']) if p else None, snap.at)
        if s['risk_equity'] <= cfg.capital*(1-cfg.daily_loss_fraction) or s['consecutive_losses'] >= 3:
            s['halted'] = True
        if created_exit:
            return [self.event('PAPER_EXIT_INTENT', 'SESSION_END_OR_STOP', **self._position_metadata(s['position']))]
        pending = s['pending']
        if pending:
            q = quotes.get(pending['instrument'])
            if pending['side'] == 'BUY':
                s['pending'] = None
                if (closing or s['halted'] or (is_public_source(cfg.source) and not market_open(snap.at, entries=True))
                    or (snap.at-datetime.fromisoformat(pending['at'])).total_seconds() > 180):
                    return [self.event('CANCEL_PAPER', 'ENTRY_EXPIRED_OR_HALTED')]
                candidate, details = select_candidate(snap, cfg)
                s['analysis'] = details
                if not q or not q.valid() or not candidate or candidate.instrument != q.instrument or q.ask > pending['max_ask']:
                    return [self.event('CANCEL_PAPER', 'ENTRY_REVALIDATION_FAILED')]
                price = money(q.ask*(1+cfg.slippage_fraction))
                if not self._risk(q, price) or q.ask_units < q.lot_size:
                    return [self.event('CANCEL_PAPER', 'ENTRY_RISK_OR_DEPTH_FAILED')]
                value, fee = money(price*q.lot_size), cfg.fee(price*q.lot_size)
                trade_id = uuid.uuid4().hex
                s['cash'] = money(s['cash']-value-fee)
                s['fees_paid'] = money(s['fees_paid']+fee)
                s['entries'] += 1
                s['position'] = {'instrument': q.instrument, 'right': q.right, 'strike': q.strike,
                                 'expiry': q.expiry.isoformat(), 'units': q.lot_size, 'entry_price': price,
                                 'entry_fee': fee, 'entered_at': snap.at.isoformat(),
                                 'last_bid': q.bid, 'mark_at': snap.at.isoformat(), 'trade_id': trade_id}
                self._mark(q, snap.at)
                return [self.event('PAPER_BUY', 'NEXT_SNAPSHOT_ASK_PLUS_SLIPPAGE',
                                   price=price, units=q.lot_size, fee=fee, trade_id=trade_id,
                                   **self._quote_metadata(q))]
            if not q or not p or not q.exit_valid(p['units']):
                return [self.event('NO_FILL', 'EXIT_QUOTE_UNAVAILABLE')]
            price = money(q.bid*(1-cfg.slippage_fraction))
            value, fee = money(price*p['units']), cfg.fee(price*p['units'])
            pnl = money((price-p['entry_price'])*p['units']-p['entry_fee']-fee)
            s['cash'] = money(s['cash']+value-fee)
            s['realized_pnl'] = money(s['realized_pnl']+pnl)
            s['fees_paid'] = money(s['fees_paid']+fee)
            s['completed_trades'] += 1
            s['consecutive_losses'] = s['consecutive_losses']+1 if pnl < 0 else 0
            s['position'], s['pending'] = None, None
            self._mark(None, snap.at)
            return [self.event('PAPER_SELL', pending['reason'], price=price, units=p['units'], fee=fee, net_pnl=pnl,
                               **self._position_metadata(p))]
        if p:
            held = (snap.at-datetime.fromisoformat(p['entered_at'])).total_seconds()/60
            change = p['last_bid']/p['entry_price']-1
            time_exit = is_public_source(cfg.source) and (snap.at.astimezone(IST).hour*60+snap.at.astimezone(IST).minute) >= 910
            if closing or s['halted'] or held >= cfg.hold_minutes or change <= -.15 or change >= .25 or time_exit:
                reason = 'RISK_OR_TIME_EXIT' if s['halted'] or held >= cfg.hold_minutes or time_exit else 'STOP_TARGET_OR_SESSION_END'
                s['pending'] = {'side': 'SELL', 'instrument': p['instrument'], 'at': snap.at.isoformat(), 'reason': reason}
                return [self.event('PAPER_EXIT_INTENT', reason, **self._position_metadata(p))]
            return [self.event('HOLD', 'POSITION_MONITORED')]
        if closing or s['halted'] or s['entries'] >= 6:
            return [self.event('NO_TRADE', 'SESSION_CLOSING_OR_RISK_HALT')]
        if is_public_source(cfg.source) and not market_open(snap.at, entries=True):
            return [self.event('NO_TRADE', 'OUTSIDE_ENTRY_WINDOW')]
        q, details = select_candidate(snap, cfg)
        s['analysis'] = details
        if not q:
            return [self.event('NO_TRADE', details.get('reason', 'NO_EDGE'))]
        price = money(q.ask*(1+cfg.slippage_fraction))
        if not self._risk(q, price):
            return [self.event('NO_TRADE', 'LOT_EXCEEDS_RISK_BUDGET')]
        s['pending'] = {'side': 'BUY', 'instrument': q.instrument, 'at': snap.at.isoformat(), 'max_ask': q.ask*1.01}
        return [self.event('PAPER_ENTRY_INTENT', 'AWAIT_NEXT_SNAPSHOT', units=q.lot_size,
                           analysis=s['analysis'], **self._quote_metadata(q))]

    def finish(self, interrupted=False):
        self.unavailable()
        self.state['pending'] = None
        self.state['status'] = 'UNRESOLVED' if self.state['position'] else 'INTERRUPTED' if interrupted else 'COMPLETED'
        self.state['reason'] = 'NO_FRESH_EXIT_FILL' if self.state['position'] else 'SESSION_FINISHED'
"""Deterministic presentation helpers for the local paper dashboard."""

from datetime import datetime
import math

from .models import Config, IST
from .diagnostics import finite


REASON_DETAILS = {
    'AWAIT_NEXT_SNAPSHOT': ('Entry intent recorded', 'The baseline selected a candidate and is waiting for a strictly later snapshot before any simulated buy.'),
    'NEXT_SNAPSHOT_ASK_PLUS_SLIPPAGE': ('Simulated buy', 'The paper engine filled the entry on a later ask with the configured adverse slippage allowance.'),
    'POSITION_MONITORED': ('Hold and monitor', 'The worker kept the existing simulated position and continued monitoring for risk or time exits.'),
    'MARKET_CLOSED': ('Market closed', 'The worker observed the source outside the allowed market session.'),
    'STALE_OR_FUTURE_DATA': ('Stale or future data', 'The source timestamp was too old or inconsistent with the current evaluation time.'),
    'CONTEXT_WARMUP_OR_STALE': ('Insufficient or stale context', 'There were not enough completed minute bars, or the recent context was too old to score a trade.'),
    'CONTEXT_GAPS': ('Insufficient or stale context', 'The completed minute-bar context contained timing gaps, so the baseline refused to score an entry.'),
    'DUPLICATE_OR_OUT_OF_ORDER': ('Duplicate snapshot', 'This snapshot was not newer than the last processed observation, so no new action was taken.'),
    'UNDERLYING_SOURCE_DISAGREEMENT': ('Underlying-source disagreement', 'The option-chain spot and Yahoo minute-bar context disagreed beyond the configured tolerance.'),
    'CASH_BETTER_AFTER_COSTS': ('Cash better after costs', 'After spreads, slippage, fees, and uncertainty allowance, the baseline did not justify an entry.'),
    'POSITIVE_BASELINE_SCENARIO_SCORE': ('Candidate selected', 'The baseline produced a positive post-cost scenario score for the selected contract. This is still an unvalidated research output.'),
    'LOT_EXCEEDS_RISK_BUDGET': ('Lot exceeds risk budget', 'The minimum official lot would exceed the configured risk budget or available cash.'),
    'ENTRY_REVALIDATION_FAILED': ('Entry revalidation failed', 'The next snapshot no longer supported the same candidate or price envelope.'),
    'ENTRY_RISK_OR_DEPTH_FAILED': ('Entry revalidation failed', 'The later snapshot did not satisfy the required risk budget or displayed ask depth for a whole-lot paper fill.'),
    'ENTRY_EXPIRED_OR_HALTED': ('Risk halt', 'The pending entry expired, the session began closing, or the risk state halted new paper entries.'),
    'EXIT_QUOTE_UNAVAILABLE': ('Exit quote unavailable', 'A later usable bid was not available with sufficient displayed size, so the simulator refused to invent an exit.'),
    'SESSION_CLOSING_OR_RISK_HALT': ('Risk halt', 'The session was closing or new entries were halted by existing limits.'),
    'SESSION_END_OR_STOP': ('Session closing', 'A graceful stop or planned end requested an exit on a later usable quote.'),
    'RISK_OR_TIME_EXIT': ('Session closing', 'Risk or time rules requested an exit on a later usable quote.'),
    'STOP_TARGET_OR_SESSION_END': ('Session closing', 'The position reached a stop, target or session-close trigger and requested an exit on a later usable quote.'),
    'SESSION_FINISHED': ('Session complete', 'The bounded paper session finished and no simulated exposure remained open.'),
    'NO_FRESH_EXIT_FILL': ('Unresolved simulated exposure', 'The session ended before a later usable exit quote arrived, so the simulated position remains unresolved.'),
    'DATA_UNAVAILABLE': ('Source unavailable', 'The worker could not fetch or parse a usable source response for this cycle.'),
    'OUTSIDE_ENTRY_WINDOW': ('Market closed', 'The source was valid, but the time was outside the configured entry window for new paper positions.'),
    'SOURCE_CLASSIFICATION_MISMATCH': ('Stale/future data', 'The session received a snapshot classification that did not match the configured source type.'),
    'DURATION_EXPIRED_DURING_FETCH': ('Session closing', 'The requested duration elapsed while a fetch was still in flight, so no new fill was allowed after the deadline.'),
}


def explain_reason(code):
    title, detail = REASON_DETAILS.get(code, ('Recorded reason', 'No dashboard-specific plain-language description is registered for this reason code.'))
    return {'code': code, 'title': title, 'detail': detail}


def parse_time(value):
    return datetime.fromisoformat(value) if value else None


def format_ist(value):
    stamp = parse_time(value) if isinstance(value, str) else value
    if stamp is None:
        return None
    return stamp.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S IST')


def age_seconds(value, now):
    stamp = parse_time(value) if isinstance(value, str) else value
    if stamp is None:
        return None
    return max(0.0, (now - stamp).total_seconds())


def estimated_unrealized_pnl(session):
    state = session['state']
    position = state.get('position')
    if not position or position.get('last_bid') is None:
        return None
    config = Config(**session['config'])
    exit_value = position['last_bid'] * (1 - config.slippage_fraction) * position['units']
    exit_fee = config.fee(exit_value)
    entry_value = position['entry_price'] * position['units']
    return round(exit_value - exit_fee - entry_value - position['entry_fee'], 2)


def build_overview(session, now):
    state = session['state']
    position = state.get('position')
    mark_status = state.get('mark_status', 'UNKNOWN')
    usable_equity = state['equity'] if mark_status in ('CURRENT_PUBLIC_SNAPSHOT', 'SYNTHETIC_MARK', 'NO_POSITION') else None
    end_at = parse_time(state.get('planned_end_utc'))
    remaining_seconds = max(0.0, (end_at - now).total_seconds()) if end_at else None
    notice = None
    if session.get('equity_history_status') == 'UNAVAILABLE' and state.get('status') in ('COMPLETED', 'UNRESOLVED'):
        notice = 'Historical equity samples unavailable.'
    return {
        'session_id': session.get('id'),
        'source': session['config']['source'],
        'status': state.get('status'),
        'reason': explain_reason(state.get('reason')),
        'worker_heartbeat_age_seconds': age_seconds(session.get('heartbeat'), now),
        'source_age_seconds': age_seconds(state.get('source_as_of'), now),
        'source_received_age_seconds': age_seconds(state.get('source_received_at'), now),
        'started_at_ist': format_ist(session.get('started')),
        'planned_end_ist': format_ist(state.get('planned_end_utc')),
        'remaining_seconds': remaining_seconds,
        'starting_capital': session['config']['capital'],
        'cash_balance': state.get('cash'),
        'realized_pnl': state.get('realized_pnl'),
        'estimated_unrealized_pnl': estimated_unrealized_pnl(session),
        'last_known_equity': state.get('equity'),
        'usable_equity': usable_equity,
        'conservative_equity': state.get('equity_lower_bound'),
        'fees_paid': state.get('fees_paid'),
        'entries': state.get('entries'),
        'completed_trades': state.get('completed_trades'),
        'halted': state.get('halted'),
        'consecutive_losses': state.get('consecutive_losses'),
        'valuation_status': mark_status,
        'position': position,
        'pending': state.get('pending'),
        'equity_history_notice': notice,
    }


def completed_trades(events):
    buys = {}
    trades = []
    incomplete = False
    for event in events:
        if event.get('action') == 'PAPER_BUY':
            trade_id = event.get('trade_id')
            if not trade_id:
                incomplete = True
                continue
            buys[trade_id] = event
        if event.get('action') == 'PAPER_SELL':
            trade_id = event.get('trade_id')
            if not trade_id or trade_id not in buys:
                incomplete = True
                continue
            buy = buys[trade_id]
            trades.append({
                'trade_id': trade_id,
                'instrument': event.get('instrument', buy.get('instrument')),
                'right': event.get('right', buy.get('right')),
                'strike': event.get('strike', buy.get('strike')),
                'expiry': event.get('expiry', buy.get('expiry')),
                'buy_time': buy.get('recorded'),
                'sell_time': event.get('recorded'),
                'buy_price': buy.get('price'),
                'sell_price': event.get('price'),
                'units': event.get('units', buy.get('units')),
                'buy_fee': buy.get('fee'),
                'sell_fee': event.get('fee'),
                'net_pnl': event.get('net_pnl'),
            })
    notice = None
    if not trades and incomplete:
        notice = 'Auditable buy/sell linkage unavailable for this older session.'
    return trades, notice


def timeline_rows(events):
    rows = []
    for event in events:
        reason = explain_reason(event.get('reason'))
        rows.append({
            'timestamp': event.get('recorded'),
            'timestamp_ist': format_ist(event.get('recorded')),
            'action': event.get('action'),
            'reason_code': reason['code'],
            'reason_title': reason['title'],
            'reason_detail': reason['detail'],
            'instrument': event.get('instrument'),
            'trade_id': event.get('trade_id'),
            'units': event.get('units'),
            'price': event.get('price'),
            'fee': event.get('fee'),
            'net_pnl': event.get('net_pnl'),
            'analysis': event.get('analysis'),
            'raw': event,
        })
    return rows


def latest_snapshot(session):
    snapshots = session.get('snapshots') or []
    return snapshots[-1] if snapshots else None


def option_rows(snapshot, right=None, expiry=None, strike_distance=None):
    if not snapshot:
        return []
    spot = snapshot.get('spot')
    rows = []
    for quote in snapshot.get('quotes', []):
        if right and quote.get('right') != right:
            continue
        if expiry and quote.get('expiry') != expiry:
            continue
        strike, bid, ask = quote.get('strike'), quote.get('bid'), quote.get('ask')
        distance = abs(strike - spot) if finite(strike) and finite(spot) else math.nan
        if strike_distance is not None and math.isfinite(distance) and distance > strike_distance:
            continue
        rows.append({
            'instrument': quote.get('instrument'),
            'right': quote.get('right'),
            'strike': quote.get('strike'),
            'expiry': quote.get('expiry'),
            'lot_size': quote.get('lot_size'),
            'bid': quote.get('bid'),
            'ask': quote.get('ask'),
            'spread': round(ask - bid, 2) if finite(ask) and finite(bid) else None,
            'bid_units': quote.get('bid_units'),
            'ask_units': quote.get('ask_units'),
            'iv': quote.get('iv'),
            'distance_to_spot': round(distance, 2) if math.isfinite(distance) else None,
        })
    return rows


def position_summary(session, now):
    state = session['state']
    position = state.get('position')
    if not position:
        return None
    entered_at = parse_time(position.get('entered_at'))
    hold_minutes = (now - entered_at).total_seconds() / 60 if entered_at else None
    return {
        'instrument': position.get('instrument'),
        'right': position.get('right'),
        'strike': position.get('strike'),
        'expiry_ist': format_ist(position.get('expiry')),
        'units': position.get('units'),
        'entry_price': position.get('entry_price'),
        'entry_fee': position.get('entry_fee'),
        'entry_time_ist': format_ist(position.get('entered_at')),
        'last_bid': position.get('last_bid'),
        'mark_time_ist': format_ist(position.get('mark_at')),
        'holding_minutes': round(hold_minutes, 1) if hold_minutes is not None else None,
        'pending_exit': state.get('pending'),
    }


def risk_summary(session):
    state = session['state']
    config = Config(**session['config'])
    position = state.get('position')
    exposure = None
    if position:
        exposure = round(position['entry_price'] * position['units'], 2)
    return {
        'full_premium_exposure': exposure,
        'per_idea_risk_budget': round(config.capital * config.risk_fraction, 2),
        'session_loss_threshold': round(config.capital * config.daily_loss_fraction, 2),
        'consecutive_losses': state.get('consecutive_losses'),
        'entry_count': state.get('entries'),
        'entry_limit': 6,
        'halted': state.get('halted'),
        'halt_reason': explain_reason(state.get('reason')),
    }


def _candidate_capital_metrics(candidate, config):
    ask = candidate.get('ask')
    if not isinstance(ask, (int, float)):
        return candidate
    actual_lot_size = candidate.get('lot_size') or 65
    entry_price = ask * (1 + config.slippage_fraction)
    entry_cost = round(entry_price * actual_lot_size, 2)
    entry_fee = config.fee(entry_cost)
    round_trip_fees = round(entry_fee * 2, 2)
    min_cash = round(entry_cost + entry_fee, 2)
    min_capital = round((entry_cost + round_trip_fees) / config.risk_fraction, 2)
    return {
        **candidate,
        'entry_cost_one_lot': entry_cost,
        'round_trip_fees_est': round_trip_fees,
        'min_cash_for_entry': min_cash,
        'min_capital_for_risk_gate': min_capital,
    }


def selection_metrics(session):
    analysis = session['state'].get('analysis') or {}
    config = Config(**session['config'])
    top_candidates = [_candidate_capital_metrics(candidate, config) for candidate in (analysis.get('top_candidates') or [])]
    return {
        'model': analysis.get('model'),
        'horizon_minutes': analysis.get('horizon_minutes'),
        'expected_log_return': analysis.get('expected_log_return'),
        'return_std': analysis.get('return_std'),
        'p_up_model_only': analysis.get('p_up_model_only'),
        'iv_stress_mean_pnl': analysis.get('iv_stress_mean_pnl'),
        'candidate_score': analysis.get('net_ev_rupees'),
        'candidate_counts': analysis.get('candidate_counts') or {},
        'top_candidates': top_candidates,
        'reason': explain_reason(analysis.get('reason', 'CASH_BETTER_AFTER_COSTS')),
    }
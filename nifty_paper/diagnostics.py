"""Auditable entry gates and reports. No workers, network, orders or tuning."""

from collections import Counter, deque
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import math
from statistics import mean, median, pstdev

from .models import IST, is_public_source, market_open
from .risk import entry_requirements
from .strategy import scenario_values, select_candidate


STAGES = {
    'after_snapshot': ('classification', 'snapshot_time', 'spot_valid', 'freshness', 'ordering'),
    'after_session': ('market_session', 'entry_window', 'session_closing', 'max_entries',
                      'consecutive_losses', 'daily_loss', 'halt', 'position'),
    'after_bars': ('bars_count', 'bars_age', 'bars_gap'),
    'after_spot': ('spot_agreement',),
    'after_quote': ('bid', 'ask', 'strike', 'option_type', 'expiry_timestamp', 'bid_quantity',
                    'ask_quantity', 'lot_size', 'quote_order', 'iv'),
    'after_expiry': ('expiry_window',),
    'after_strike': ('strike_window',),
    'after_spread': ('spread',),
    'after_depth': ('depth',),
    'after_risk': ('risk', 'cash'),
    'after_score': ('score',),
}


def finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def clean(value):
    """Preserve missing data as null, never manufacture prices or IV."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def check(passed, code, actual=None, required=None, depends_on=None):
    return {'status': 'NOT_EVALUATED' if passed is None else 'PASS' if passed else 'FAIL',
            'code': code, 'actual': clean(actual), 'required': required,
            'depends_on': depends_on}


def failed_gates(trace):
    failures = list(dict.fromkeys(v['code'] for v in trace['validations'].values() if v['status'] == 'FAIL'))
    trace['failed_gates'] = failures
    trace['first_failed_gate'] = failures[0] if failures else None
    trace['rejection_reason'] = failures[0] if failures else None


def evaluate(snap, config, state, now, closing=False):
    """Evaluate independent checks even after a failure; causal dependencies stay unknown.

    Public feeds expose chain-wide timestamps only. We do NOT claim per-leg
    freshness, quote ordering, holiday coverage, or historical warm-up support.
    """
    timestamp_ok = aware(snap.at) and aware(now)
    spot_ok = finite(snap.spot) and snap.spot > 0
    age = (now - snap.at).total_seconds() if timestamp_ok else None
    last_at = datetime.fromisoformat(state['last_at']) if state.get('last_at') else None
    public = is_public_source(config.source)
    snapshot_checks = {
        'classification': check(snap.kind == state['classification'], 'SOURCE_CLASSIFICATION_MISMATCH', snap.kind, state['classification']),
        'snapshot_time': check(timestamp_ok, 'MISSING_TIMESTAMP', snap.at, 'timezone-aware snapshot and decision time'),
        'spot_valid': check(spot_ok, 'INVALID_SPOT', snap.spot, '> 0, finite'),
        'freshness': check(-5 <= age <= config.max_age_seconds if age is not None else None,
                           'FUTURE_QUOTE' if age is not None and age < -5 else 'STALE_QUOTE', age,
                           f'-5 <= snapshot age <= {config.max_age_seconds} seconds', 'snapshot_time'),
        'ordering': check(snap.at > last_at if timestamp_ok and last_at else True if timestamp_ok else None,
                          'DUPLICATE_OR_OUT_OF_ORDER', snap.at, 'strictly later than last accepted snapshot', 'snapshot_time'),
    }
    global_checks = dict(snapshot_checks)
    global_checks.update({
        'market_session': check((market_open(snap.at) and snap.at.astimezone(IST).date() == now.astimezone(IST).date()) if public and timestamp_ok else True if not public else None,
                                'MARKET_CLOSED', snap.at, 'same IST weekday, 09:15 <= time < 15:30; holiday calendar NOT implemented'),
        'entry_window': check(market_open(snap.at, entries=True) if public and timestamp_ok else True if not public else None,
                              'ENTRY_WINDOW_CLOSED', snap.at, '09:30 <= IST time < 15:30 on weekdays'),
        'session_closing': check(not closing, 'SESSION_CLOSING', closing, False),
        'max_entries': check(state['entries'] < 6, 'MAX_ENTRIES_REACHED', state['entries'], '< 6'),
        'consecutive_losses': check(state['consecutive_losses'] < 3, 'CONSECUTIVE_LOSS_LIMIT', state['consecutive_losses'], '< 3 closed net losses'),
        'daily_loss': check(state['risk_equity'] > config.capital*(1-config.daily_loss_fraction),
                            'DAILY_LOSS_LIMIT', state['risk_equity']-config.capital, f'> {-config.capital*config.daily_loss_fraction} INR (net conservative equity change)'),
        'halt': check(not state['halted'], 'HALT_LATCHED', state['halted'], False),
        'position': check(not state['position'], 'POSITION_ALREADY_OPEN', bool(state['position']), False),
    })
    valid_bars = [(t, p) for t, p in snap.bars if aware(t) and finite(p) and p > 0 and timestamp_ok
                  and t <= snap.at and t.astimezone(IST).date() == snap.at.astimezone(IST).date()]
    bar_age = (snap.at-valid_bars[-1][0]).total_seconds() if valid_bars else None
    window = valid_bars[-61:]
    intervals = [(b[0]-a[0]).total_seconds() for a, b in zip(window, window[1:])]
    gaps = [gap for gap in intervals if not 30 <= gap <= 90]
    mismatch = abs(valid_bars[-1][1]/snap.spot - 1) if valid_bars and spot_ok else None
    global_checks.update({
        'bars_count': check(len(valid_bars) >= 31, 'INSUFFICIENT_BARS', len(valid_bars), '>= 31 same-session completed bars'),
        'bars_age': check(bar_age <= 180 if bar_age is not None else None, 'STALE_BARS', bar_age, '<= 180 seconds', 'bars_count'),
        'bars_gap': check(not gaps if len(valid_bars) >= 2 else None, 'BAR_GAP', gaps, '30 <= same-session interval <= 90 seconds', 'bars_count'),
        'spot_agreement': check(mismatch <= .002 if mismatch is not None else None, 'SPOT_MISMATCH', mismatch, '<= 0.002', 'bars and spot'),
    })
    forecast = {}
    if timestamp_ok and spot_ok and all(global_checks[k]['status'] == 'PASS' for k in ('bars_count', 'bars_age', 'bars_gap', 'spot_agreement')):
        _, forecast = select_candidate(replace(snap, bars=tuple(valid_bars), quotes=()), config)
    candidates = []
    for index, q in enumerate(snap.quotes):
        gates = dict(global_checks)
        bid_ok, ask_ok = finite(q.bid) and q.bid > 0, finite(q.ask) and q.ask > 0
        strike_ok = finite(q.strike) and q.strike > 0
        strike_ratio = q.strike/snap.spot if strike_ok and spot_ok else None
        strike_distance = abs(math.log(strike_ratio)) if strike_ratio is not None and finite(strike_ratio) and strike_ratio > 0 else None
        lot_ok = isinstance(q.lot_size, int) and not isinstance(q.lot_size, bool) and q.lot_size > 0
        iv_ok = finite(q.iv) and 0 < q.iv <= 3
        expiry_ok = aware(q.expiry)
        dte = (q.expiry-snap.at).total_seconds()/86400 if expiry_ok and timestamp_ok else None
        mid = (q.bid+q.ask)/2 if bid_ok and ask_ok else None
        spread = q.ask-q.bid if mid else None
        fraction = spread/mid if mid else None
        gates.update({
            'bid': check(bid_ok, 'INVALID_BID', q.bid, '> 0 finite'),
            'ask': check(ask_ok, 'INVALID_ASK', q.ask, '> 0 finite'),
            'strike': check(strike_ok, 'INVALID_STRIKE', q.strike, '> 0 finite'),
            'option_type': check(q.right in ('CE', 'PE'), 'INVALID_OPTION_TYPE', q.right, 'CE or PE'),
            'expiry_timestamp': check(expiry_ok, 'INVALID_EXPIRY', q.expiry, 'timezone-aware expiry'),
            'bid_quantity': check(finite(q.bid_units) and q.bid_units > 0, 'INVALID_BID_QUANTITY', q.bid_units, '> 0'),
            'ask_quantity': check(finite(q.ask_units) and q.ask_units > 0, 'INVALID_ASK_QUANTITY', q.ask_units, '> 0'),
            'lot_size': check(lot_ok, 'INVALID_LOT_SIZE', q.lot_size, 'positive integer official lot'),
            'quote_order': check(q.bid <= q.ask if bid_ok and ask_ok else None, 'INVALID_QUOTE', [q.bid, q.ask], 'bid <= ask (existing policy)', 'bid and ask'),
            'iv': check(iv_ok, 'INVALID_IV', q.iv, '0 < IV <= 3, decimal volatility'),
            'expiry_window': check(3 <= dte <= 15 if dte is not None else None, 'INVALID_EXPIRY', dte, '3 <= DTE <= 15', 'expiry_timestamp'),
            'strike_window': check(strike_distance <= .01 if strike_distance is not None else False if strike_ok and spot_ok else None,
                                   'STRIKE_OUTSIDE_WINDOW', strike_ratio, 'abs(log(strike/spot)) <= 0.01'),
            'spread': check(0 <= fraction <= config.max_spread_fraction if fraction is not None else None,
                            'SPREAD_TOO_WIDE', fraction, f'<= {config.max_spread_fraction} of mid', 'bid and ask'),
            'depth': check(min(q.bid_units, q.ask_units) >= q.lot_size if lot_ok and finite(q.bid_units) and finite(q.ask_units) else None,
                           'INSUFFICIENT_DEPTH', [q.bid_units, q.ask_units], f'each side >= {q.lot_size} units'),
        })
        cost_error = False
        try:
            costs = entry_requirements(config, state, q) if ask_ok and lot_ok else {}
        except (ArithmeticError, ValueError):
            costs = {'risk_pass': False, 'cash_pass': False}
            cost_error = True
        gates['cost_calculation'] = check(not cost_error if ask_ok and lot_ok else None, 'INVALID_COST', required='finite representable full-lot amounts')
        gates['risk'] = check(costs.get('risk_pass'), 'RISK_TOO_HIGH', costs.get('risk_required'), costs.get('configured_risk_budget'), 'ask and lot')
        gates['cash'] = check(costs.get('cash_pass'), 'INSUFFICIENT_CASH', costs.get('total_entry_cost'), state['cash'], 'ask and lot')
        score, means, uncertainty = None, [], None
        if forecast.get('uncertainty_move') is not None and all(gates[k]['status'] == 'PASS' for k in ('bid','ask','strike','option_type','expiry_timestamp','quote_order','lot_size','iv')):
            try:
                score, means, uncertainty = scenario_values(snap, q, config, forecast)
                if not all(finite(v) for v in [score, uncertainty, *means]):
                    score, means, uncertainty = None, [], None
            except (ValueError, ArithmeticError):
                pass
        gates['score'] = check(score > 0 if score is not None else None, 'SCORE_TOO_LOW', score, '> 0 INR', 'valid pricing inputs and causal forecast')
        gates['later_snapshot'] = check(None, 'NOT_LATER_SNAPSHOT', required='strictly later than entry intent', depends_on='pending BUY')
        gates['intent_age'] = check(None, 'ENTRY_INTENT_EXPIRED', required='<= 180 seconds', depends_on='pending BUY')
        gates['ask_envelope'] = check(None, 'ASK_ENVELOPE_EXCEEDED', required='<= original ask * 1.01', depends_on='pending BUY')
        gates['same_candidate'] = check(None, 'CANDIDATE_CHANGED', required='same highest-scoring feasible instrument', depends_on='pending BUY and valid candidate selection')
        trace = {
            'candidate_index': index, 'timestamp': now, 'source_as_of': snap.at, 'source_received_at': snap.received_at,
            'strategy': config.source, 'underlying_spot': snap.spot, 'instrument': q.instrument,
            'option_type': q.right, 'strike': q.strike, 'expiry': q.expiry, 'dte': dte,
            'bid': q.bid, 'ask': q.ask, 'bid_quantity': q.bid_units, 'ask_quantity': q.ask_units,
            'snapshot_age_seconds': age, 'quote_age_seconds': None, 'timestamp_scope': 'CHAIN_SNAPSHOT_ONLY' if public else 'SYNTHETIC_SNAPSHOT',
            'iv': q.iv, 'iv_valid': iv_ok, 'mid': mid, 'spread': spread,
            'spread_fraction': fraction, 'spread_percentage': fraction*100 if fraction is not None else None,
            'lot_size': q.lot_size, 'premium': None, 'fees': None, 'total_entry_cost': None,
            'configured_risk_budget': config.risk_fraction*min(config.capital, state['equity']), 'cash_available': state['cash'],
            **costs, 'score': score, 'scenario_means': means, 'uncertainty': uncertainty,
            'applied_uncertainty': uncertainty*(.35 if config.source == 'public_loose' else 1) if uncertainty is not None else None,
            'expected_log_return': forecast.get('expected_log_return'), 'scenario_dispersion': pstdev(means) if means else None,
            'scenario_positive_count': sum(v > 0 for v in means) if means else None,
            'current_session_bars': len(valid_bars), 'historical_warmup_bars_used': 0,
            'validations': gates,
        }
        passed = True
        reached = {}
        for stage, keys in STAGES.items():
            passed = passed and all(gates[key]['status'] == 'PASS' for key in keys)
            reached[stage] = passed
        trace['stages'] = reached
        trace['hard_pass'] = reached['after_risk']
        trace['eligible'] = reached['after_score']
        trace['final_decision'] = 'ELIGIBLE' if trace['eligible'] else 'REJECTED'
        failed_gates(trace)
        candidates.append(trace)
    return clean({'schema_version': 1, 'mode': 'DIAGNOSTIC' if config.diagnostic else 'PAPER',
                  'timestamp': now, 'source_as_of': snap.at, 'strategy': config.source,
                  'classification': snap.kind, 'snapshot_checks': snapshot_checks, 'forecast': forecast,
                  'candidates': candidates, 'snapshot_reason': None if candidates else 'NO_VALID_CONTRACT',
                  'limitations': ['Public quote age/order is chain-wide, not verified per leg.',
                                  'Counts start at normalized quotes; source legs discarded by the old parser are not reconstructable.',
                                  'Historical warm-up and exchange-holiday calendar are not implemented.',
                                  'Scores are unvalidated research values, not evidence of alpha.']})


def finalize(report, events, prior_pending=None):
    report['actions'] = [{k: e[k] for k in ('action', 'reason', 'instrument') if k in e} for e in events]
    outcome = events[0] if events else {}
    report['outcome_reason'] = outcome.get('reason')
    report['selected_decision'] = outcome.get('reason') if outcome.get('action') == 'DIAGNOSTIC' else outcome.get('action')
    eligible = [t for t in report['candidates'] if t['eligible']]
    selected = max(eligible, key=lambda t: t['score'])['instrument'] if eligible else None
    execution_codes = {'ENTRY_EXPIRED_OR_HALTED', 'ENTRY_REVALIDATION_FAILED', 'ENTRY_RISK_OR_DEPTH_FAILED'}
    for trace in report['candidates']:
        if outcome.get('instrument') == trace['instrument']:
            trace['final_decision'] = report['selected_decision']
        elif trace['eligible']:
            trace['final_decision'] = 'PASS_NOT_SELECTED'
        if prior_pending and prior_pending.get('side') == 'BUY' and prior_pending['instrument'] == trace['instrument']:
            at = datetime.fromisoformat(report['source_as_of'])
            pending_at = datetime.fromisoformat(prior_pending['at'])
            gates = trace['validations']
            gates['later_snapshot'] = check(at > pending_at, 'NOT_LATER_SNAPSHOT', at, '> intent timestamp')
            gates['intent_age'] = check((at-pending_at).total_seconds() <= 180, 'ENTRY_INTENT_EXPIRED', (at-pending_at).total_seconds(), '<= 180 seconds')
            gates['ask_envelope'] = check(trace['ask'] <= prior_pending['max_ask'] if finite(trace['ask']) else None,
                                          'ASK_ENVELOPE_EXCEEDED', trace['ask'], prior_pending['max_ask'])
            gates['same_candidate'] = check(selected == trace['instrument'] if selected else None, 'CANDIDATE_CHANGED', selected,
                                            prior_pending['instrument'], 'valid candidate selection')
            if outcome.get('reason') in execution_codes:
                trace['final_decision'] = 'CANCEL_PAPER'
                gates['entry_revalidation'] = check(False, outcome['reason'], outcome['reason'], 'same highest-scoring feasible candidate, unchanged intent constraints')
            failed_gates(trace)
    report['summary'] = summarize([report])
    report['decision_id'] = hashlib.sha256(json.dumps(report, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return report


def statistics(values):
    values = sorted(v for v in values if finite(v))
    if not values:
        return {'count': 0, 'minimum': None, 'maximum': None, 'mean': None, 'median': None,
                'percentiles': {}, 'positive': 0, 'zero': 0, 'negative': 0}
    def percentile(p):
        index = (len(values)-1)*p/100
        low = int(index)
        return values[low] + (values[min(low+1, len(values)-1)]-values[low])*(index-low)
    return {'count': len(values), 'minimum': values[0], 'maximum': values[-1], 'mean': mean(values),
            'median': median(values), 'percentiles': {str(p): percentile(p) for p in (5, 25, 50, 75, 95)},
            'positive': sum(v > 0 for v in values), 'zero': sum(v == 0 for v in values), 'negative': sum(v < 0 for v in values)}


def summarize(reports):
    funnel = Counter({'discovered': 0, **{stage: 0 for stage in STAGES}})
    first, all_failed, decisions = Counter(), Counter(), Counter()
    scores, uncertainties, near_misses = [], [], deque(maxlen=10)
    evaluations = 0
    for report in reports:
        evaluations += 1
        decisions.update(e['action']+':'+e['reason'] for e in report.get('actions', []))
        for trace in report['candidates']:
            funnel['discovered'] += 1
            for stage, passed in trace['stages'].items():
                funnel[stage] += int(passed)
            if trace['first_failed_gate']:
                first[trace['first_failed_gate']] += 1
            all_failed.update(trace['failed_gates'])
            if trace['stages']['after_depth']:
                scores.append(trace['score'])
                uncertainties.append(trace['uncertainty'])
            # Independent failed gates only; unknown prerequisites are visible, not assumed passes.
            if 1 <= len(trace['failed_gates']) <= 2:
                near_misses.append({k: trace[k] for k in ('timestamp','instrument','score','failed_gates','first_failed_gate','validations')})
    return {'evaluations': evaluations, 'count_unit': 'candidate observations per evaluated snapshot, not unique contracts',
            'funnel': dict(funnel), 'first_failed_gates': dict(first), 'all_failed_gates': dict(all_failed),
            'actions': dict(decisions), 'trades_taken': sum(n for k,n in decisions.items() if k.startswith('PAPER_BUY:')),
            'scoring_population': 'candidates passing data, session and liquidity gates, before risk filtering',
            'score_statistics': statistics(scores), 'uncertainty_statistics': statistics(uncertainties),
            'near_misses': list(near_misses), 'near_miss_limit': 10,
            'final_stage_explanation': 'Eligible candidates still require later-snapshot revalidation; eligibility is not a fill.' if funnel['after_score'] else 'No candidate passed every entry gate; see first_failed_gates and all_failed_gates.'}


def journal_diagnostics(connection, session_id):
    event_rows = connection.execute('SELECT payload FROM events WHERE session_id=? ORDER BY seq', (session_id,))
    recorded_reasons = dict(Counter(json.loads(row[0]).get('reason', 'UNKNOWN') for row in event_rows))
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_reports'").fetchone()
    count = connection.execute('SELECT COUNT(*) FROM decision_reports WHERE session_id=?', (session_id,)).fetchone()[0] if exists else 0
    if not count:
        row = connection.execute('SELECT state FROM sessions WHERE id=?', (session_id,)).fetchone()
        new_schema = bool(row and json.loads(row[0]).get('diagnostic_schema_version'))
        if new_schema:
            return {'status': 'NO_EVALUATIONS', 'summary': summarize([]), 'latest': None,
                    'recorded_reasons': recorded_reasons,
                    'notice': 'No candidate snapshots were evaluated. Inspect recorded reasons for source outages, closed market or session deadlines.'}
        return {'status': 'UNAVAILABLE', 'summary': None, 'latest': None,
                'recorded_reasons': recorded_reasons,
                'notice': 'This session predates persisted candidate diagnostics. Old traces cannot be fabricated.'}
    reports = (json.loads(row[0]) for row in connection.execute('SELECT payload FROM decision_reports WHERE session_id=? ORDER BY seq', (session_id,)))
    summary = summarize(reports)
    latest = json.loads(connection.execute('SELECT payload FROM decision_reports WHERE session_id=? ORDER BY seq DESC LIMIT 1', (session_id,)).fetchone()[0])
    snapshots = connection.execute('SELECT COUNT(*) FROM snapshots WHERE session_id=?', (session_id,)).fetchone()[0]
    return {'status': 'AVAILABLE', 'summary': summary, 'latest': latest,
            'recorded_reasons': recorded_reasons,
            'stored_snapshots': snapshots, 'evaluations_with_traces': count,
            'notice': 'Session aggregates use all recorded traces; latest contains one complete evaluation.'}
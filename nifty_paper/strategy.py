"""Unvalidated distribution baseline; conservative scenario ranking versus cash."""

import math
from statistics import NormalDist, mean, stdev

from .models import IST


def candidate_score(source, scenario_means, uncertainty_penalty):
    if source == 'public_loose':
        return mean(scenario_means) - 0.35 * uncertainty_penalty
    return min(scenario_means) - uncertainty_penalty


def option_value(spot, strike, years, vol, right):
    # Zero carry/rate approximation is deliberately documented, not a fitted surface.
    if years <= 0 or vol <= 0:
        return max(0, spot - strike) if right == 'CE' else max(0, strike - spot)
    d1 = (math.log(spot / strike) + .5 * vol * vol * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    normal = NormalDist()
    if right == 'CE':
        return spot * normal.cdf(d1) - strike * normal.cdf(d2)
    return strike * normal.cdf(-d2) - spot * normal.cdf(-d1)


def select_candidate(snap, config):
    bars = [(t, p) for t, p in snap.bars if t <= snap.at and t.astimezone(IST).date() == snap.at.astimezone(IST).date()]
    if len(bars) < 31 or (snap.at - bars[-1][0]).total_seconds() > 180:
        return None, {'reason': 'CONTEXT_WARMUP_OR_STALE', 'bars': len(bars)}
    bars = bars[-61:]
    if any(not 30 <= (b[0] - a[0]).total_seconds() <= 90 for a, b in zip(bars, bars[1:])):
        return None, {'reason': 'CONTEXT_GAPS'}
    if abs(bars[-1][1] / snap.spot - 1) > .002:
        return None, {'reason': 'UNDERLYING_SOURCE_DISAGREEMENT'}
    returns = [math.log(b[1] / a[1]) for a, b in zip(bars, bars[1:])]
    drift = max(-.0002, min(.0002, mean(returns) * .25))
    sigma = max(stdev(returns), .0001)
    horizon = config.hold_minutes
    mu, scale = drift * horizon, sigma * math.sqrt(horizon)
    uncertainty_move = 1.96 * sigma / math.sqrt(len(returns)) * horizon
    normal = NormalDist()
    zs = [normal.inv_cdf((i + .5) / 41) for i in range(41)]
    best, best_score = None, 0.0
    candidate_counts = {'total': len(snap.quotes), 'valid': 0, 'days_window': 0,
                        'strike_window': 0, 'spread_ok': 0, 'depth_ok': 0, 'positive_score': 0}
    top_candidates = []
    details = {'reason': 'CASH_BETTER_AFTER_COSTS', 'model': 'shrunk-normal-baseline-v1-UNVALIDATED',
               'horizon_minutes': horizon, 'expected_log_return': mu, 'return_std': scale,
               'p_up_model_only': normal.cdf(mu / scale), 'calibrated': False,
               'candidate_counts': candidate_counts, 'top_candidates': top_candidates}
    for q in snap.quotes:
        days = (q.expiry - snap.at).total_seconds() / 86400
        valid = q.valid()
        if valid:
            candidate_counts['valid'] += 1
        if not valid:
            continue
        if 3 <= days <= 15:
            candidate_counts['days_window'] += 1
        else:
            continue
        if abs(math.log(q.strike / snap.spot)) <= .01:
            candidate_counts['strike_window'] += 1
        else:
            continue
        spread_fraction = (q.ask-q.bid) / ((q.ask+q.bid)/2)
        if spread_fraction <= config.max_spread_fraction:
            candidate_counts['spread_ok'] += 1
        else:
            continue
        if min(q.bid_units, q.ask_units) >= q.lot_size:
            candidate_counts['depth_ok'] += 1
        else:
            continue
        entry = q.ask * (1 + config.slippage_fraction)
        years = max(0, days/365 - horizon/(365*1440))
        scenario_means = []
        for iv_change in (-.02, 0, .02):
            prices = [option_value(snap.spot * math.exp(mu+scale*z), q.strike, years,
                                   max(.01, q.iv+iv_change), q.right) for z in zs]
            exit_price = max(0, mean(prices) - (q.ask-q.bid)/2) * (1-config.slippage_fraction)
            pnl = (exit_price-entry)*q.lot_size - config.fee(entry*q.lot_size) - config.fee(exit_price*q.lot_size)
            scenario_means.append(pnl)
        # Bound delta magnitude by one for a conservative mean-estimation deduction.
        score = candidate_score(config.source, scenario_means, snap.spot*uncertainty_move*q.lot_size)
        top_candidates.append({
            'instrument': q.instrument,
            'right': q.right,
            'strike': q.strike,
            'lot_size': q.lot_size,
            'bid': round(q.bid, 2),
            'ask': round(q.ask, 2),
            'spread_pct': round(spread_fraction * 100, 3),
            'depth_bid': q.bid_units,
            'depth_ask': q.ask_units,
            'iv': round(q.iv, 4),
            'scenario_means': [round(value, 2) for value in scenario_means],
            'score': round(score, 2),
        })
        if score > 0:
            candidate_counts['positive_score'] += 1
        if score > best_score:
            best, best_score = q, score
            details = {**details, 'reason': 'POSITIVE_BASELINE_SCENARIO_SCORE',
                       'net_ev_rupees': round(score, 2), 'iv_stress_mean_pnl': scenario_means,
                       'not_a_statistical_confidence_bound': True}
    top_candidates.sort(key=lambda item: item['score'], reverse=True)
    details['top_candidates'] = top_candidates[:5]
    return best, details
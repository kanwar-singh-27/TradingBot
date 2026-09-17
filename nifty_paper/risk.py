"""Deterministic full-premium risk; strategy outputs cannot alter these amounts."""

from .models import money


def entry_requirements(config, state, quote, price=None):
    price = money(quote.ask * (1 + config.slippage_fraction)) if price is None else price
    premium = price * quote.lot_size
    fee = config.fee(premium)
    budget = config.risk_fraction * min(config.capital, state['equity'])
    required = premium + 2 * fee
    cash_required = premium + fee
    return {
        'entry_price': price,
        'premium': money(premium),
        'entry_fee': fee,
        'exit_fee_reserve': fee,
        'fees': money(2 * fee),
        'total_entry_cost': money(cash_required),
        'risk_required': money(required),
        'configured_risk_budget': budget,
        'risk_fraction': config.risk_fraction,
        'risk_capital_basis': min(config.capital, state['equity']),
        'cash_available': state['cash'],
        'risk_pass': required <= budget,
        'cash_pass': cash_required <= state['cash'],
    }
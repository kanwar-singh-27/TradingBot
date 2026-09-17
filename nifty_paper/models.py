"""Typed paper-only configuration and source observations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import math

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30), 'IST')


def is_public_source(source):
    return source in ('public', 'public_loose')


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Config:
    source: str = 'public'
    duration_minutes: float = 60
    poll_seconds: float = 60
    capital: float = 1_000_000
    risk_fraction: float = .0025
    daily_loss_fraction: float = .01
    max_spread_fraction: float = .01
    max_age_seconds: float = 90
    hold_minutes: float = 15
    fee_per_order: float = 25
    fee_rate: float = .002
    slippage_fraction: float = .001
    diagnostic: bool = False

    def __post_init__(self):
        if not isinstance(self.diagnostic, bool):
            raise ValueError('diagnostic must be a boolean')
        if self.source not in ('public', 'public_loose', 'demo'):
            raise ValueError('Only public, public_loose, or demo paper sources are permitted; no live mode exists')
        bounds = {
            'duration_minutes': (.01, 375), 'poll_seconds': (.05 if self.source == 'demo' else 60, 300),
            'capital': (1, 1_000_000_000), 'risk_fraction': (.0001, .0025),
            'daily_loss_fraction': (.0001, .01), 'max_spread_fraction': (.0001, .01),
            'max_age_seconds': (1, 90), 'hold_minutes': (1, 60),
            'fee_per_order': (0, 1000), 'fee_rate': (0, .1), 'slippage_fraction': (0, .1),
        }
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{name} must be finite and between {low} and {high}')

    def fee(self, notional):
        return money(self.fee_per_order + abs(notional) * self.fee_rate)


@dataclass(frozen=True)
class Quote:
    instrument: str
    right: str
    strike: float
    expiry: datetime
    bid: float
    ask: float
    bid_units: int
    ask_units: int
    lot_size: int
    iv: float

    def valid(self):
        numbers = (self.strike, self.bid, self.ask, self.iv)
        return (all(math.isfinite(n) and n > 0 for n in numbers)
                and self.bid <= self.ask and self.right in ('CE', 'PE')
                and self.expiry.tzinfo is not None and self.lot_size > 0
                and self.bid_units > 0 and self.ask_units > 0 and self.iv <= 3)

    def exit_valid(self, units):
        return (math.isfinite(self.bid) and self.bid > 0 and self.bid_units >= units
                and (not math.isfinite(self.ask) or self.ask <= 0 or self.bid <= self.ask))


@dataclass(frozen=True)
class Snapshot:
    at: datetime
    received_at: datetime
    spot: float
    bars: tuple
    quotes: tuple[Quote, ...]
    source: str
    kind: str


def market_open(at, entries=False):
    local = at.astimezone(IST)
    minutes = local.hour * 60 + local.minute
    lower, upper = (570, 930) if entries else (555, 930)
    return local.weekday() < 5 and lower <= minutes < upper
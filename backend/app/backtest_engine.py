"""Deterministic metrics for validated out-of-sample equity curves.

This module does not claim that an input data set is point-in-time or
survivorship-free; the public runner stays disabled until those are verified.
"""
from dataclasses import dataclass
from datetime import date
from math import isfinite, sqrt
from statistics import mean, stdev

@dataclass(frozen=True)
class EquityPoint:
    day: date
    portfolio: float
    benchmark: float

def performance_metrics(points: list[EquityPoint], closed_returns: list[float], test_start: date) -> dict:
    if len(points) < 3 or any(p.day < test_start for p in points):
        raise ValueError("At least three out-of-sample observations are required.")
    if any(p.portfolio <= 0 or p.benchmark <= 0 or not isfinite(p.portfolio) or not isfinite(p.benchmark) for p in points):
        raise ValueError("Equity and benchmark values must be positive finite numbers.")
    if any(a.day >= b.day for a, b in zip(points, points[1:])):
        raise ValueError("Equity observations must be strictly chronological.")
    if any(not isfinite(value) for value in closed_returns):
        raise ValueError("Closed returns must be finite.")
    returns = [b.portfolio / a.portfolio - 1 for a, b in zip(points, points[1:])]
    peak, maximum_drawdown = points[0].portfolio, 0.0
    for point in points:
        peak = max(peak, point.portfolio)
        maximum_drawdown = min(maximum_drawdown, point.portfolio / peak - 1)
    deviation = stdev(returns) if len(returns) > 1 else 0
    return {"total_return": points[-1].portfolio / points[0].portfolio - 1,
        "benchmark_return": points[-1].benchmark / points[0].benchmark - 1,
        "max_drawdown": maximum_drawdown,
        "win_rate": sum(value > 0 for value in closed_returns) / len(closed_returns) if closed_returns else None,
        "average_return": mean(closed_returns) if closed_returns else None,
        "annualized_sharpe_zero_risk_free": mean(returns) / deviation * sqrt(252) if deviation else None,
        "note": "Sharpe assumes consecutive trading-day observations and a zero risk-free rate; undefined when return volatility is zero."}

from datetime import datetime, timedelta

class IncompleteBacktestData(ValueError):
    pass

@dataclass(frozen=True)
class UniverseMembership:
    symbol: str
    effective_from: date
    effective_through: date
    known_at: datetime

@dataclass(frozen=True)
class ScreeningSignal:
    contract: str
    symbol: str
    decision_at: datetime
    inputs_available_at: datetime
    expiration: date
    implied_volatility: float
    realized_volatility: float

@dataclass(frozen=True)
class ExecutionQuote:
    contract: str
    timestamp: datetime
    available_at: datetime
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    feed: str

def replay_signals(signals: list[ScreeningSignal], quotes: list[ExecutionQuote], universe: list[UniverseMembership], *,
                   out_of_sample_start: datetime, out_of_sample_end: datetime, holding_days: int,
                   cost_per_side: float, max_spread: float, universe_history_verified: bool) -> list[dict]:
    """Replay one long contract per non-overlapping signal in an independently verified dataset.

    This pure engine is not connected to the public API; its caller must verify
    data provenance, full historical coverage and survival-bias controls.
    Missing execution or expiry data stops the replay rather than being filled.
    """
    if not universe_history_verified:
        raise IncompleteBacktestData("A verified survivorship-aware universe is required.")
    if out_of_sample_start.tzinfo is None or out_of_sample_end.tzinfo is None or out_of_sample_end <= out_of_sample_start:
        raise ValueError("A timezone-aware out-of-sample interval is required.")
    if holding_days < 1 or cost_per_side < 0 or not isfinite(cost_per_side) or not 0 <= max_spread <= 2:
        raise ValueError("Invalid holding period, cost, or spread.")
    for s in signals:
        if s.decision_at.tzinfo is None or s.inputs_available_at.tzinfo is None or s.inputs_available_at > s.decision_at:
            raise ValueError("Signal inputs were not available at decision time.")
        if not (isfinite(s.implied_volatility) and isfinite(s.realized_volatility) and s.implied_volatility > 0 and s.realized_volatility > 0):
            raise ValueError("Invalid volatility inputs.")
    for member in universe:
        if member.known_at.tzinfo is None:
            raise ValueError("Universe availability timestamps must be timezone-aware.")
    for q in quotes:
        if q.timestamp.tzinfo is None or q.available_at.tzinfo is None:
            raise ValueError("Quote timestamps must be timezone-aware.")
    by_time = sorted(signals, key=lambda s: (s.decision_at, s.contract))
    results = []
    last_exit = None
    for signal in by_time:
        if not out_of_sample_start <= signal.decision_at <= out_of_sample_end:
            continue
        if last_exit and signal.decision_at <= last_exit:
            continue
        if not any(m.symbol == signal.symbol and m.effective_from <= signal.decision_at.date() <= m.effective_through and m.known_at <= signal.decision_at for m in universe):
            raise IncompleteBacktestData("Point-in-time membership is missing for a signal.")
        if signal.implied_volatility >= signal.realized_volatility:
            continue
        def usable(q):
            if q.contract != signal.contract or q.feed != "opra" or q.available_at > q.timestamp:
                return False
            if not (isfinite(q.bid) and isfinite(q.ask)) or q.bid <= 0 or q.ask < q.bid or q.bid_size < 1 or q.ask_size < 1:
                return False
            return (q.ask - q.bid) / ((q.ask + q.bid) / 2) <= max_spread
        candidates = sorted((q for q in quotes if usable(q) and signal.decision_at < q.timestamp <= signal.decision_at + timedelta(days=1)), key=lambda q: q.timestamp)
        if not candidates:
            raise IncompleteBacktestData("A timely executable entry quote is missing.")
        entry = candidates[0]
        target = entry.timestamp + timedelta(days=holding_days)
        if target.date() >= signal.expiration:
            raise IncompleteBacktestData("Expiration settlement data has not been implemented or validated.")
        exits = sorted((q for q in quotes if usable(q) and target <= q.timestamp <= min(target + timedelta(days=1), out_of_sample_end) and q.timestamp.date() < signal.expiration), key=lambda q: q.timestamp)
        if not exits:
            raise IncompleteBacktestData("A timely executable exit quote is missing.")
        exit_quote = exits[0]
        profit = (exit_quote.bid - entry.ask) * 100 - 2 * cost_per_side
        results.append({"contract": signal.contract, "signal_at": signal.decision_at, "entry_at": entry.timestamp, "exit_at": exit_quote.timestamp, "entry_ask": entry.ask, "exit_bid": exit_quote.bid, "net_profit": profit})
        last_exit = exit_quote.timestamp
    return results

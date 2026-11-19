from math import log, sqrt
from statistics import stdev

def realized_volatility(closes: list[float], window: int = 20) -> float | None:
    if len(closes) < window + 1 or any(x <= 0 for x in closes[-(window + 1):]):
        return None
    values = closes[-(window + 1):]
    returns = [log(b / a) for a, b in zip(values, values[1:])]
    return stdev(returns) * sqrt(252)

def payoff(kind: str, strike: float, premium: float, price: float, contracts: int = 1) -> float:
    intrinsic = max(price - strike, 0) if kind == "call" else max(strike - price, 0)
    return (intrinsic - premium) * 100 * contracts

def spread(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask < bid:
        return None
    return (ask - bid) / ((ask + bid) / 2)
from math import erf, exp, log, sqrt

def european_option_value(kind: str, spot: float, strike: float, years: float, volatility: float, risk_free_rate: float, dividend_yield: float) -> float:
    """Black-Scholes-Merton, continuous dividend yield; European exercise."""
    if years <= 0:
        return max(spot - strike, 0) if kind == "call" else max(strike - spot, 0)
    discounted_strike = strike * exp(-risk_free_rate * years)
    discounted_spot = spot * exp(-dividend_yield * years)
    if spot <= 0:
        return 0.0 if kind == "call" else discounted_strike
    if volatility <= 0:
        return max(discounted_spot - discounted_strike, 0) if kind == "call" else max(discounted_strike - discounted_spot, 0)
    standard_deviation = volatility * sqrt(years)
    d1 = (log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * volatility * volatility) * years) / standard_deviation
    d2 = d1 - standard_deviation
    def cdf(value: float) -> float:
        return (1 + erf(value / sqrt(2))) / 2
    if kind == "call":
        return max(0.0, discounted_spot * cdf(d1) - discounted_strike * cdf(d2))
    return max(0.0, discounted_strike * cdf(-d2) - discounted_spot * cdf(-d1))

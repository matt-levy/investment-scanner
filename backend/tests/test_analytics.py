import math
from app.analytics import payoff, realized_volatility, spread

def test_payoff():
    assert payoff("call", 100, 5, 120) == 1500
    assert payoff("put", 100, 5, 80) == 1500
    assert payoff("call", 100, 5, 90) == -500

def test_volatility_and_spread():
    assert realized_volatility([100] * 21) == 0
    assert realized_volatility([100] * 20) is None
    assert math.isclose(spread(1, 1.2), 0.2 / 1.1)
    assert spread(0, 1) is None
    assert spread(2, 1) is None

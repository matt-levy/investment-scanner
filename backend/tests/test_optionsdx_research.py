import sqlite3
from datetime import date, timedelta
import pytest
from app.analytics import european_option_value
from app.optionsdx_import import SCHEMA
from app.optionsdx_benchmark import SCHEMA as BENCHMARK_SCHEMA
from app.optionsdx_research import ResearchDataError, estimated_european_iv, quality_report, research_replay

def test_iv_solver_recovers_model_input_and_rejects_bad_quotes():
    price = european_option_value('call', 100, 100, 1, .3, .05, .01)
    assert estimated_european_iv('call', 100, 100, 1, price, price, .05, .01) == pytest.approx(.3, abs=1e-8)
    assert estimated_european_iv('put', 100, 120, 1, 0, 1, .05, .01) is None

def fixture_data():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.executescript(BENCHMARK_SCHEMA)
    db.execute("INSERT INTO imports VALUES (1, 'hash', 'AAPL', 'fixture', 'now', 31)")
    db.execute("INSERT INTO benchmark_imports VALUES (1, 'hash', 'fixture', 'now')")
    first = date(2023, 1, 1)
    for i in range(31):
        day = first + timedelta(days=i)
        price = 100 + (i % 2) * 2
        db.execute('''INSERT INTO option_observations (import_id,ticker,quote_unix,quote_date,expiration,strike_millis,kind,underlying_price,bid,ask,implied_volatility,volume,bid_size,ask_size)
                      VALUES (1,'AAPL',?,?, '2024-01-01',100000,'call',?,4,5,.1,1,5,5)''', (i, day.isoformat(),price))
        db.execute('INSERT INTO benchmark_prices VALUES (?,?,?,1)', (day.isoformat(),i, 400 + i))
    return db

def test_replay_uses_next_observed_session_and_stops_on_missing_mark():
    db = fixture_data()
    start, end = date(2023, 1, 22), date(2023, 1, 31)
    # Widen this synthetic bid/ask for the fixture; normal default is stricter.
    result = research_replay(db, 'AAPL', start, end, 1, hold_sessions=5, max_spread=.3)
    assert result['trade_count'] == 1
    trade = result['trades'][0]
    assert trade['signal_date'] == '2023-01-22'
    assert trade['entry_date'] == '2023-01-23'
    assert trade['exit_date'] == '2023-01-28'
    assert trade['net_profit'] == pytest.approx(-102)
    assert result['benchmark_return'] == pytest.approx(430/421 - 1)
    assert quality_report(db, 'AAPL')['observations'] == 31
    db.execute("DELETE FROM option_observations WHERE quote_date='2023-01-25'")
    # Another observed contract preserves that day, so the missing selected mark is detected.
    db.execute("""INSERT INTO option_observations (import_id,ticker,quote_unix,quote_date,expiration,strike_millis,kind,underlying_price,bid,ask,implied_volatility,volume,bid_size,ask_size)
                 VALUES (1,'AAPL',24,'2023-01-25','2024-01-01',101000,'call',100,4,5,.1,1,5,5)""")
    with pytest.raises(ResearchDataError, match='mark'):
        research_replay(db, 'AAPL', start, end, 1, hold_sessions=5, max_spread=.3)

def test_replay_rejects_split_and_missing_benchmark():
    db = fixture_data()
    with pytest.raises(ResearchDataError, match='stock split'):
        research_replay(db, 'AAPL', date(2020, 8, 1), date(2020, 9, 30), 1)
    with pytest.raises(ResearchDataError, match='NVDA stock split'):
        research_replay(db, 'NVDA', date(2021, 7, 1), date(2021, 8, 1), 1)
    with pytest.raises(ResearchDataError, match='TSLA stock split'):
        research_replay(db, 'TSLA', date(2022, 8, 1), date(2022, 9, 1), 1)
    db.execute("DELETE FROM benchmark_prices WHERE quote_date='2023-01-25'")
    with pytest.raises(ResearchDataError, match='Missing SPY'):
        research_replay(db, 'AAPL', date(2023, 1, 22), date(2023, 1, 31), 1, max_spread=.3)

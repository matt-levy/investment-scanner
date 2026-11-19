"""Restricted exploratory research on imported OptionsDX observations."""
import math
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from .analytics import european_option_value, realized_volatility, spread
from .ranking import screen_factors

class ResearchDataError(ValueError):
    pass

# Effective trading dates, for the 2020–2023 OptionsDX files only.
SPLITS = {'AAPL': [(date(2020, 8, 31), 4)], 'NVDA': [(date(2021, 7, 20), 4)],
          'TSLA': [(date(2020, 8, 31), 5), (date(2022, 8, 25), 3)]}

def open_data():
    path = Path(os.getenv("OPTIONSDX_DATABASE", "data/optionsdx.sqlite")).resolve()
    if not path.is_file():
        raise ResearchDataError("No imported OptionsDX database is available.")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db

def quality_report(db, ticker):
    row = db.execute("""SELECT count(*) n, count(DISTINCT quote_date) days,
        min(quote_date) first, max(quote_date) last,
        sum(CASE WHEN bid IS NULL OR ask IS NULL OR bid <= 0 OR ask < bid THEN 1 ELSE 0 END) bad_quote,
        sum(CASE WHEN implied_volatility IS NULL OR implied_volatility <= 0 THEN 1 ELSE 0 END) missing_iv
        FROM option_observations WHERE ticker=?""", (ticker,)).fetchone()
    if not row['n']:
        raise ResearchDataError("No imported data for this ticker.")
    inconsistent = db.execute("""SELECT count(*) FROM (SELECT quote_date FROM option_observations
        WHERE ticker=? GROUP BY quote_date HAVING count(DISTINCT underlying_price) != 1)""", (ticker,)).fetchone()[0]
    return {"ticker": ticker, "observations": row['n'], "days": row['days'], "first": row['first'],
        "last": row['last'], "unusable_bid_ask": row['bad_quote'], "missing_or_nonpositive_iv": row['missing_iv'],
        "inconsistent_underlying_days": inconsistent,
        "note": "Field checks do not verify quote executability, complete contract coverage, corporate actions, timestamps, or historical data availability."}

def estimated_european_iv(kind, spot, strike, years, bid, ask, rate, dividend_yield):
    """Invert a European model at midpoint. This approximates American equity options."""
    if kind not in ('call', 'put') or not all(math.isfinite(x) for x in (spot, strike, years, bid, ask, rate, dividend_yield)):
        return None
    if min(spot, strike, years, bid) <= 0 or ask < bid:
        return None
    target = (bid + ask) / 2
    intrinsic = max(spot - strike, 0) if kind == 'call' else max(strike - spot, 0)
    if target < intrinsic:
        return None
    low, high = .0001, 5.0
    if not (european_option_value(kind, spot, strike, years, low, rate, dividend_yield) <= target <= european_option_value(kind, spot, strike, years, high, rate, dividend_yield)):
        return None
    for _ in range(48):
        middle = (low + high) / 2
        if european_option_value(kind, spot, strike, years, middle, rate, dividend_yield) < target:
            low = middle
        else:
            high = middle
    return (low + high) / 2

def research_replay(db, ticker, start, end, fee, initial_cash=10000.0, hold_sessions=5, max_spread=.2):
    """Single-position, daily EOD experiment, with strict missing-mark failure."""
    if end <= start or fee < 0 or not math.isfinite(fee):
        raise ResearchDataError("Invalid test dates or fee.")
    if ticker not in SPLITS or start < date(2020, 1, 1) or end > date(2023, 12, 31):
        raise ResearchDataError("This experimental replay supports only AAPL, NVDA and TSLA data dated 2020–2023.")
    for split_date, _ in SPLITS[ticker]:
        if start < split_date <= end:
            raise ResearchDataError(f"This period crosses the {ticker} stock split on {split_date}. Run separate tests before and after the split; adjusted option contracts are not supported.")
    quality = quality_report(db, ticker)
    if quality['inconsistent_underlying_days']:
        raise ResearchDataError("Underlying prices disagree within a date.")
    data = db.execute("""SELECT * FROM option_observations WHERE ticker=? AND quote_date>=? AND quote_date<=?
        ORDER BY quote_date, expiration, strike_millis, kind""", (ticker, (start-timedelta(days=90)).isoformat(), end.isoformat())).fetchall()
    daily = {}
    for row in data:
        daily.setdefault(row['quote_date'], []).append(row)
    days = sorted(daily)
    for day, rows in daily.items():
        keys = [(row['expiration'], row['strike_millis'], row['kind']) for row in rows]
        if len({row['quote_unix'] for row in rows}) != 1 or len(set(keys)) != len(keys):
            raise ResearchDataError(f"Multiple quote times or duplicate contracts on {day}; daily replay stopped.")
    if len(days) < 22 or end.isoformat() not in daily or start.isoformat() not in daily:
        raise ResearchDataError("Start and end must be observed trading dates with at least 21 earlier observations.")
    start_index, end_index = days.index(start.isoformat()), days.index(end.isoformat())
    if start_index < 21:
        raise ResearchDataError("At least 21 earlier daily prices are required for volatility.")
    prices = [daily[d][0]['underlying_price'] for d in days]
    if any(p is None or p <= 0 or not math.isfinite(p) for p in prices):
        raise ResearchDataError("Missing or invalid underlying price.")
    try:
        benchmark_rows = db.execute('SELECT quote_date, quote_unix, price FROM benchmark_prices WHERE quote_date BETWEEN ? AND ?',
            (days[start_index - 20], end.isoformat())).fetchall()
    except sqlite3.OperationalError as exc:
        raise ResearchDataError('SPY benchmark prices have not been imported.') from exc
    benchmark = {row['quote_date']: row for row in benchmark_rows}
    missing_underlying = sorted(set(benchmark) - set(days))
    if missing_underlying:
        raise ResearchDataError(f"Missing {ticker} observations on SPY trading date {missing_underlying[0]}; replay stopped.")
    for day in days[start_index-20:end_index+1]:
        if day not in benchmark:
            raise ResearchDataError(f'Missing SPY benchmark price for {day}.')
        if benchmark[day]['quote_unix'] != daily[day][0]['quote_unix']:
            raise ResearchDataError(f'{ticker} and SPY quote times differ on {day}.')
    def key(row):
        return (row['expiration'], row['strike_millis'], row['kind'])
    def usable(row):
        s = spread(row['bid'], row['ask'])
        return s is not None and s <= max_spread and (row['bid_size'] or 0) >= 1 and (row['ask_size'] or 0) >= 1
    cash = initial_cash
    baseline_price = benchmark[start.isoformat()]['price']
    equity = []
    trades = []
    position = None
    pending = None
    for i in range(start_index, end_index + 1):
        day = days[i]
        rows = daily[day]
        by_contract = {key(row): row for row in rows}
        if position:
            quote = by_contract.get(position['key'])
            if quote is None or not usable(quote):
                raise ResearchDataError(f"Missing or unusable mark for an open position on {day}; replay stopped.")
            if i - position['entry_index'] >= hold_sessions:
                proceeds = quote['bid'] * 100 - fee
                cash += proceeds
                trades.append({'signal_date': position['signal_date'], 'entry_date': position['entry_date'], 'exit_date': day,
                    'expiration': position['key'][0], 'strike': position['key'][1] / 1000, 'kind': position['key'][2],
                    'entry_ask': position['entry_ask'], 'exit_bid': quote['bid'], 'net_profit': proceeds - position['cost']})
                position = None
        if pending:
            quote = by_contract.get(pending['key'])
            if quote is None or not usable(quote):
                raise ResearchDataError(f"Missing or unusable next-session entry quote on {day}; replay stopped.")
            cost = quote['ask'] * 100 + fee
            if cost > cash:
                raise ResearchDataError(f"Insufficient simulated cash for the selected contract on {day}; replay stopped.")
            cash -= cost
            position = {'key': pending['key'], 'signal_date': pending['signal_date'], 'entry_date': day,
                'entry_index': i, 'entry_ask': quote['ask'], 'cost': cost}
            pending = None
        mark = by_contract[position['key']]['bid'] * 100 if position else 0
        equity.append({'date': day, 'equity': round(cash + mark, 2), 'benchmark': round(initial_cash * benchmark[day]['price'] / baseline_price, 2)})
        # Leave enough observed sessions to enter and exit; never manufacture a final sale.
        if not position and i + 1 + hold_sessions <= end_index:
            # Adjust only the trailing price observations that precede the known 4:1 split.
            decision_day = date.fromisoformat(day)
            history = [p / math.prod(ratio for split_day, ratio in SPLITS[ticker] if date.fromisoformat(d) < split_day <= decision_day)
                       for d, p in zip(days[:i+1], prices[:i+1])]
            rv = realized_volatility(history)
            candidates = []
            for row in rows:
                dte = (date.fromisoformat(row['expiration']) - date.fromisoformat(day)).days
                iv = row['implied_volatility']
                if not 90 <= dte <= 548 or iv is None or not math.isfinite(iv) or iv <= 0 or not usable(row) or row['ask'] * 100 + fee > cash:
                    continue
                factors = screen_factors({'iv': iv, 'spread': spread(row['bid'], row['ask']), 'bid':row['bid'], 'ask':row['ask'],
                    'quote_timestamp':row['quote_unix'], 'volume':row['volume'], 'open_interest':None, 'stale':False}, rv)
                candidates.append((-(factors['score'] or 0), key(row)))
            if candidates:
                candidates.sort()
                pending = {'key': candidates[0][1], 'signal_date':day}
    if position or pending:
        raise ResearchDataError("The test ends with an unclosed position.")
    return {'status':'exploratory', 'ticker':ticker, 'start':start.isoformat(), 'end':end.isoformat(),
        'initial_cash':initial_cash, 'final_equity':round(cash, 2), 'total_return':cash / initial_cash - 1,
        'benchmark_return':benchmark[end.isoformat()]['price'] / baseline_price - 1, 'fee_per_side':fee,
        'holding_sessions':hold_sessions, 'trade_count':len(trades), 'trades':trades, 'equity':equity,
        'limitations':[f'{ticker} was chosen with hindsight; this is a single-security exploratory test, not a market-wide strategy validation.',
            'No independent model calibration or separate out-of-sample validation is established.',
            'Daily file publication timing, coverage, corporate actions and quote executability are unverified.',
            'Signals use provider IV, not reconstructed IV. Missing IV is excluded.',
            'Entry and exit are assumed at next observed daily ask and bid; actual fills may differ.',
            'Benchmark is SPY price return only and excludes dividends and fund-investment costs.']}

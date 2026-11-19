import sqlite3
import pytest
from app.optionsdx_import import SCHEMA, import_file

HEADER = '[QUOTE_UNIXTIME], [QUOTE_DATE], [UNDERLYING_LAST], [EXPIRE_DATE], [STRIKE], [C_BID], [C_ASK], [C_IV], [C_VOLUME], [C_SIZE], [P_BID], [P_ASK], [P_IV], [P_VOLUME], [P_SIZE]\n'
ROW = '1672779600, 2023-01-03, 125.01, 2023-12-15, 120, 10, 11, 0.25, 3, 5 x 6, 4, 5, , 2, 7 x 8\n'

def test_import_preserves_missing_values_and_is_idempotent(tmp_path):
    path = tmp_path / 'aapl.csv'
    path.write_text(HEADER + ROW, encoding='utf8')
    with sqlite3.connect(':memory:') as db:
        db.executescript(SCHEMA)
        assert import_file(db, path, 'AAPL')['option_observations'] == 2
        assert import_file(db, path, 'AAPL')['status'] == 'already imported'
        rows = db.execute('SELECT kind, implied_volatility, bid_size, ask_size, strike_millis FROM option_observations ORDER BY kind').fetchall()
        assert rows == [('call', .25, 5, 6, 120000), ('put', None, 7, 8, 120000)]

def test_bad_input_and_conflicting_import_roll_back(tmp_path):
    good = tmp_path / 'good.csv'
    good.write_text(HEADER + ROW, encoding='utf8')
    bad = tmp_path / 'bad.csv'
    bad.write_text(HEADER + ROW + 'bad,row\n', encoding='utf8')
    with sqlite3.connect(':memory:') as db:
        db.executescript(SCHEMA)
        with pytest.raises(ValueError):
            import_file(db, bad, 'AAPL')
        assert db.execute('SELECT count(*) FROM imports').fetchone()[0] == 0
        import_file(db, good, 'AAPL')
        other = tmp_path / 'other.csv'
        other.write_text(HEADER + ROW.replace('10, 11', '9, 11'), encoding='utf8')
        with pytest.raises(sqlite3.IntegrityError):
            import_file(db, other, 'AAPL')
        assert db.execute('SELECT count(*) FROM imports').fetchone()[0] == 1

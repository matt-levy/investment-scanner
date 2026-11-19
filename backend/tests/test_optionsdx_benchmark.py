import sqlite3
import pytest
from app.optionsdx_benchmark import SCHEMA, import_benchmark

def test_benchmark_import_checks_daily_prices_and_deduplicates(tmp_path):
    header = '[QUOTE_DATE], [QUOTE_UNIXTIME], [UNDERLYING_LAST]\n'
    row = '2023-01-03, 1672779600, 380.5\n'
    path = tmp_path / 'spy.csv'
    path.write_text(header + row + row, encoding='utf8')
    with sqlite3.connect(':memory:') as db:
        db.executescript(SCHEMA)
        assert import_benchmark(db, path)['days'] == 1
        assert import_benchmark(db, path)['status'] == 'already imported'
        assert db.execute('SELECT price FROM benchmark_prices').fetchone()[0] == 380.5
        bad = tmp_path / 'bad.csv'
        bad.write_text(header + row + row.replace('380.5', '381'), encoding='utf8')
        with pytest.raises(ValueError, match='inconsistent'):
            import_benchmark(db, bad)
        assert db.execute('SELECT count(*) FROM benchmark_imports').fetchone()[0] == 1

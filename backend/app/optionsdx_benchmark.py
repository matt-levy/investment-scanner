"""Import only daily underlying observations from OptionsDX SPY archives."""
import argparse
import csv
import hashlib
import json
import math
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from .optionsdx_import import input_stream, normalize_header

SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_imports (
 id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL, imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmark_prices (
 quote_date TEXT PRIMARY KEY, quote_unix INTEGER NOT NULL, price REAL NOT NULL,
 import_id INTEGER NOT NULL REFERENCES benchmark_imports(id)
);
"""

def import_benchmark(db, path):
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if db.execute('SELECT 1 FROM benchmark_imports WHERE sha256=?', (digest,)).fetchone():
        return {'file':path.name, 'status':'already imported'}
    days = {}
    header = None
    with input_stream(path) as stream:
        for line, fields in enumerate(csv.reader(stream, skipinitialspace=True), 1):
            if not fields or not any(x.strip() for x in fields):
                continue
            cols = normalize_header(fields)
            if 'QUOTE_UNIXTIME' in cols:
                if not {'QUOTE_UNIXTIME','QUOTE_DATE','UNDERLYING_LAST'} <= set(cols) or len(cols) != len(set(cols)):
                    raise ValueError(f'{path.name} line {line}: invalid header')
                header = cols
                continue
            if header is None or len(fields) != len(header):
                raise ValueError(f'{path.name} line {line}: invalid row')
            row = dict(zip(header, fields))
            try:
                day = date.fromisoformat(row['QUOTE_DATE'].strip()).isoformat()
                timestamp, price = int(row['QUOTE_UNIXTIME']), float(row['UNDERLYING_LAST'])
                if not math.isfinite(price) or price <= 0:
                    raise ValueError('invalid underlying price')
            except ValueError as exc:
                raise ValueError(f'{path.name} line {line}: {exc}') from exc
            if day in days and days[day] != (timestamp, price):
                raise ValueError(f'{path.name}: inconsistent SPY price or timestamp for {day}')
            days[day] = (timestamp, price)
    if not days:
        raise ValueError(f'{path.name}: no observations')
    with db:
        import_id = db.execute('INSERT INTO benchmark_imports (sha256,filename,imported_at) VALUES (?,?,?)',
            (digest,path.name,datetime.now(timezone.utc).isoformat())).lastrowid
        db.executemany('INSERT INTO benchmark_prices VALUES (?,?,?,?)',
            [(day, timestamp, price, import_id) for day, (timestamp, price) in days.items()])
    return {'file':path.name,'status':'imported','days':len(days),'sha256':digest}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--database', type=Path, default=Path('data/optionsdx.sqlite'))
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('Import options first to create the research database.')
    with sqlite3.connect(args.database) as db:
        db.executescript('PRAGMA foreign_keys = ON; ' + SCHEMA)
        for path in args.files:
            try:
                print(json.dumps(import_benchmark(db, path)), flush=True)
            except (OSError, ValueError, sqlite3.Error) as exc:
                parser.exit(1, f'Import failed for {path.name}: {exc}\n')

if __name__ == '__main__':
    main()

"""Import local OptionsDX files into a separate, reproducible research database.

Run from the backend directory: python -m app.optionsdx_import --ticker AAPL FILE...
The SQLite database is intentionally separate from live scanner quotes.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED = {"QUOTE_UNIXTIME", "QUOTE_DATE", "UNDERLYING_LAST", "EXPIRE_DATE", "STRIKE",
            "C_BID", "C_ASK", "C_IV", "C_VOLUME", "P_BID", "P_ASK", "P_IV", "P_VOLUME"}

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, ticker TEXT NOT NULL,
  filename TEXT NOT NULL, imported_at TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(sha256, ticker)
);
CREATE TABLE IF NOT EXISTS option_observations (
  id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES imports(id),
  ticker TEXT NOT NULL, quote_unix INTEGER NOT NULL, quote_date TEXT NOT NULL,
  expiration TEXT NOT NULL, strike_millis INTEGER NOT NULL, kind TEXT NOT NULL,
  underlying_price REAL, bid REAL, ask REAL, implied_volatility REAL, volume REAL,
  bid_size INTEGER, ask_size INTEGER,
  UNIQUE(ticker, quote_unix, expiration, strike_millis, kind)
);
CREATE INDEX IF NOT EXISTS ix_optionsdx_date ON option_observations(ticker, quote_date, expiration);
"""

def number(value):
    if not value or not value.strip():
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite numeric value")
    return result

def sizes(value):
    if not value or not value.strip():
        return None, None
    match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", value)
    if not match:
        raise ValueError("Invalid quote size")
    return int(match.group(1)), int(match.group(2))

def normalize_header(row):
    return [cell.strip().strip("[]").upper() for cell in row]

def observations(row, ticker, import_id):
    timestamp = int(row["QUOTE_UNIXTIME"].strip())
    datetime.fromtimestamp(timestamp, timezone.utc)  # Validate timestamp range.
    quoted = date.fromisoformat(row["QUOTE_DATE"].strip())
    expiration = date.fromisoformat(row["EXPIRE_DATE"].strip())
    strike = Decimal(row["STRIKE"].strip()) * 1000
    if not strike.is_finite() or strike <= 0 or strike != strike.to_integral_value():
        raise ValueError("Invalid strike")
    underlying = number(row["UNDERLYING_LAST"])
    result = []
    for prefix, kind in (("C", "call"), ("P", "put")):
        bid_size, ask_size = sizes(row.get(prefix + "_SIZE", ""))
        result.append((import_id, ticker, timestamp, quoted.isoformat(), expiration.isoformat(),
            int(strike), kind, underlying, number(row[prefix + "_BID"]), number(row[prefix + "_ASK"]),
            number(row[prefix + "_IV"]), number(row[prefix + "_VOLUME"]), bid_size, ask_size))
    return result

@contextmanager
def input_stream(path):
    if path.suffix.lower() in (".csv", ".txt"):
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            yield stream
    elif path.suffix.lower() == ".7z":
        # tar streams members without extracting paths or invoking a shell.
        import io
        try:
            process = subprocess.Popen(["tar", "-xOf", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as exc:
            raise ValueError("A tar executable with 7z support is required for archives; alternatively extract the CSV files first.") from exc
        try:
            with io.TextIOWrapper(process.stdout, encoding="utf-8-sig", newline="") as stream:
                yield stream
            errors = process.stderr.read().decode("utf-8", errors="replace")
            if process.wait() != 0:
                raise ValueError("Unable to read archive: " + errors[:300])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stderr.close()
    else:
        raise ValueError("Only .7z, .csv, and .txt files are supported")

def import_file(db, path, ticker):
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if db.execute("SELECT 1 FROM imports WHERE sha256=? AND ticker=?", (digest, ticker)).fetchone():
        return {"file": path.name, "status": "already imported"}
    count = 0
    with db:
        cursor = db.execute("INSERT INTO imports (sha256,ticker,filename,imported_at) VALUES (?,?,?,?)",
            (digest, ticker, path.name, datetime.now(timezone.utc).isoformat()))
        import_id = cursor.lastrowid
        header = None
        batch = []
        with input_stream(path) as stream:
            for line, fields in enumerate(csv.reader(stream, skipinitialspace=True), 1):
                if not fields or not any(field.strip() for field in fields):
                    continue
                normalized = normalize_header(fields)
                if "QUOTE_UNIXTIME" in normalized:
                    if len(normalized) != len(set(normalized)) or not REQUIRED.issubset(normalized):
                        raise ValueError(f"{path.name}, line {line}: missing or duplicate required columns")
                    header = normalized
                    continue
                if header is None or len(fields) != len(header):
                    raise ValueError(f"{path.name}, line {line}: missing header or incorrect column count")
                try:
                    batch.extend(observations(dict(zip(header, fields)), ticker, import_id))
                except (ValueError, InvalidOperation, OverflowError) as exc:
                    raise ValueError(f"{path.name}, line {line}: invalid input: {exc}") from exc
                count += 1
                if len(batch) >= 4000:
                    db.executemany("INSERT INTO option_observations (import_id,ticker,quote_unix,quote_date,expiration,strike_millis,kind,underlying_price,bid,ask,implied_volatility,volume,bid_size,ask_size) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                    batch.clear()
        if not count:
            raise ValueError(f"{path.name}: no option rows found")
        if batch:
            db.executemany("INSERT INTO option_observations (import_id,ticker,quote_unix,quote_date,expiration,strike_millis,kind,underlying_price,bid,ask,implied_volatility,volume,bid_size,ask_size) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        db.execute("UPDATE imports SET row_count=? WHERE id=?", (count, import_id))
    return {"file": path.name, "status": "imported", "source_rows": count, "option_observations": count * 2, "sha256": digest}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="Underlying symbol; OptionsDX rows do not identify it")
    parser.add_argument("--database", type=Path, default=Path("data/optionsdx.sqlite"))
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    ticker = args.ticker.upper()
    if not re.fullmatch(r"[A-Z]{1,6}", ticker):
        parser.error("Ticker must contain 1–6 letters")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.database) as db:
        db.executescript(SCHEMA)
        for path in args.files:
            try:
                print(json.dumps(import_file(db, path, ticker)), flush=True)
            except (OSError, ValueError, sqlite3.Error) as exc:
                parser.exit(1, f"Import failed for {path.name}: {exc}\n")
    print(f"Research database: {args.database}")

if __name__ == "__main__":
    main()

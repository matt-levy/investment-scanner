import os
import tempfile
from pathlib import Path
test_dir = tempfile.mkdtemp(prefix="scanner-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + Path(test_dir, "scanner.db").as_posix()

from app.db import Base, engine
from app import market_db, research_db, watchlist_db, paper_db
Base.metadata.create_all(engine)

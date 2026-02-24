"""Check if the database is reachable. Exits 0 if ready, 1 if not."""

import os
import sys

from sqlalchemy import create_engine, text

db_url = "postgresql+psycopg2://{}:{}@{}:{}/{}".format(
    os.environ["DB_USER"],
    os.environ["DB_PASS"],
    os.environ["DB_HOST"],
    os.environ.get("DB_PORT", "5432"),
    os.environ.get("DB_NAME", "superset"),
)

try:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    sys.exit(0)
except Exception:
    sys.exit(1)

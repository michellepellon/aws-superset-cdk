"""Run Superset DB migrations with PostgreSQL advisory lock for concurrency safety."""

import os
import subprocess

from sqlalchemy import create_engine, text

db_url = "postgresql+psycopg2://{}:{}@{}:{}/{}".format(
    os.environ["DB_USER"],
    os.environ["DB_PASS"],
    os.environ["DB_HOST"],
    os.environ.get("DB_PORT", "5432"),
    os.environ.get("DB_NAME", "superset"),
)

LOCK_ID = 73829  # Arbitrary advisory lock ID for Superset migrations

engine = create_engine(db_url)

with engine.connect() as conn:
    acquired = conn.execute(
        text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}
    ).scalar()

    if acquired:
        print("[bootstrap] Acquired migration lock, running migrations...")
        try:
            subprocess.check_call(["superset", "db", "upgrade"])
            subprocess.check_call(["superset", "init"])
            print("[bootstrap] Migrations complete")
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
    else:
        print("[bootstrap] Another task is running migrations, skipping...")

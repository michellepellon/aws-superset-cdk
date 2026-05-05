"""Run Superset DB migrations with PostgreSQL advisory lock for concurrency safety."""

import os
import subprocess

from sqlalchemy import create_engine, text

import init_roles

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
            print("[bootstrap] Migrations complete; ensuring custom roles...")
            # Build a Superset Flask app context to access the SecurityManager.
            # Imported here (not at module top) so subprocess `superset` calls
            # above run in their own clean process without inheriting state.
            from superset.app import create_app

            app = create_app()
            with app.app_context():
                init_roles.ensure_analyst_role(app.appbuilder.sm)
            print("[bootstrap] Custom roles ensured")
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
    else:
        print("[bootstrap] Another task is running migrations, skipping...")

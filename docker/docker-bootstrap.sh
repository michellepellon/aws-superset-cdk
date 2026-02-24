#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Superset bootstrap entrypoint
#
# Handles:
#   1. Waiting for database readiness (Aurora cold start can take ~15s)
#   2. Running DB migrations with PostgreSQL advisory lock (concurrency-safe)
#   3. Initializing Superset roles
#   4. Starting the appropriate service based on SUPERSET_ROLE
# ---------------------------------------------------------------------------

ROLE="${SUPERSET_ROLE:-web}"

echo "[bootstrap] Starting Superset role: ${ROLE}"

# ---------------------------------------------------------------------------
# Wait for database
# ---------------------------------------------------------------------------
wait_for_db() {
    local retries=30
    local wait=5
    for i in $(seq 1 $retries); do
        if python /app/db_ready.py 2>/dev/null; then
            echo "[bootstrap] Database is ready"
            return 0
        fi
        echo "[bootstrap] Waiting for database (attempt ${i}/${retries})..."
        sleep $wait
    done
    echo "[bootstrap] ERROR: Database not available after ${retries} attempts"
    exit 1
}

# ---------------------------------------------------------------------------
# Start service
# ---------------------------------------------------------------------------
wait_for_db
python /app/run_migrations.py

case "${ROLE}" in
    web)
        echo "[bootstrap] Starting gunicorn..."
        exec gunicorn \
            --bind 0.0.0.0:8088 \
            --workers "${GUNICORN_WORKERS:-2}" \
            --timeout "${GUNICORN_TIMEOUT:-120}" \
            --limit-request-line 0 \
            --limit-request-field_size 0 \
            --access-logfile - \
            "superset.app:create_app()"
        ;;
    worker)
        echo "[bootstrap] Starting Celery worker..."
        exec celery \
            --app=superset.tasks.celery_app:app \
            worker \
            --loglevel=INFO \
            --max-tasks-per-child=128 \
            --pool=prefork \
            --concurrency=2
        ;;
    beat)
        echo "[bootstrap] Starting Celery beat..."
        exec celery \
            --app=superset.tasks.celery_app:app \
            beat \
            --loglevel=INFO \
            --schedule=/tmp/celerybeat-schedule
        ;;
    *)
        echo "[bootstrap] ERROR: Unknown SUPERSET_ROLE: ${ROLE}"
        exit 1
        ;;
esac

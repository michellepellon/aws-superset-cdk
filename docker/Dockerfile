FROM apache/superset:6.0.0

USER root

# Install drivers and dependencies:
#   - psycopg2: PostgreSQL (Aurora metadata DB)
#   - redis/celery: async task queue
#   - Authlib: Entra ID OIDC authentication
#   - duckdb-engine: MotherDuck / DuckDB data source support
RUN . /app/.venv/bin/activate && uv pip install --no-cache \
    psycopg2-binary==2.9.10 \
    redis==5.2.1 \
    celery[redis]==5.4.0 \
    Authlib==1.4.1 \
    duckdb-engine==0.17.0 \
    duckdb==1.4.4

# Copy Superset configuration
COPY superset_config.py /app/superset_config.py
ENV SUPERSET_CONFIG_PATH=/app/superset_config.py

# Copy bootstrap scripts
COPY docker-bootstrap.sh /app/docker-bootstrap.sh
COPY db_ready.py /app/db_ready.py
COPY run_migrations.py /app/run_migrations.py
COPY init_roles.py /app/init_roles.py
RUN chmod +x /app/docker-bootstrap.sh

USER superset

EXPOSE 8088

ENTRYPOINT ["/app/docker-bootstrap.sh"]

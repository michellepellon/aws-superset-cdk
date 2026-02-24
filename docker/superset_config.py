"""Superset configuration — all values sourced from environment variables.

Injected by ECS task definition via Secrets Manager and plain env vars.
"""

import logging
import os

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
APP_NAME = "Superset"

# ---------------------------------------------------------------------------
# Database (Aurora Serverless v2 PostgreSQL)
# ---------------------------------------------------------------------------
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASS"]
DB_HOST = os.environ["DB_HOST"]
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "superset")

SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
REDIS_HOST = os.environ["REDIS_HOST"]
REDIS_PORT = os.environ.get("REDIS_PORT", "6379")
REDIS_AUTH = os.environ.get("REDIS_AUTH", "")

REDIS_BASE_URL = f"rediss://:{REDIS_AUTH}@{REDIS_HOST}:{REDIS_PORT}"


def _celery_redis_url(db: int) -> str:
    """Celery expects CERT_REQUIRED (uppercase)."""
    return f"{REDIS_BASE_URL}/{db}?ssl_cert_reqs=CERT_REQUIRED"


def _cache_redis_url(db: int) -> str:
    """Flask-Caching / redis-py expects 'required' (lowercase)."""
    return f"{REDIS_BASE_URL}/{db}?ssl_cert_reqs=required"


# ---------------------------------------------------------------------------
# Celery (async queries, alerts, reports)
# ---------------------------------------------------------------------------


class CeleryConfig:
    broker_url = _celery_redis_url(0)
    result_backend = _celery_redis_url(1)
    broker_transport_options = {"visibility_timeout": 3600}
    broker_use_ssl = {"ssl_cert_reqs": "CERT_REQUIRED"}
    redis_backend_use_ssl = {"ssl_cert_reqs": "CERT_REQUIRED"}
    # Acknowledge tasks only after completion — safe with Fargate Spot
    task_acks_late = True
    worker_prefetch_multiplier = 1
    worker_max_tasks_per_child = 128


CELERY_CONFIG = CeleryConfig

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_URL": _cache_redis_url(2),
}

DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "superset_data_",
    "CACHE_REDIS_URL": _cache_redis_url(3),
}

FILTER_STATE_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 600,
    "CACHE_KEY_PREFIX": "superset_filter_",
    "CACHE_REDIS_URL": _cache_redis_url(4),
}

EXPLORE_FORM_DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 600,
    "CACHE_KEY_PREFIX": "superset_explore_",
    "CACHE_REDIS_URL": _cache_redis_url(4),
}

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
    "ALERT_REPORTS": True,
    "DASHBOARD_CROSS_FILTERS": True,
    "DASHBOARD_RBAC": True,
    "EMBEDDABLE_CHARTS": True,
    "SCHEDULED_QUERIES": True,
}

# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------
ENABLE_PROXY_FIX = True  # Required behind ALB / Cloudflare
PROXY_FIX_CONFIG = {
    "x_for": 1,
    "x_proto": 0,  # Ignore ALB's X-Forwarded-Proto (always http)
    "x_host": 1,
    "x_prefix": 1,
}

# Talisman CSP disabled — Cloudflare handles HTTPS headers
TALISMAN_ENABLED = False


def FLASK_APP_MUTATOR(app):
    """Force HTTPS scheme — Cloudflare terminates SSL before the ALB."""
    _inner = app.wsgi_app
    def _force_https(environ, start_response):
        environ["wsgi.url_scheme"] = "https"
        return _inner(environ, start_response)
    app.wsgi_app = _force_https

# ---------------------------------------------------------------------------
# Authentication — Microsoft Entra ID (Azure AD) via OIDC
# ---------------------------------------------------------------------------
# Enabled when ENTRA_TENANT_ID and ENTRA_CLIENT_ID env vars are set.
# Falls back to local database auth when not configured.

ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID")
ENTRA_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID")
ENTRA_CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET")
ENTRA_DEFAULT_ROLE = os.environ.get("ENTRA_DEFAULT_ROLE", "Gamma")

if ENTRA_TENANT_ID and ENTRA_CLIENT_ID:
    from flask_appbuilder.security.manager import AUTH_OAUTH

    logger = logging.getLogger(__name__)
    logger.info("Entra ID authentication enabled (tenant: %s)", ENTRA_TENANT_ID)

    AUTH_TYPE = AUTH_OAUTH
    AUTH_USER_REGISTRATION = True
    AUTH_USER_REGISTRATION_ROLE = ENTRA_DEFAULT_ROLE

    OAUTH_PROVIDERS = [
        {
            "name": "azure",
            "icon": "fa-windows",
            "token_key": "access_token",
            "remote_app": {
                "client_id": ENTRA_CLIENT_ID,
                "client_secret": ENTRA_CLIENT_SECRET,
                "api_base_url": f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/",
                "server_metadata_url": (
                    f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"
                    "/v2.0/.well-known/openid-configuration"
                ),
                "client_kwargs": {
                    "scope": "openid email profile User.Read",
                },
            },
        },
    ]

    from superset.security import SupersetSecurityManager

    class EntraSecurityManager(SupersetSecurityManager):
        """Map Entra ID user info to Superset user fields."""

        def oauth_user_info(self, provider, response=None):
            if provider != "azure":
                return super().oauth_user_info(provider, response)

            token = self.appbuilder.sm.oauth_remotes[provider].get(
                "https://graph.microsoft.com/v1.0/me"
            )
            me = token.json()
            return {
                "username": me.get("userPrincipalName", me.get("mail", "")),
                "first_name": me.get("givenName", ""),
                "last_name": me.get("surname", ""),
                "email": me.get("mail", me.get("userPrincipalName", "")),
            }

    CUSTOM_SECURITY_MANAGER = EntraSecurityManager

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
WTF_CSRF_ENABLED = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True

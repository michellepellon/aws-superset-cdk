from dataclasses import dataclass, field


@dataclass(frozen=True)
class EnvironmentConfig:
    """Configuration for a deployment environment."""

    env_name: str

    # Networking
    nat_gateways: int
    max_azs: int

    # Aurora Serverless v2
    aurora_min_acu: float
    aurora_max_acu: float
    aurora_backup_retention_days: int

    # ElastiCache Redis
    redis_node_type: str
    redis_num_replicas: int

    # Fargate - Web
    web_cpu: int
    web_memory_mib: int
    web_desired_count: int
    web_min_count: int
    web_max_count: int

    # Fargate - Worker
    worker_cpu: int
    worker_memory_mib: int
    worker_desired_count: int
    worker_min_count: int
    worker_max_count: int
    worker_spot: bool

    # Fargate - Beat
    beat_cpu: int
    beat_memory_mib: int

    # Gunicorn
    gunicorn_workers: int
    gunicorn_timeout: int

    # Removal policy (DESTROY for dev, RETAIN for prod)
    removal_destroy: bool

    # Microsoft Entra ID (Azure AD) — set via CDK context:
    #   cdk deploy -c env=dev -c entra_tenant_id=xxx -c entra_client_id=yyy
    # Leave as None to disable Entra auth (falls back to local DB auth).
    entra_tenant_id: str | None = field(default=None)
    entra_client_id: str | None = field(default=None)
    # Superset role to assign to new Entra users on first login
    entra_default_role: str = field(default="Gamma")


DEV = EnvironmentConfig(
    env_name="dev",
    nat_gateways=1,
    max_azs=2,
    aurora_min_acu=0,
    aurora_max_acu=2,
    aurora_backup_retention_days=7,
    redis_node_type="cache.t4g.micro",
    redis_num_replicas=0,
    web_cpu=256,
    web_memory_mib=512,
    web_desired_count=1,
    web_min_count=1,
    web_max_count=3,
    worker_cpu=512,
    worker_memory_mib=1024,
    worker_desired_count=1,
    worker_min_count=1,
    worker_max_count=3,
    worker_spot=True,
    beat_cpu=256,
    beat_memory_mib=512,
    gunicorn_workers=2,
    gunicorn_timeout=120,
    removal_destroy=True,
)

PROD = EnvironmentConfig(
    env_name="prod",
    nat_gateways=2,
    max_azs=2,
    aurora_min_acu=0.5,
    aurora_max_acu=16,
    aurora_backup_retention_days=30,
    redis_node_type="cache.t4g.small",
    redis_num_replicas=1,
    web_cpu=1024,
    web_memory_mib=2048,
    web_desired_count=2,
    web_min_count=2,
    web_max_count=6,
    worker_cpu=1024,
    worker_memory_mib=2048,
    worker_desired_count=2,
    worker_min_count=1,
    worker_max_count=10,
    worker_spot=True,
    beat_cpu=256,
    beat_memory_mib=512,
    gunicorn_workers=4,
    gunicorn_timeout=120,
    removal_destroy=False,
)

ENVIRONMENTS: dict[str, EnvironmentConfig] = {
    "dev": DEV,
    "prod": PROD,
}

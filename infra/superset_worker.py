from aws_cdk import Duration
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from config.environments import EnvironmentConfig


class SupersetWorkerService(Construct):
    """Fargate service running Celery workers (with Spot support)."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: EnvironmentConfig,
        cluster: ecs.ICluster,
        container_image: ecs.ContainerImage,
        db_cluster: rds.IDatabaseCluster,
        db_secret: secretsmanager.ISecret,
        redis_endpoint: str,
        redis_port: str,
        redis_auth_secret: secretsmanager.ISecret,
        superset_secret_key: secretsmanager.ISecret,
        ecs_security_group: ec2.ISecurityGroup,
        entra_client_secret: secretsmanager.ISecret | None = None,
    ) -> None:
        super().__init__(scope, id)

        environment = {
            "SUPERSET_ROLE": "worker",
            "REDIS_HOST": redis_endpoint,
            "REDIS_PORT": redis_port,
            "DB_HOST": db_cluster.cluster_endpoint.hostname,
            "DB_PORT": str(db_cluster.cluster_endpoint.port),
        }

        container_secrets = {
            "DB_USER": ecs.Secret.from_secrets_manager(db_secret, "username"),
            "DB_PASS": ecs.Secret.from_secrets_manager(db_secret, "password"),
            "DB_NAME": ecs.Secret.from_secrets_manager(db_secret, "dbname"),
            "SUPERSET_SECRET_KEY": ecs.Secret.from_secrets_manager(
                superset_secret_key
            ),
            "REDIS_AUTH": ecs.Secret.from_secrets_manager(redis_auth_secret),
        }

        # Microsoft Entra ID
        if config.entra_tenant_id and config.entra_client_id:
            environment["ENTRA_TENANT_ID"] = config.entra_tenant_id
            environment["ENTRA_CLIENT_ID"] = config.entra_client_id
            environment["ENTRA_DEFAULT_ROLE"] = config.entra_default_role
            if entra_client_secret:
                container_secrets["ENTRA_CLIENT_SECRET"] = (
                    ecs.Secret.from_secrets_manager(entra_client_secret)
                )

        task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDef",
            cpu=config.worker_cpu,
            memory_limit_mib=config.worker_memory_mib,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )

        task_definition.add_container(
            "worker",
            image=container_image,
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="superset-worker",
                log_retention=logs.RetentionDays.TWO_WEEKS,
            ),
            environment=environment,
            secrets=container_secrets,
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "celery -A superset.tasks.celery_app:app inspect ping -d celery@$HOSTNAME || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(10),
                retries=3,
                start_period=Duration.seconds(60),
            ),
        )

        # Capacity provider strategy: Spot for workers
        capacity_provider_strategies = []
        if config.worker_spot:
            capacity_provider_strategies.append(
                ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE_SPOT",
                    weight=2,
                )
            )
            capacity_provider_strategies.append(
                ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE",
                    weight=1,
                    base=1,  # At least 1 on-demand task
                )
            )
        else:
            capacity_provider_strategies.append(
                ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE",
                    weight=1,
                )
            )

        self.service = ecs.FargateService(
            self,
            "Service",
            service_name=f"superset-worker-{config.env_name}",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=config.worker_desired_count,
            security_groups=[ecs_security_group],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            assign_public_ip=False,
            capacity_provider_strategies=capacity_provider_strategies,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            propagate_tags=ecs.PropagatedTagSource.SERVICE,
        )

        # Auto-scaling
        scaling = self.service.auto_scale_task_count(
            min_capacity=config.worker_min_count,
            max_capacity=config.worker_max_count,
        )
        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.seconds(300),
            scale_out_cooldown=Duration.seconds(60),
        )

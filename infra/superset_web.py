from aws_cdk import Duration
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from config.environments import EnvironmentConfig


class SupersetWebService(Construct):
    """ALB-fronted Fargate service running Superset web (gunicorn)."""

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
        alb_security_group: ec2.ISecurityGroup,
        ecs_security_group: ec2.ISecurityGroup,
        entra_client_secret: secretsmanager.ISecret | None = None,
    ) -> None:
        super().__init__(scope, id)

        environment = {
            "SUPERSET_ROLE": "web",
            "GUNICORN_WORKERS": str(config.gunicorn_workers),
            "GUNICORN_TIMEOUT": str(config.gunicorn_timeout),
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

        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "Service",
            cluster=cluster,
            service_name=f"superset-web-{config.env_name}",
            desired_count=config.web_desired_count,
            cpu=config.web_cpu,
            memory_limit_mib=config.web_memory_mib,
            security_groups=[ecs_security_group],
            assign_public_ip=False,
            task_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=container_image,
                container_port=8088,
                container_name="web",
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="superset-web",
                    log_retention=logs.RetentionDays.TWO_WEEKS,
                ),
                environment=environment,
                secrets=container_secrets,
            ),
            open_listener=False,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            health_check_grace_period=Duration.seconds(120),
            propagate_tags=ecs.PropagatedTagSource.SERVICE,
        )

        # Use the pre-created ALB security group
        self.service.load_balancer.add_security_group(alb_security_group)

        # Configure health check
        self.service.target_group.configure_health_check(
            path="/health",
            healthy_http_codes="200",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(10),
            healthy_threshold_count=2,
            unhealthy_threshold_count=5,
        )

        # Sticky sessions for Superset UI
        self.service.target_group.set_attribute(
            "stickiness.enabled", "true"
        )
        self.service.target_group.set_attribute(
            "stickiness.type", "lb_cookie"
        )
        self.service.target_group.set_attribute(
            "stickiness.lb_cookie.duration_seconds", "3600"
        )

        # Auto-scaling
        scaling = self.service.service.auto_scale_task_count(
            min_capacity=config.web_min_count,
            max_capacity=config.web_max_count,
        )
        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.seconds(300),
            scale_out_cooldown=Duration.seconds(60),
        )

    @property
    def load_balancer(self) -> elbv2.IApplicationLoadBalancer:
        return self.service.load_balancer

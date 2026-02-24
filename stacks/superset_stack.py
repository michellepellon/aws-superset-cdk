from aws_cdk import CfnOutput, Stack
from constructs import Construct

from config.environments import EnvironmentConfig
from infra.cache import Cache
from infra.container_registry import DockerImage
from infra.database import Database
from infra.ecs_cluster import EcsCluster
from infra.monitoring import Monitoring
from infra.networking import Networking
from infra.secrets import Secrets
from infra.superset_beat import SupersetBeatService
from infra.superset_web import SupersetWebService
from infra.superset_worker import SupersetWorkerService


class SupersetStack(Stack):
    """Main stack deploying Apache Superset on serverless AWS infrastructure."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: EnvironmentConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # --- Networking ---
        networking = Networking(self, "Networking", config=config)

        # --- Secrets ---
        secrets = Secrets(self, "Secrets", config=config)

        # --- Database ---
        database = Database(
            self,
            "Database",
            config=config,
            vpc=networking.vpc,
            security_group=networking.db_sg,
        )

        # --- Cache ---
        cache = Cache(
            self,
            "Cache",
            config=config,
            vpc=networking.vpc,
            security_group=networking.redis_sg,
            auth_token_secret=secrets.redis_auth_token,
        )

        # --- Docker Image (built + pushed automatically) ---
        docker_image = DockerImage(self, "DockerImage", config=config)

        # --- ECS Cluster ---
        ecs_cluster = EcsCluster(
            self, "EcsCluster", config=config, vpc=networking.vpc
        )

        # --- Shared ECS arguments ---
        shared_ecs_kwargs = dict(
            config=config,
            cluster=ecs_cluster.cluster,
            container_image=docker_image.container_image,
            db_cluster=database.cluster,
            db_secret=database.secret,
            redis_endpoint=cache.endpoint,
            redis_port=cache.port,
            redis_auth_secret=cache.auth_token_secret,
            superset_secret_key=secrets.superset_secret_key,
            ecs_security_group=networking.ecs_sg,
            entra_client_secret=secrets.entra_client_secret,
        )

        # --- Web Service (ALB + Fargate) ---
        web = SupersetWebService(
            self,
            "Web",
            alb_security_group=networking.alb_sg,
            **shared_ecs_kwargs,
        )

        # --- Worker Service (Fargate + Spot) ---
        worker = SupersetWorkerService(self, "Worker", **shared_ecs_kwargs)

        # --- Beat Service (Fargate, singleton) ---
        beat = SupersetBeatService(self, "Beat", **shared_ecs_kwargs)

        # --- Monitoring ---
        Monitoring(
            self,
            "Monitoring",
            config=config,
            web_service=web.service.service,
            worker_service=worker.service,
            beat_service=beat.service,
            load_balancer=web.load_balancer,
            db_cluster=database.cluster,
        )

        # --- Outputs ---
        CfnOutput(
            self,
            "AlbDnsName",
            value=web.load_balancer.load_balancer_dns_name,
            description="ALB DNS name — point Cloudflare CNAME here",
        )

        CfnOutput(
            self,
            "DockerImageUri",
            value=docker_image.asset.image_uri,
            description="Docker image URI in ECR (built automatically)",
        )

        CfnOutput(
            self,
            "EcsClusterName",
            value=ecs_cluster.cluster.cluster_name,
            description="ECS cluster name for run-task commands",
        )

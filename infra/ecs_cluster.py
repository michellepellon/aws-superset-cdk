from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from constructs import Construct

from config.environments import EnvironmentConfig


class EcsCluster(Construct):
    """ECS cluster with Fargate and Fargate Spot capacity providers."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: EnvironmentConfig,
        vpc: ec2.IVpc,
    ) -> None:
        super().__init__(scope, id)

        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=f"superset-{config.env_name}",
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
            enable_fargate_capacity_providers=True,
        )

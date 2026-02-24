from aws_cdk import RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_logs as logs
from constructs import Construct

from config.environments import EnvironmentConfig


class Networking(Construct):
    """VPC with public and private subnets for Superset deployment."""

    def __init__(
        self, scope: Construct, id: str, *, config: EnvironmentConfig
    ) -> None:
        super().__init__(scope, id)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=config.max_azs,
            nat_gateways=config.nat_gateways,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # VPC Flow Logs
        flow_log_group = logs.LogGroup(
            self,
            "FlowLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=(
                RemovalPolicy.DESTROY if config.removal_destroy else RemovalPolicy.RETAIN
            ),
        )

        self.vpc.add_flow_log(
            "FlowLog",
            destination=ec2.FlowLogDestination.to_cloud_watch_logs(flow_log_group),
            traffic_type=ec2.FlowLogTrafficType.REJECT,
        )

        # Security groups
        self.alb_sg = ec2.SecurityGroup(
            self, "AlbSg", vpc=self.vpc, description="ALB security group"
        )
        self.alb_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "HTTP from anywhere"
        )

        self.ecs_sg = ec2.SecurityGroup(
            self, "EcsSg", vpc=self.vpc, description="ECS tasks security group"
        )
        self.ecs_sg.add_ingress_rule(
            self.alb_sg, ec2.Port.tcp(8088), "Superset from ALB"
        )

        self.db_sg = ec2.SecurityGroup(
            self, "DbSg", vpc=self.vpc, description="Aurora security group"
        )
        self.db_sg.add_ingress_rule(
            self.ecs_sg, ec2.Port.tcp(5432), "PostgreSQL from ECS"
        )

        self.redis_sg = ec2.SecurityGroup(
            self, "RedisSg", vpc=self.vpc, description="Redis security group"
        )
        self.redis_sg.add_ingress_rule(
            self.ecs_sg, ec2.Port.tcp(6379), "Redis from ECS"
        )

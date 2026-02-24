from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct

from config.environments import EnvironmentConfig


class Database(Construct):
    """Aurora Serverless v2 PostgreSQL cluster for Superset metadata."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: EnvironmentConfig,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
    ) -> None:
        super().__init__(scope, id)

        removal = (
            RemovalPolicy.DESTROY if config.removal_destroy else RemovalPolicy.RETAIN
        )

        self.cluster = rds.DatabaseCluster(
            self,
            "AuroraCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4,
            ),
            serverless_v2_min_capacity=config.aurora_min_acu,
            serverless_v2_max_capacity=config.aurora_max_acu,
            writer=rds.ClusterInstance.serverless_v2("Writer"),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            security_groups=[security_group],
            default_database_name="superset",
            backup=rds.BackupProps(
                retention=Duration.days(config.aurora_backup_retention_days),
            ),
            storage_encrypted=True,
            removal_policy=removal,
            deletion_protection=not config.removal_destroy,
        )

    @property
    def secret(self) -> rds.DatabaseSecret:
        """The auto-generated master user credentials secret."""
        return self.cluster.secret

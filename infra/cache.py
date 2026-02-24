from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticache as elasticache
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from config.environments import EnvironmentConfig


class Cache(Construct):
    """ElastiCache Redis (node-based) for Superset caching and Celery broker.

    Uses node-based Redis instead of ElastiCache Serverless because
    Serverless is incompatible with Celery (CROSSSLOT errors from
    cluster-mode routing).
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: EnvironmentConfig,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        auth_token_secret: secretsmanager.ISecret,
    ) -> None:
        super().__init__(scope, id)

        self._auth_token_secret = auth_token_secret

        private_subnets = vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        subnet_group = elasticache.CfnSubnetGroup(
            self,
            "SubnetGroup",
            description="Redis subnet group",
            subnet_ids=private_subnets.subnet_ids,
        )

        # Resolve the auth token from Secrets Manager for Redis AUTH
        auth_token = auth_token_secret.secret_value.unsafe_unwrap()

        self.replication_group = elasticache.CfnReplicationGroup(
            self,
            "Redis",
            replication_group_description=f"Superset Redis {config.env_name}",
            engine="redis",
            engine_version="7.1",
            cache_node_type=config.redis_node_type,
            num_cache_clusters=1 + config.redis_num_replicas,
            automatic_failover_enabled=config.redis_num_replicas > 0,
            multi_az_enabled=config.redis_num_replicas > 0,
            cache_subnet_group_name=subnet_group.ref,
            security_group_ids=[security_group.security_group_id],
            transit_encryption_enabled=True,
            auth_token=auth_token,
            at_rest_encryption_enabled=True,
            port=6379,
        )

    @property
    def endpoint(self) -> str:
        """Primary endpoint address."""
        return self.replication_group.attr_primary_end_point_address

    @property
    def port(self) -> str:
        return self.replication_group.attr_primary_end_point_port

    @property
    def auth_token_secret(self) -> secretsmanager.ISecret:
        return self._auth_token_secret

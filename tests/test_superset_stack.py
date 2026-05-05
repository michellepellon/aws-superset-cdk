"""CDK assertion tests for the Superset stack."""

from dataclasses import replace

import aws_cdk as cdk
from aws_cdk import assertions

from config.environments import DEV, PROD
from stacks.superset_stack import SupersetStack


def _synth_stack(config):
    app = cdk.App()
    stack = SupersetStack(
        app,
        f"TestSuperset-{config.env_name}",
        config=config,
    )
    return assertions.Template.from_stack(stack)


class TestDevStack:
    def test_vpc_created(self):
        template = _synth_stack(DEV)
        template.resource_count_is("AWS::EC2::VPC", 1)

    def test_aurora_cluster_created(self):
        template = _synth_stack(DEV)
        template.resource_count_is("AWS::RDS::DBCluster", 1)
        template.has_resource_properties(
            "AWS::RDS::DBCluster",
            {
                "Engine": "aurora-postgresql",
                "DatabaseName": "superset",
                "StorageEncrypted": True,
                "ServerlessV2ScalingConfiguration": {
                    "MinCapacity": 0,
                    "MaxCapacity": 2,
                },
            },
        )

    def test_redis_replication_group_created(self):
        template = _synth_stack(DEV)
        template.resource_count_is("AWS::ElastiCache::ReplicationGroup", 1)
        template.has_resource_properties(
            "AWS::ElastiCache::ReplicationGroup",
            {
                "Engine": "redis",
                "CacheNodeType": "cache.t4g.micro",
                "TransitEncryptionEnabled": True,
                "AtRestEncryptionEnabled": True,
            },
        )

    def test_ecs_cluster_created(self):
        template = _synth_stack(DEV)
        template.resource_count_is("AWS::ECS::Cluster", 1)
        template.has_resource_properties(
            "AWS::ECS::Cluster",
            {"ClusterName": "superset-dev"},
        )

    def test_three_ecs_services_created(self):
        template = _synth_stack(DEV)
        template.resource_count_is("AWS::ECS::Service", 3)

    def test_alb_created(self):
        template = _synth_stack(DEV)
        template.resource_count_is(
            "AWS::ElasticLoadBalancingV2::LoadBalancer", 1
        )

    def test_secrets_created(self):
        template = _synth_stack(DEV)
        # 3 secrets: DB master password (auto by Aurora), Superset SECRET_KEY, Redis AUTH
        secrets = template.find_resources("AWS::SecretsManager::Secret")
        assert len(secrets) >= 2

    def test_cloudwatch_dashboard_created(self):
        template = _synth_stack(DEV)
        template.resource_count_is("AWS::CloudWatch::Dashboard", 1)

    def test_cloudwatch_alarms_created(self):
        template = _synth_stack(DEV)
        alarms = template.find_resources("AWS::CloudWatch::Alarm")
        assert len(alarms) >= 3


class TestProdStack:
    def test_aurora_min_capacity_not_zero(self):
        template = _synth_stack(PROD)
        template.has_resource_properties(
            "AWS::RDS::DBCluster",
            {
                "ServerlessV2ScalingConfiguration": {
                    "MinCapacity": 1.0,
                    "MaxCapacity": 16,
                },
                "DeletionProtection": True,
            },
        )

    def test_redis_node_type(self):
        template = _synth_stack(PROD)
        template.has_resource_properties(
            "AWS::ElastiCache::ReplicationGroup",
            {"CacheNodeType": "cache.t4g.medium"},
        )


class TestEntraAuth:
    """Tests for Microsoft Entra ID authentication."""

    ENTRA_DEV = replace(
        DEV,
        entra_tenant_id="00000000-0000-0000-0000-000000000000",
        entra_client_id="11111111-1111-1111-1111-111111111111",
    )

    def test_entra_secret_created_when_enabled(self):
        template = _synth_stack(self.ENTRA_DEV)
        # Should have 3 Secrets Manager secrets:
        # DB master password (Aurora), Superset SECRET_KEY, Redis AUTH, Entra client secret
        secrets = template.find_resources("AWS::SecretsManager::Secret")
        assert len(secrets) >= 3

    def test_no_entra_secret_when_disabled(self):
        template = _synth_stack(DEV)
        secrets = template.find_resources("AWS::SecretsManager::Secret")
        # Without Entra: DB master password, Superset SECRET_KEY, Redis AUTH
        # No Entra client secret
        entra_secrets = [
            k for k, v in secrets.items()
            if "Entra" in v.get("Properties", {}).get("Description", "")
        ]
        assert len(entra_secrets) == 0

    def test_three_ecs_services_still_created_with_entra(self):
        template = _synth_stack(self.ENTRA_DEV)
        template.resource_count_is("AWS::ECS::Service", 3)

#!/usr/bin/env python3
"""CDK app entry point for Apache Superset on AWS."""

from dataclasses import replace

import aws_cdk as cdk

from config.environments import ENVIRONMENTS
from stacks.superset_stack import SupersetStack

app = cdk.App()

env_name = app.node.try_get_context("env") or "dev"

if env_name not in ENVIRONMENTS:
    raise ValueError(
        f"Unknown environment '{env_name}'. "
        f"Valid options: {', '.join(ENVIRONMENTS.keys())}. "
        f"Usage: cdk deploy -c env=dev"
    )

config = ENVIRONMENTS[env_name]

# Microsoft Entra ID — override via CDK context:
#   cdk deploy -c env=dev -c entra_tenant_id=xxx -c entra_client_id=yyy
entra_overrides = {}
entra_tenant_id = app.node.try_get_context("entra_tenant_id")
entra_client_id = app.node.try_get_context("entra_client_id")
if entra_tenant_id:
    entra_overrides["entra_tenant_id"] = entra_tenant_id
if entra_client_id:
    entra_overrides["entra_client_id"] = entra_client_id

if entra_overrides:
    config = replace(config, **entra_overrides)

# NOTE: Do NOT pass `-c account=...` / `-c region=...` to `cdk deploy` or
# `cdk diff` when targeting an existing stack. The original deploy was
# env-agnostic (both context values absent), so the deployed CloudFormation
# template uses `Fn::GetAZs` for subnet `AvailabilityZone`. Passing concrete
# account+region triggers a CDK AZ lookup that emits literal AZ names
# ("us-east-2a") in the new template. Since `AvailabilityZone` is an
# immutable property, CloudFormation would REPLACE every subnet — which
# cascades into Aurora downtime, NAT gateway recreation, and a new ALB DNS
# (breaking the Cloudflare CNAME).
#
# To target a different AWS account or region, use AWS profile / env vars
# (`AWS_PROFILE`, `AWS_REGION`) — not CDK context.
SupersetStack(
    app,
    f"Superset-{config.env_name.capitalize()}",
    config=config,
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region"),
    ),
)

app.synth()

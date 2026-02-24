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

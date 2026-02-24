import aws_cdk as cdk
from aws_cdk import RemovalPolicy
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from config.environments import EnvironmentConfig


class Secrets(Construct):
    """Secrets Manager secrets for Superset."""

    def __init__(
        self, scope: Construct, id: str, *, config: EnvironmentConfig
    ) -> None:
        super().__init__(scope, id)

        removal = (
            RemovalPolicy.DESTROY if config.removal_destroy else RemovalPolicy.RETAIN
        )

        self.superset_secret_key = secretsmanager.Secret(
            self,
            "SupersetSecretKey",
            description="Superset SECRET_KEY for session signing",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True,
                password_length=64,
            ),
            removal_policy=removal,
        )

        self.redis_auth_token = secretsmanager.Secret(
            self,
            "RedisAuthToken",
            description="ElastiCache Redis AUTH token",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True,
                password_length=40,
            ),
            removal_policy=removal,
        )

        # Microsoft Entra ID client secret — created as a placeholder.
        # After deployment, update this secret's value in the AWS console
        # or CLI with the client secret from your Entra app registration.
        self.entra_client_secret: secretsmanager.Secret | None = None
        if config.entra_tenant_id and config.entra_client_id:
            self.entra_client_secret = secretsmanager.Secret(
                self,
                "EntraClientSecret",
                description=(
                    "Microsoft Entra ID OAuth client secret. "
                    "Update this value after deployment with the secret "
                    "from your Entra app registration."
                ),
                secret_string_value=cdk.SecretValue.unsafe_plain_text(
                    "REPLACE_ME_WITH_ENTRA_CLIENT_SECRET"
                ),
                removal_policy=removal,
            )

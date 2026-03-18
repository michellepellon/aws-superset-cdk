import os

from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from constructs import Construct

from config.environments import EnvironmentConfig


class DockerImage(Construct):
    """Builds and pushes the custom Superset Docker image via CDK assets.

    Uses DockerImageAsset so the image is built locally and pushed to ECR
    automatically during ``cdk deploy`` — no manual docker build/push needed.
    """

    def __init__(
        self, scope: Construct, id: str, *, config: EnvironmentConfig
    ) -> None:
        super().__init__(scope, id)

        docker_dir = os.path.join(os.path.dirname(__file__), "..", "docker")

        self.asset = ecr_assets.DockerImageAsset(
            self,
            "SupersetImage",
            directory=os.path.abspath(docker_dir),
            platform=ecr_assets.Platform.LINUX_ARM64,
        )

        self.container_image = ecs.ContainerImage.from_docker_image_asset(
            self.asset
        )

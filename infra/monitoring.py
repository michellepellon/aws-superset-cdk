from aws_cdk import Duration
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_rds as rds
from constructs import Construct

from config.environments import EnvironmentConfig


class Monitoring(Construct):
    """CloudWatch dashboard and alarms for Superset infrastructure."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: EnvironmentConfig,
        web_service: ecs.FargateService,
        worker_service: ecs.FargateService,
        beat_service: ecs.FargateService,
        load_balancer: elbv2.IApplicationLoadBalancer,
        db_cluster: rds.IDatabaseCluster,
    ) -> None:
        super().__init__(scope, id)

        dashboard = cloudwatch.Dashboard(
            self,
            "Dashboard",
            dashboard_name=f"superset-{config.env_name}",
        )

        # --- ECS Metrics ---
        web_cpu = web_service.metric_cpu_utilization()
        web_memory = web_service.metric_memory_utilization()
        worker_cpu = worker_service.metric_cpu_utilization()
        worker_memory = worker_service.metric_memory_utilization()

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="ECS CPU Utilization",
                left=[web_cpu, worker_cpu],
                width=12,
            ),
            cloudwatch.GraphWidget(
                title="ECS Memory Utilization",
                left=[web_memory, worker_memory],
                width=12,
            ),
        )

        # --- ALB Metrics ---
        alb_requests = load_balancer.metric_request_count()
        alb_5xx = load_balancer.metric_http_code_elb(
            code=elbv2.HttpCodeElb.ELB_5XX_COUNT
        )

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="ALB Request Count",
                left=[alb_requests],
                width=12,
            ),
            cloudwatch.GraphWidget(
                title="ALB 5xx Errors",
                left=[alb_5xx],
                width=12,
            ),
        )

        # --- Aurora Metrics ---
        db_connections = db_cluster.metric_database_connections()
        db_cpu = db_cluster.metric(
            "CPUUtilization",
            statistic="Average",
            period=Duration.minutes(5),
        )
        db_acu = db_cluster.metric(
            "ServerlessDatabaseCapacity",
            statistic="Average",
            period=Duration.minutes(5),
        )

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Aurora Connections",
                left=[db_connections],
                width=8,
            ),
            cloudwatch.GraphWidget(
                title="Aurora CPU",
                left=[db_cpu],
                width=8,
            ),
            cloudwatch.GraphWidget(
                title="Aurora ACU",
                left=[db_acu],
                width=8,
            ),
        )

        # --- Alarms ---
        web_cpu.create_alarm(
            self,
            "WebHighCpu",
            alarm_name=f"superset-{config.env_name}-web-high-cpu",
            threshold=85,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )

        worker_cpu.create_alarm(
            self,
            "WorkerHighCpu",
            alarm_name=f"superset-{config.env_name}-worker-high-cpu",
            threshold=85,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )

        alb_5xx.create_alarm(
            self,
            "Alb5xxAlarm",
            alarm_name=f"superset-{config.env_name}-alb-5xx",
            threshold=10,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )

        db_connections.create_alarm(
            self,
            "DbHighConnections",
            alarm_name=f"superset-{config.env_name}-db-high-connections",
            threshold=80,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )

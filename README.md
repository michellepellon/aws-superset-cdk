# Apache Superset on AWS

AWS CDK infrastructure for deploying Apache Superset on serverless AWS 
services with production-ready configurations for dev and prod environments.

## Architecture

This project deploys Apache Superset using:

- **Compute**: AWS Fargate (serverless containers) for web, worker, and beat services
- **Database**: Aurora Serverless v2 (PostgreSQL) for metadata storage
- **Cache**: ElastiCache Redis for caching and Celery task queue
- **Load Balancer**: Application Load Balancer with health checks
- **Networking**: VPC with public/private subnets across multiple AZs
- **Monitoring**: CloudWatch dashboards, alarms, and logs
- **Secrets**: AWS Secrets Manager for credentials and API keys
- **Container Registry**: ECR with automatic Docker image builds

## Features

- Multi-environment support (dev/prod) with distinct configurations
- Auto-scaling for web and worker services
- High availability with multi-AZ deployment
- Microsoft Entra ID (Azure AD) authentication support
- Spot instances for cost optimization on workers
- DuckDB/MotherDuck data source support
- Automatic database migrations on deployment
- CloudWatch monitoring and alerting

## Prerequisites

- AWS CLI configured with appropriate credentials
- AWS CDK CLI: `npm install -g aws-cdk`
- Python 3.14+
- Docker (for building container images)
- AWS account with sufficient permissions

## Quick Start

### 1. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Bootstrap CDK (first time only)

```bash
cdk bootstrap \
  -c account=YOUR_AWS_ACCOUNT_ID \
  -c region=us-east-1
```

### 3. Deploy

Deploy to dev environment:
```bash
cdk deploy -c env=dev -c account=YOUR_AWS_ACCOUNT_ID -c region=us-east-1
```

Deploy to prod environment:
```bash
cdk deploy -c env=prod -c account=YOUR_AWS_ACCOUNT_ID -c region=us-east-1
```

### 4. Access Superset

After deployment, the ALB DNS name will be in the stack outputs:
```bash
# Get the load balancer URL
aws cloudformation describe-stacks \
  --stack-name Superset-Dev \
  --query 'Stacks[0].Outputs[?OutputKey==`AlbDnsName`].OutputValue' \
  --output text
```

Default credentials for first login (if not using Entra ID):
- Create admin user via ECS task (see Management Tasks section)

## Configuration

### Environment Variables

Environment-specific configurations are defined in `config/environments.py`:

**Dev Environment** (`env=dev`):
- 1 NAT Gateway, 2 AZs
- Aurora: 0-2 ACUs
- Redis: cache.t4g.micro (no replicas)
- Web: 256 CPU, 512 MB (1-3 tasks)
- Worker: 512 CPU, 1024 MB (1-3 tasks, Spot)
- 7-day database backup retention

**Prod Environment** (`env=prod`):
- 2 NAT Gateways, 2 AZs
- Aurora: 2.0-32 ACUs
- Redis: cache.m7g.large (1 replica)
- Web: 2048 CPU, 4096 MB (4-16 tasks, 6 gunicorn workers each)
- Worker: 1024 CPU, 2048 MB (3-16 tasks, Spot)
- 30-day database backup retention
- Sized for ~1000 daily active users (dashboard/viewer-heavy, cache-dependent)

### Deployment notes

#### Do not pass `-c account=…` / `-c region=…` to `cdk deploy`

The first deploy of `Superset-Prod` was env-agnostic (no account/region context), so its CloudFormation template uses the `Fn::GetAZs` intrinsic for subnet `AvailabilityZone`. Passing concrete `-c account=…` and `-c region=…` on subsequent deploys triggers a CDK AZ lookup that emits *literal* AZ names (e.g. `"us-east-2a"`) instead. Because `AvailabilityZone` is an immutable property, CloudFormation would **replace every subnet** — which cascades into Aurora downtime, NAT gateway recreation, and a new ALB DNS (breaking the Cloudflare CNAME).

Use AWS profile / env vars (`AWS_PROFILE`, `AWS_REGION`) to set the deployment target instead. The standard prod deploy command is:

```bash
cdk deploy -c env=prod --require-approval never Superset-Prod
```

(Entra IDs come from `cdk.json` context, so they don't need to be on the CLI either.)

`cdk bootstrap` is the only command where `-c account=` / `-c region=` is appropriate — it operates on the CDK toolkit stack, not on the application stack template.

### Microsoft Entra ID Authentication

The Entra tenant ID and client ID for this deployment live in `cdk.json` under `context.entra_tenant_id` / `context.entra_client_id`, so every `cdk deploy` picks them up automatically. To override them on a single run (e.g. testing a different tenant), pass `-c entra_tenant_id=… -c entra_client_id=…` — CLI context wins over `cdk.json`.

To enable Entra in a fresh fork pointing at a different tenant, edit `cdk.json` and replace the two IDs (these are non-secret org/app identifiers; the actual client *secret* is in AWS Secrets Manager).

Configure the client secret in AWS Secrets Manager after deployment (secret name: `superset-{env}-entra-client-secret`).

#### Just-in-time provisioning

When Entra is enabled, new users are auto-provisioned in Superset on first login (`AUTH_USER_REGISTRATION = True` in `docker/superset_config.py`). The role assigned to new users is controlled by `entra_default_role` on `EnvironmentConfig`, which defaults to **`Analyst`** — a custom role created automatically by `docker/init_roles.py` during migrations.

The Analyst role is built by:
1. Copying the stock `Gamma` role's permissions
2. Removing all SQL Lab perms (no raw SQL writing)
3. Adding `all_database_access` and `all_datasource_access` so users automatically see every database an admin connects post-deploy

Net effect: an Analyst can view org dashboards, build their own personal charts/dashboards via the Explore UI on any connected database, and cannot edit dashboards they don't own (enforced by `DASHBOARD_RBAC`, which is enabled).

#### Post-deploy steps for Entra

After the first deploy with `entra_*` context:

1. **Rotate the placeholder client secret.** CDK creates `superset-{env}-entra-client-secret` with the literal value `REPLACE_ME_WITH_ENTRA_CLIENT_SECRET`. Update it with the secret from your Entra app registration:
   ```bash
   aws secretsmanager update-secret \
     --secret-id superset-dev-entra-client-secret \
     --secret-string 'YOUR_REAL_ENTRA_CLIENT_SECRET'
   ```
   Then force a new ECS deployment so containers pick up the new value:
   ```bash
   aws ecs update-service --cluster superset-dev --service superset-web-dev --force-new-deployment
   ```

2. **Configure the Entra app callback URL.** In your Azure portal, set the redirect URI on the app registration to:
   ```
   https://<your-public-hostname>/oauth-authorized/azure
   ```
   This must match the public hostname users hit (Cloudflare-fronted), not the raw ALB DNS.

3. **Connect at least one database.** Log in as Admin (`superset fab create-admin` via `aws ecs run-task`) and add a database connection through *Settings → Database Connections*. The Analyst role's `all_database_access` automatically picks it up — no per-role grant needed.

## Infrastructure Components

### Networking (`infra/networking.py`)
- VPC with public and private subnets
- NAT Gateways for private subnet internet access
- Security groups for ALB, ECS, RDS, and Redis

### Database (`infra/database.py`)
- Aurora Serverless v2 PostgreSQL cluster
- Automatic backups and point-in-time recovery
- Multi-AZ for high availability (prod)

### Cache (`infra/cache.py`)
- ElastiCache Redis cluster
- Used for Superset caching and Celery task queue
- Replication for HA (prod)

### Services
- **Web Service** (`infra/superset_web.py`): Gunicorn web server behind ALB
- **Worker Service** (`infra/superset_worker.py`): Celery workers for async tasks
- **Beat Service** (`infra/superset_beat.py`): Celery beat scheduler (singleton)

### Monitoring (`infra/monitoring.py`)
- CloudWatch dashboards for all services
- Alarms for service health, database connections, and cache
- Centralized logging

## Management Tasks

### Create Admin User

```bash
aws ecs run-task \
  --cluster superset-dev \
  --launch-type FARGATE \
  --task-definition superset-dev-web \
  --overrides '{
    "containerOverrides": [{
      "name": "web",
      "command": ["superset", "fab", "create-admin",
                  "--username", "admin",
                  "--firstname", "Admin",
                  "--lastname", "User",
                  "--email", "admin@example.com",
                  "--password", "YOUR_PASSWORD"]
    }]
  }' \
  --network-configuration '{
    "awsvpcConfiguration": {
      "subnets": ["subnet-xxx"],
      "securityGroups": ["sg-xxx"],
      "assignPublicIp": "ENABLED"
    }
  }'
```

### Run Database Migrations

Migrations run automatically on container startup via `docker/run_migrations.py`.

To run manually:
```bash
aws ecs run-task \
  --cluster superset-dev \
  --task-definition superset-dev-web \
  --overrides '{
    "containerOverrides": [{
      "name": "web",
      "command": ["python", "/app/run_migrations.py"]
    }]
  }'
```

## Development

### Project Structure

```
.
├── app.py                    # CDK app entry point
├── cdk.json                  # CDK configuration
├── requirements.txt          # Python dependencies
├── config/
│   └── environments.py       # Environment configurations (dev/prod)
├── stacks/
│   └── superset_stack.py    # Main CDK stack
├── infra/                    # Infrastructure constructs
│   ├── networking.py         # VPC, subnets, security groups
│   ├── database.py           # Aurora Serverless v2
│   ├── cache.py              # ElastiCache Redis
│   ├── ecs_cluster.py        # ECS cluster
│   ├── secrets.py            # Secrets Manager
│   ├── superset_web.py       # Web service + ALB
│   ├── superset_worker.py    # Celery worker service
│   ├── superset_beat.py      # Celery beat scheduler
│   ├── monitoring.py         # CloudWatch dashboards/alarms
│   └── container_registry.py # ECR + Docker build
├── docker/
│   ├── Dockerfile            # Superset container image
│   ├── superset_config.py    # Superset configuration
│   ├── docker-bootstrap.sh   # Container entrypoint
│   ├── run_migrations.py     # Database migration script
│   └── db_ready.py           # Database health check
└── tests/                    # CDK tests
```

### Useful CDK Commands

```bash
# Synthesize CloudFormation template
cdk synth -c env=dev

# Show differences with deployed stack
cdk diff -c env=dev -c account=XXX -c region=us-east-1

# Deploy with all required context
cdk deploy -c env=dev -c account=XXX -c region=us-east-1

# Destroy stack (careful!)
cdk destroy -c env=dev -c account=XXX -c region=us-east-1

# List all stacks
cdk list
```

### Customizing Superset

Modify `docker/superset_config.py` to customize Superset behavior:
- Feature flags
- Dashboard cache settings
- Query limits
- OIDC/OAuth configuration
- Row-level security

After modifying, redeploy to rebuild and push the Docker image:
```bash
cdk deploy -c env=dev
```

## Monitoring

Access CloudWatch dashboards via AWS Console:
- Navigate to CloudWatch > Dashboards
- Look for `Superset-{Env}-Dashboard`

Key metrics monitored:
- ECS service CPU/memory utilization
- ALB target health and request count
- Database connections and CPU
- Redis cache hits/misses
- Celery task queue length

## Cost Optimization

- Dev environment uses Spot instances for workers
- Aurora Serverless v2 scales to zero (dev) or 0.5 ACU (prod) when idle
- Single NAT Gateway in dev (2 in prod for HA)
- Smaller instance types in dev environment

## Troubleshooting

### Check service logs

```bash
# Web service logs
aws logs tail /aws/ecs/superset-dev-web --follow

# Worker service logs
aws logs tail /aws/ecs/superset-dev-worker --follow

# Beat service logs
aws logs tail /aws/ecs/superset-dev-beat --follow
```

### Check ECS task health

```bash
aws ecs describe-services \
  --cluster superset-dev \
  --services superset-dev-web
```

### Connect to database

Use the credentials from Secrets Manager (`superset-dev-db-credentials`) to connect via psql or pgAdmin.

## Security

- All secrets stored in AWS Secrets Manager
- Database in private subnets (no public access)
- Redis requires authentication
- Security groups restrict traffic to necessary ports
- ALB can be configured with SSL/TLS certificates
- Supports Entra ID for enterprise SSO

## License

This infrastructure code is provided as-is. Apache Superset is licensed under Apache License 2.0.

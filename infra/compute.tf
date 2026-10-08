resource "aws_ecr_repository" "lab" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # Laboratorio efímero: down elimina también las imágenes.
}

resource "aws_ecs_cluster" "lab" {
  name = local.name
}

resource "aws_cloudwatch_log_group" "agents" {
  name              = "/lab/${local.name}/agents"
  retention_in_days = 7
}

resource "aws_secretsmanager_secret" "anthropic" {
  name_prefix             = "${local.name}-anthropic-"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "anthropic" {
  secret_id                = aws_secretsmanager_secret.anthropic.id
  secret_string_wo         = var.anthropic_api_key
  secret_string_wo_version = var.secret_revision
}

resource "aws_iam_role" "execution" {
  name_prefix = "${local.name}-execution-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "execution" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
        Resource = aws_ecr_repository.lab.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.agents.arn}:*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = concat([aws_secretsmanager_secret.anthropic.arn],
          local.direct_hec_enabled ? [aws_secretsmanager_secret.splunk[0].arn] : [],
        local.datadog_enabled ? [aws_secretsmanager_secret.datadog[0].arn] : [])
      }
    ]
  })
}

# Los agentes no necesitan permisos AWS para ejecutar sus herramientas mock.
resource "aws_iam_role" "task" {
  name_prefix        = "${local.name}-task-"
  assume_role_policy = aws_iam_role.execution.assume_role_policy
}

resource "aws_ecs_task_definition" "lab" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name            = "agents"
    image           = "${aws_ecr_repository.lab.repository_url}:${var.image_tag}"
    essential       = true
    user            = "10001"
    linuxParameters = { initProcessEnabled = true }
    environment = concat([
      { name = "ANTHROPIC_MODEL", value = var.anthropic_model },
      { name = "PYTHONUNBUFFERED", value = "1" }
      ], local.direct_hec_enabled ? [
      { name = "SPLUNK_HEC_URL", value = var.splunk_hec_endpoint },
      { name = "SPLUNK_HEC_VERIFY_TLS", value = tostring(var.splunk_hec_verify_tls) }
      ] : [], local.datadog_enabled ? [
      { name = "OBSERVABILITY_PROVIDER", value = "datadog" },
      { name = "DD_SITE", value = var.datadog_site },
      { name = "DD_SERVICE", value = "agent-compliance-lab" },
      { name = "DD_ENV", value = "lab" },
      { name = "DD_APM_TRACING_ENABLED", value = "false" },
      { name = "DD_INSTRUMENTATION_TELEMETRY_ENABLED", value = "false" }
    ] : [])
    secrets = concat(
      [{ name = "ANTHROPIC_API_KEY", valueFrom = aws_secretsmanager_secret.anthropic.arn }],
      local.direct_hec_enabled ? [{ name = "SPLUNK_HEC_TOKEN", valueFrom = "${aws_secretsmanager_secret.splunk[0].arn}:hec_token::" }] : [],
      local.datadog_enabled ? [{ name = "DD_API_KEY", valueFrom = aws_secretsmanager_secret.datadog[0].arn }] : []
    )
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.agents.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "lab"
        mode                  = "blocking"
      }
    }
  }])

  depends_on = [aws_iam_role_policy.execution, aws_secretsmanager_secret_version.anthropic, aws_secretsmanager_secret_version.splunk, aws_secretsmanager_secret_version.datadog]
}

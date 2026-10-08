# Todos los recursos y consultas AWS están simulados; estas pruebas no despliegan.
mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-1a"] }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/test-role" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-lab-AbCdEf" }
  }
}

variables {
  aws_account_id    = "123456789012"
  anthropic_api_key = "SENTINEL_ANTHROPIC_NOT_FOR_STATE"
}

run "private_lab" {
  command = plan

  assert {
    condition     = length(aws_nat_gateway.lab) == 1 && output.lab.assign_public_ip == "DISABLED"
    error_message = "La configuración privada necesita NAT y tareas sin IP pública."
  }
}

run "public_lab_has_no_nat_charges" {
  command = plan
  variables {
    private_network = false
  }
  assert {
    condition     = length(aws_nat_gateway.lab) == 0 && length(aws_eip.nat) == 0 && length(aws_subnet.private) == 0
    error_message = "El modo público no debe dejar recursos NAT o EIP facturables."
  }
  assert {
    condition     = output.lab.assign_public_ip == "ENABLED"
    error_message = "La tarea pública necesita IP pública para acceder a Anthropic."
  }
}

run "datadog_secrets_and_environment" {
  command = apply
  variables {
    observability_provider = "datadog"
    datadog_site           = "datadoghq.eu"
    datadog_api_key        = "SENTINEL_DATADOG_NOT_FOR_STATE"
  }
  assert {
    condition     = length(aws_secretsmanager_secret.datadog) == 1
    error_message = "Datadog requiere su secreto en Secrets Manager."
  }
  assert {
    condition     = contains([for s in jsondecode(aws_ecs_task_definition.lab.container_definitions)[0].secrets : s.name], "DD_API_KEY")
    error_message = "ECS debe recibir DD_API_KEY desde Secrets Manager."
  }
  assert {
    condition     = !strcontains(aws_ecs_task_definition.lab.container_definitions, "SENTINEL_DATADOG_NOT_FOR_STATE") && aws_secretsmanager_secret_version.datadog[0].secret_string == null
    error_message = "La clave debe usar el atributo write-only."
  }
  assert {
    condition     = contains(jsondecode(aws_ecs_task_definition.lab.container_definitions)[0].environment, { name = "DD_SITE", value = "datadoghq.eu" })
    error_message = "ECS debe apuntar al sitio Datadog seleccionado."
  }
}

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
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::test-lab-audit" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-lab-AbCdEf" }
  }
  mock_resource "aws_kinesis_firehose_delivery_stream" {
    defaults = { arn = "arn:aws:firehose:us-east-1:123456789012:deliverystream/test-lab" }
  }
}

variables {
  aws_account_id    = "123456789012"
  anthropic_api_key = "SENTINEL_ANTHROPIC_NOT_FOR_STATE"
  splunk_hec_token  = "SENTINEL_SPLUNK_NOT_FOR_STATE"
}

run "private_lab_without_splunk" {
  command = plan

  assert {
    condition     = length(aws_nat_gateway.lab) == 1 && output.lab.assign_public_ip == "DISABLED"
    error_message = "La configuración privada necesita NAT y tareas sin IP pública."
  }
  assert {
    condition     = length(aws_kinesis_firehose_delivery_stream.splunk) == 0 && length(aws_secretsmanager_secret.splunk) == 0
    error_message = "Sin endpoint HEC no deben crearse Firehose ni un secreto Splunk."
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

run "splunk_pipeline_processes_cloudwatch_messages" {
  command = plan
  variables {
    splunk_hec_endpoint  = "https://hec.example.com:8088"
    splunk_delivery_mode = "firehose"
  }
  assert {
    condition     = length(aws_cloudwatch_log_subscription_filter.audit) == 1 && length(aws_s3_bucket.audit) == 1
    error_message = "HEC debe activar tanto la suscripción como el respaldo de auditoría."
  }
  assert {
    condition = toset([
      for processor in aws_kinesis_firehose_delivery_stream.splunk[0].splunk_configuration[0].processing_configuration[0].processors : processor.type
    ]) == toset(["Decompression", "CloudWatchLogProcessing"])
    error_message = "Splunk requiere descomprimir CloudWatch y extraer sus mensajes JSON."
  }
  assert {
    condition     = aws_kinesis_firehose_delivery_stream.splunk[0].splunk_configuration[0].hec_token == null
    error_message = "El token debe obtenerse desde Secrets Manager, no persistirse en Firehose/Terraform."
  }
}

run "trial_uses_direct_hec_with_correct_egress" {
  command = plan
  variables {
    splunk_hec_endpoint  = "https://inputs.example.splunkcloud.com:8088"
    splunk_delivery_mode = "hec"
  }
  assert {
    condition     = length(aws_secretsmanager_secret.splunk) == 1 && length(aws_kinesis_firehose_delivery_stream.splunk) == 0 && length(aws_s3_bucket.audit) == 0
    error_message = "El trial debe usar el secreto HEC sin crear Firehose ni su bucket."
  }
  assert {
    condition     = aws_vpc_security_group_egress_rule.hec[0].to_port == 8088
    error_message = "La red del contenedor debe permitir el puerto HTTPS configurado por el trial."
  }
}

run "reject_non_https_hec" {
  command = plan
  variables {
    splunk_hec_endpoint = "http://hec.example.com:8088"
  }
  expect_failures = [var.splunk_hec_endpoint]
}

run "datadog_secrets_and_environment" {
  command = apply
  variables {
    observability_provider = "datadog"
    datadog_site           = "datadoghq.eu"
    datadog_api_key        = "SENTINEL_DATADOG_NOT_FOR_STATE"
  }
  assert {
    condition     = length(aws_secretsmanager_secret.datadog) == 1 && length(aws_secretsmanager_secret.splunk) == 0
    error_message = "Datadog requiere su secreto, sin recursos Splunk."
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

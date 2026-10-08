output "lab" {
  description = "Configuración no secreta para el lanzador ./lab."
  value = {
    account_id             = var.aws_account_id
    observability_provider = var.observability_provider
    datadog_site           = var.datadog_site
    region                 = var.aws_region
    cluster_arn            = aws_ecs_cluster.lab.arn
    task_definition_arn    = aws_ecs_task_definition.lab.arn
    repository_url         = aws_ecr_repository.lab.repository_url
    log_group              = aws_cloudwatch_log_group.agents.name
    image_tag              = var.image_tag
    subnet_id              = var.private_network ? aws_subnet.private[0].id : aws_subnet.public.id
    security_group_id      = aws_security_group.task.id
    assign_public_ip       = var.private_network ? "DISABLED" : "ENABLED"
    splunk_enabled         = local.splunk_enabled
    splunk_delivery_mode   = var.splunk_delivery_mode
    backup_bucket          = local.firehose_enabled ? aws_s3_bucket.audit[0].id : null
  }
}

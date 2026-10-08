terraform {
  required_version = ">= 1.11.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  # Evita desplegar accidentalmente con el perfil de otra cuenta.
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "Terraform"
      Purpose   = "LLM-compliance-lab"
    }
  }
}

data "aws_partition" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name               = var.project_name
  partition          = data.aws_partition.current.partition
  splunk_enabled     = var.splunk_hec_endpoint != ""
  direct_hec_enabled = local.splunk_enabled && var.splunk_delivery_mode == "hec"
  firehose_enabled   = local.splunk_enabled && var.splunk_delivery_mode == "firehose"
  hec_port           = try(tonumber(regex(":([0-9]+)/?$", var.splunk_hec_endpoint)[0]), 443)
}

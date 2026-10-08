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
  name      = var.project_name
  partition = data.aws_partition.current.partition
}

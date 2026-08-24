output "config" {
  value       = local.config
  description = "Resolved config grouped by topic and project."
}

output "projects" {
  value       = local.projects
  description = "Projects included in the resolved config."
}

output "topics" {
  value       = local.topics
  description = "Resource topics included in the resolved config."
}

output "s3" {
  value       = lookup(local.config, "s3", {})
  description = "S3 resources grouped by project."
}

output "ecr" {
  value       = lookup(local.config, "ecr", {})
  description = "ECR resources grouped by project."
}

output "route53" {
  value       = lookup(local.config, "route53", {})
  description = "Route 53 resources grouped by project."
}

output "secrets" {
  value       = lookup(local.config, "secrets", {})
  description = "Secrets Manager resources grouped by project."
}

output "ssm" {
  value       = lookup(local.config, "ssm", {})
  description = "SSM parameters grouped by project."
}

output "deployment" {
  value       = lookup(local.config, "deployment", {})
  description = "Deployment runtime config grouped by project."
}

output "oidc" {
  value       = lookup(local.config, "oidc", {})
  description = "OIDC config grouped by project."
}

output "tags" {
  value       = lookup(local.config, "tags", {})
  description = "Tag config grouped by project."
}

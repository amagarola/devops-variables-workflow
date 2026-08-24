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

output "oidc" {
  value       = lookup(local.config, "oidc", {})
  description = "OIDC config grouped by project."
}

output "tags" {
  value       = lookup(local.config, "tags", {})
  description = "Tag config grouped by project."
}

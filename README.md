# devops-variables-workflow

Reusable configuration source for the `devops` Terraform workflows.

The repository has two entry points that read the same YAML files:

- A composite GitHub Action that writes a Terraform `.auto.tfvars.json` file.
- A Terraform module at the repository root that can be consumed directly from Terraform.

## Layout

```text
config/
  shared/
    oidc.yaml
    tags.yaml
  portfolio/
    s3.yaml
  ironmagarola/
    s3.yaml
scripts/
  resolve_config.py
main.tf
outputs.tf
variables.tf
action.yml
```

Each YAML file is grouped by project and resource topic:

```yaml
s3:
  backups:
    enabled: true
  gallery:
    enabled: true
```

That resolves to:

```json
{
  "s3": {
    "portfolio": {
      "backups": { "enabled": true },
      "gallery": { "enabled": true }
    }
  }
}
```

Terraform can then flatten each topic with `for_each` and create one resource per entry.

## GitHub Action

```yaml
- name: Resolve DevOps config
  uses: amagarola/devops-variables-workflow@main
  with:
    projects: |
      shared
      portfolio
      ironmagarola
    topics: |
      oidc
      tags
      s3
    output-file: terraform/generated/devops.auto.tfvars.json
```

The generated file contains:

```json
{
  "devops_config": {},
  "devops_config_projects": [],
  "devops_config_topics": []
}
```

## Terraform Module

```hcl
module "config" {
  source = "git::https://github.com/amagarola/devops-variables-workflow.git?ref=main"

  projects = ["shared", "portfolio", "ironmagarola"]
  topics   = ["oidc", "tags", "s3"]
}
```

The module exposes `config` plus convenience outputs such as `s3`, `oidc`, and `tags`.

## Public Repository Rule

This repo stores configuration, not secrets. Use names, ARNs, paths, or parameter references for secrets, and keep real values in AWS Secrets Manager, SSM Parameter Store, or GitHub Secrets.

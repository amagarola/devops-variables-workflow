#!/usr/bin/env python3
"""Resolve deployment defaults and optionally export them to GITHUB_ENV."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml


DEFAULTS = {
    "aws_region": "us-east-1",
    "aws_role_arn": "arn:aws:iam::471112989011:role/GitHub_Actions_Role",
    "ec2_instance_id": "i-0057b7fa819ecefa7",
}


def bool_input(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def write_env(name: str, value: str) -> None:
    env_path = os.environ.get("GITHUB_ENV")
    if env_path:
        with open(env_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    action_path = Path(os.environ.get("GITHUB_ACTION_PATH", ".")).resolve()
    config_root = Path(os.environ.get("INPUT_CONFIG_ROOT", "config"))
    if not config_root.is_absolute():
        config_root = (Path.cwd() / config_root).resolve()
        if not config_root.exists():
            config_root = (action_path / os.environ.get("INPUT_CONFIG_ROOT", "config")).resolve()

    project = os.environ["INPUT_DEPLOYMENT_PROJECT"]
    export_env = bool_input(os.environ.get("INPUT_EXPORT_ENV", "true"))

    defaults = dict(DEFAULTS)
    defaults.update(load_yaml(config_root / "default" / "env-properties.yaml").get("defaults", {}))
    defaults.update(load_yaml(config_root / project / "env-properties.yaml").get("defaults", {}))

    mapping = {
        "aws-region": ("AWS_REGION", defaults["aws_region"]),
        "aws-role-arn": ("AWS_ROLE_ARN", defaults["aws_role_arn"]),
        "ec2-instance-id": ("EC2_INSTANCE_ID", defaults["ec2_instance_id"]),
    }

    for output_name, (env_name, value) in mapping.items():
        value_text = str(value)
        write_output(output_name, value_text)
        if export_env:
            write_env(env_name, value_text)

    print(f"Resolved deployment defaults for {project}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

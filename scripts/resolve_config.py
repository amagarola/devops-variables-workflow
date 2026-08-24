#!/usr/bin/env python3
"""Resolve project/resource YAML files into Terraform tfvars JSON."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT_KEYS_ALLOWED = re.compile(r"^[a-z][a-z0-9_-]*$")
SECRET_VALUE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "private_key",
    "secret_key",
    "secret_access_key",
    "access_key",
    "api_key",
    "token",
    "client_secret",
}
SAFE_SECRET_REFERENCE_SUFFIXES = (
    "_name",
    "_names",
    "_arn",
    "_arns",
    "_id",
    "_ids",
    "_path",
    "_paths",
    "_parameter",
    "_parameters",
)


def parse_list(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n,]+", value or "") if part.strip()]


def bool_input(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def discover_projects(config_root: Path) -> list[str]:
    return sorted(path.name for path in config_root.iterdir() if path.is_dir() and path.name != "default")


def discover_topics(config_root: Path, projects: list[str]) -> list[str]:
    topics: set[str] = set()
    for project in projects:
        project_dir = config_root / project
        if not project_dir.is_dir():
            continue
        topics.update(path.stem for path in project_dir.glob("*.yaml"))
        topics.update(path.stem for path in project_dir.glob("*.yml"))
        if (project_dir / "env-properties.yaml").exists() or (project_dir / "env.properties").exists():
            topics.add("deployment")
    return sorted(topics)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the document root")
    return data


def validate_topic_name(topic: str) -> None:
    if not ROOT_KEYS_ALLOWED.match(topic):
        raise ValueError(f"Invalid topic name {topic!r}; use lowercase letters, numbers, '_' or '-'")


def validate_no_secret_values(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            next_path = f"{path}.{key}" if path else str(key)
            if key_text in SECRET_VALUE_KEYS and not key_text.endswith(SAFE_SECRET_REFERENCE_SUFFIXES):
                raise ValueError(
                    f"{next_path} looks like a raw secret value. Store only secret names, ARNs or paths in this repo."
                )
            validate_no_secret_values(nested, next_path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            validate_no_secret_values(nested, f"{path}[{index}]")


def write_github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> int:
    action_path = Path(os.environ.get("GITHUB_ACTION_PATH", ".")).resolve()
    config_root = Path(os.environ.get("INPUT_CONFIG_ROOT", "config"))
    if not config_root.is_absolute():
        config_root = (Path.cwd() / config_root).resolve()
        if not config_root.exists():
            config_root = (action_path / os.environ.get("INPUT_CONFIG_ROOT", "config")).resolve()

    output_file = Path(os.environ.get("INPUT_OUTPUT_FILE", "generated/devops.auto.tfvars.json"))
    if not output_file.is_absolute():
        output_file = (Path.cwd() / output_file).resolve()

    fail_on_missing = bool_input(os.environ.get("INPUT_FAIL_ON_MISSING", "false"))

    if not config_root.is_dir():
        raise FileNotFoundError(f"Config root does not exist: {config_root}")

    projects = parse_list(os.environ.get("INPUT_PROJECTS", ""))
    if not projects:
        projects = discover_projects(config_root)

    topics = parse_list(os.environ.get("INPUT_TOPICS", ""))
    if not topics:
        topics = discover_topics(config_root, projects)

    for topic in topics:
        validate_topic_name(topic)

    resolved: dict[str, dict[str, Any]] = {topic: {} for topic in topics}
    loaded_files: list[str] = []

    for project in projects:
        for topic in topics:
            candidates = [config_root / project / f"{topic}.yaml", config_root / project / f"{topic}.yml"]
            if topic == "deployment":
                candidates.append(config_root / project / "env-properties.yaml")
                candidates.append(config_root / project / "env.properties")
            file_path = next((candidate for candidate in candidates if candidate.exists()), None)
            if file_path is None:
                if fail_on_missing:
                    raise FileNotFoundError(f"Missing config for {project}/{topic}.yaml")
                continue

            if file_path.name in {"env.properties", "env-properties.yaml"}:
                document = {"deployment": {"app": {"env_properties": str(file_path.relative_to(config_root))}}}
            else:
                document = load_yaml(file_path)
            if topic not in document:
                raise ValueError(f"{file_path} must contain root key {topic!r}")

            topic_config = document[topic] or {}
            if not isinstance(topic_config, dict):
                raise ValueError(f"{file_path}:{topic} must be a mapping")

            validate_no_secret_values(topic_config, f"{project}.{topic}")
            resolved[topic][project] = topic_config
            loaded_files.append(str(file_path.relative_to(config_root)))

    tfvars = {
        "devops_config": resolved,
        "devops_config_projects": projects,
        "devops_config_topics": topics,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(tfvars, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    compact_config = json.dumps(resolved, separators=(",", ":"), sort_keys=True)
    write_github_output("tfvars-file", str(output_file))
    write_github_output("projects", ",".join(projects))
    write_github_output("topics", ",".join(topics))
    write_github_output("config-json", compact_config)

    print(f"Resolved {len(loaded_files)} config files from {config_root}")
    print(f"Wrote Terraform variables to {output_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

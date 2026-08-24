#!/usr/bin/env python3
"""Resolve deployment.yaml into a runtime .env file."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def write_github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def mask(value: str) -> None:
    if value:
        print(f"::add-mask::{value}")


def aws_json(*args: str) -> Any:
    result = subprocess.run(
        ["aws", *args, "--output", "json"],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def parse_csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def parse_bool_or_value(value: str) -> bool | str:
    lowered = value.strip().lower()
    if lowered in {"false", "no", "off", "0"}:
        return False
    if lowered in {"true", "yes", "on", "1"}:
        return True
    return value


def parse_ssm_paths(value: Any) -> list[Any]:
    paths: list[Any] = []
    for item in parse_csv(value):
        if item.endswith(":mask"):
            paths.append({"path": item.removesuffix(":mask"), "mask": True})
        elif ":prefix=" in item:
            path_name, prefix = item.split(":prefix=", 1)
            paths.append({"path": path_name, "env_prefix": prefix})
        else:
            paths.append(item)
    return paths


def load_env_properties(path: Path) -> dict[str, Any]:
    deployment: dict[str, Any] = {"app": {}}
    app = deployment["app"]
    env: dict[str, Any] = {}
    env_defaults: dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}: invalid properties line: {raw_line}")
        key, value = [part.strip() for part in line.split("=", 1)]

        if key in {"data_dir", "db_path"}:
            app[key] = parse_bool_or_value(value)
        elif key == "ssm":
            app["ssm"] = parse_ssm_paths(value)
        elif key in {"secrets", "optional_secrets", "workflow_env", "optional_workflow_env"}:
            app[key] = parse_csv(value)
        elif key.startswith("env_defaults."):
            env_defaults[key.removeprefix("env_defaults.")] = value
        elif key.startswith("secret."):
            env[key.removeprefix("secret.")] = {"secret": parse_csv(value)}
        elif key.startswith("value."):
            env[key.removeprefix("value.")] = {"value": value}
        else:
            raise ValueError(f"{path}: unsupported property: {key}")

    if env:
        app["env"] = env
    if env_defaults:
        app["env_defaults"] = env_defaults
    return {"deployment": deployment}


def load_env_properties_yaml(path: Path) -> dict[str, Any]:
    data = load_yaml(path)
    deployment: dict[str, Any] = {"app": {}}
    app = deployment["app"]
    env: dict[str, Any] = {}
    env_defaults: dict[str, str] = {}

    for key, value in data.items():
        if key in {"data_dir", "db_path"}:
            app[key] = value
        elif key in {"ssm", "secrets", "optional_secrets", "workflow_env", "optional_workflow_env"}:
            app[key] = parse_ssm_paths(value) if key == "ssm" else parse_csv(value)
        elif key == "env_defaults":
            if not isinstance(value, dict):
                raise ValueError(f"{path}: env_defaults must be a mapping")
            env_defaults.update({str(k): str(v) for k, v in value.items()})
        elif key == "secret":
            if not isinstance(value, dict):
                raise ValueError(f"{path}: secret must be a mapping")
            for env_name, keys in value.items():
                env[str(env_name)] = {"secret": parse_csv(keys)}
        elif key == "value":
            if not isinstance(value, dict):
                raise ValueError(f"{path}: value must be a mapping")
            for env_name, env_value_ in value.items():
                env[str(env_name)] = {"value": env_value_}
        else:
            raise ValueError(f"{path}: unsupported property: {key}")

    if env:
        app["env"] = env
    if env_defaults:
        app["env_defaults"] = env_defaults
    return {"deployment": deployment}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_project_config(config_root: Path, project: str) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for project_dir in [config_root / "default", config_root / project]:
        if not project_dir.is_dir():
            continue
        for path in sorted([*project_dir.glob("*.yaml"), *project_dir.glob("*.yml")]):
            if path.name == "deployment.yaml":
                continue
            config = deep_merge(config, load_yaml(path))
    return config


def config_value(config: dict[str, Any], path: str) -> Any:
    value: Any = config
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(f"Missing config path: {path}")
        value = value[part]
    return value


def template_vars(project: str) -> dict[str, str]:
    app = project.replace("_", "-")
    return {
        "app": app,
        "app_upper": app.upper().replace("-", "_"),
    }


def render_template(value: Any, project: str) -> str:
    return str(value).format(**template_vars(project))


def render_value(value: Any, project_config: dict[str, Any], project: str) -> str:
    text = str(value)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in template_vars(project):
            return template_vars(project)[key]
        return str(config_value(project_config, key))

    return re.sub(r"\{([^{}]+)\}", replace, text)


def env_name_to_path(name: str, project: str) -> str:
    app_prefix = template_vars(project)["app_upper"] + "_"
    normalized = name
    if normalized.startswith(app_prefix):
        normalized = normalized[len(app_prefix) :]
    return normalized.lower().replace("_", "-").replace("-", "/")


def ssm_path(project: str, name: str, scope: str = "config") -> str:
    if name.startswith("/"):
        return name
    return f"/{project}/production/{scope}/{name}"


def env_value(name: str, default: Any = None, required: bool = True) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        if default is not None:
            return str(default)
        if required:
            raise KeyError(f"Missing required environment variable: {name}")
        return ""
    return value


def secret_payload(secret_name: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if secret_name not in cache:
        response = aws_json(
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            secret_name,
            "--query",
            "SecretString",
        )
        if isinstance(response, str):
            cache[secret_name] = json.loads(response)
        elif isinstance(response, dict):
            cache[secret_name] = response
        else:
            raise ValueError(f"Unexpected secret payload for {secret_name}")
    return cache[secret_name]


def ssm_parameter(name: str, with_decryption: bool) -> str:
    args = [
        "ssm",
        "get-parameter",
        "--name",
        name,
        "--query",
        "Parameter.Value",
    ]
    if with_decryption:
        args.append("--with-decryption")
    response = aws_json(*args)
    return str(response)


def ssm_parameters_by_path(path: str, with_decryption: bool) -> list[dict[str, Any]]:
    args = [
        "ssm",
        "get-parameters-by-path",
        "--path",
        path,
        "--recursive",
    ]
    if with_decryption:
        args.append("--with-decryption")

    parameters: list[dict[str, Any]] = []
    next_token = ""
    while True:
        page_args = [*args]
        if next_token:
            page_args.extend(["--starting-token", next_token])
        response = aws_json(*page_args)
        parameters.extend(response.get("Parameters", []))
        next_token = response.get("NextToken", "")
        if not next_token:
            return parameters


def parameter_env_name(parameter_name: str, base_path: str, env_prefix: str = "") -> str:
    relative = parameter_name.removeprefix(base_path.rstrip("/") + "/")
    name = relative.upper().replace("-", "_").replace("/", "_")
    if env_prefix:
        name = f"{env_prefix}_{name}"
    return name


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def resolve_spec_value(spec: Any, project_config: dict[str, Any], project: str) -> str:
    if isinstance(spec, dict) and "config" in spec:
        return render_value(config_value(project_config, str(spec["config"])), project_config, project)
    return render_value(spec, project_config, project)


def resolve_entry(
    name: str,
    spec: Any,
    secret_names: dict[str, str],
    secret_cache: dict[str, dict[str, Any]],
    project_config: dict[str, Any],
    project: str,
) -> str:
    if not isinstance(spec, dict):
        return str(spec)

    required = bool(spec.get("required", True))
    default = spec.get("default")

    if "value" in spec:
        return resolve_spec_value(spec["value"], project_config, project)

    if "env" in spec:
        return env_value(str(spec["env"]), default=default, required=required)

    if "secret" in spec:
        secret_spec = spec["secret"]
        if secret_spec is True:
            secret_ref = "app"
            keys = [name]
        elif isinstance(secret_spec, str):
            secret_ref = "app"
            keys = [secret_spec]
        elif isinstance(secret_spec, dict):
            secret_ref = resolve_spec_value(secret_spec.get("name", "app"), project_config, project)
            if "keys" in secret_spec:
                keys = [str(item) for item in secret_spec["keys"]]
            else:
                keys = [str(secret_spec["key"])]
        else:
            raise ValueError(f"{name}: secret must be a string or mapping")

        payload = secret_payload(secret_names[secret_ref], secret_cache)
        for key in keys:
            if key in payload and payload[key] not in (None, ""):
                return str(payload[key])
        if default is not None:
            return str(default)
        if required:
            raise KeyError(f"{name}: missing keys {', '.join(keys)} in secret {secret_names[secret_ref]}")
        return ""

    if "ssm" in spec:
        ssm_spec = spec["ssm"]
        if ssm_spec is True:
            path = ssm_path(project, env_name_to_path(name, project))
            with_decryption = bool(spec.get("with_decryption", True))
        elif isinstance(ssm_spec, str):
            path = ssm_path(project, render_template(ssm_spec, project))
            with_decryption = bool(spec.get("with_decryption", True))
        elif isinstance(ssm_spec, dict):
            scope = str(ssm_spec.get("scope", "config"))
            path = ssm_path(project, resolve_spec_value(ssm_spec["name"], project_config, project), scope)
            with_decryption = bool(ssm_spec.get("with_decryption", True))
        else:
            raise ValueError(f"{name}: ssm must be a string or mapping")
        return ssm_parameter(path, with_decryption)

    raise ValueError(f"{name}: unsupported deployment env spec")


def main() -> int:
    action_path = Path(os.environ.get("GITHUB_ACTION_PATH", ".")).resolve()
    config_root = Path(os.environ.get("INPUT_CONFIG_ROOT", "config"))
    if not config_root.is_absolute():
        config_root = (Path.cwd() / config_root).resolve()
        if not config_root.exists():
            config_root = (action_path / os.environ.get("INPUT_CONFIG_ROOT", "config")).resolve()

    project = os.environ["INPUT_DEPLOYMENT_PROJECT"]
    deployment_name = os.environ.get("INPUT_DEPLOYMENT_NAME", "app")
    output_file = Path(os.environ.get("INPUT_RUNTIME_ENV_FILE", "generated/runtime.env"))
    if not output_file.is_absolute():
        output_file = (Path.cwd() / output_file).resolve()

    config_path = config_root / project / "deployment.yaml"
    properties_yaml_path = config_root / project / "env-properties.yaml"
    properties_path = config_root / project / "env.properties"
    default_path = config_root / "default" / "deployment.yaml"
    default_document = load_yaml(default_path) if default_path.exists() else {}
    if properties_yaml_path.exists():
        project_document = load_env_properties_yaml(properties_yaml_path)
    elif properties_path.exists():
        project_document = load_env_properties(properties_path)
    else:
        project_document = load_yaml(config_path)
    document = deep_merge(default_document, project_document)
    deployments = document.get("deployment") or {}
    if deployment_name not in deployments:
        raise KeyError(f"Missing deployment entry {deployment_name!r} in {config_path}")

    deployment = deployments[deployment_name] or {}
    if deployment.get("enabled", True) is False:
        raise ValueError(f"Deployment {project}/{deployment_name} is disabled")

    project_config = load_project_config(config_root, project)
    vars_ = template_vars(project)

    secret_names = {}
    default_app_secret = config_value(project_config, "secrets.app.name") if "secrets" in project_config else None
    if default_app_secret:
        secret_names["app"] = str(default_app_secret)
    secret_names.update({
        str(key): resolve_spec_value(value, project_config, project)
        for key, value in (deployment.get("secret_refs") or deployment.get("secret_names") or {}).items()
    })

    env_spec = {
        "AWS_REGION": {"value": "us-east-1"},
        "PORT": {"env": "APP_PORT", "default": "8000"},
        "ADMIN_USER": {"secret": True},
        "ADMIN_PASS": {"secret": True},
        "APP_VERSION": {"env": "APP_VERSION"},
        "APP_BUILD_SHA": {"env": "GITHUB_SHA"},
        "APP_BUILD_IMAGE": {"env": "IMAGE"},
    }
    env_spec.update(deployment.get("env") or {})

    for name in as_list(deployment.get("secrets")):
        env_spec[str(name)] = {"secret": True}
    for name in as_list(deployment.get("optional_secrets")):
        env_spec[str(name)] = {"secret": True, "required": False}
    for name in as_list(deployment.get("workflow_env")):
        env_spec[str(name)] = {"env": str(name)}
    for name in as_list(deployment.get("optional_workflow_env")):
        env_spec[str(name)] = {"env": str(name), "required": False}
    for name, default in (deployment.get("env_defaults") or {}).items():
        env_spec[str(name)] = {"env": str(name), "default": default}

    if not isinstance(env_spec, dict):
        raise ValueError(f"{config_path}: deployment.{deployment_name}.env must be a mapping")

    secret_cache: dict[str, dict[str, Any]] = {}
    lines: list[str] = []
    sensitive_values: list[str] = []

    data_dir = deployment.get("data_dir", f"/data/{vars_['app']}")
    if data_dir is not False:
        lines.append(f"{vars_['app_upper']}_DATA_DIR={render_template(data_dir, project)}")

    db_path = deployment.get("db_path", f"/data/{vars_['app']}/{vars_['app']}.sqlite3")
    if db_path is not False:
        lines.append(f"{vars_['app_upper']}_DB_PATH={render_template(db_path, project)}")

    generated_env = deployment.get("generated_env") or {}
    if not isinstance(generated_env, dict):
        raise ValueError(f"{config_path}: deployment.{deployment_name}.generated_env must be a mapping")

    for generated_name, generated_spec in generated_env.items():
        if generated_spec is None or generated_spec is False:
            continue
        if not isinstance(generated_spec, dict):
            raise ValueError(f"{generated_name}: generated_env entry must be a mapping")
        if generated_spec.get("enabled", True) is False:
            continue
        env_name = render_template(generated_spec["name"], project)
        value = resolve_spec_value(generated_spec["value"], project_config, project)
        lines.append(f"{env_name}={value}")

    ssm_paths = [*as_list(deployment.get("ssm")), *as_list(deployment.get("ssm_paths"))]
    for ssm_path_spec in ssm_paths:
        if isinstance(ssm_path_spec, str):
            base_path = ssm_path(project, ssm_path_spec)
            env_prefix = ""
            with_decryption = True
            mask_path = "/private/" in base_path
        elif isinstance(ssm_path_spec, dict):
            base_path = ssm_path(project, resolve_spec_value(ssm_path_spec["path"], project_config, project))
            env_prefix = str(ssm_path_spec.get("env_prefix", ""))
            with_decryption = bool(ssm_path_spec.get("with_decryption", True))
            mask_path = bool(ssm_path_spec.get("mask", "/private/" in base_path))
        else:
            raise ValueError("ssm_paths entries must be strings or mappings")

        for parameter in ssm_parameters_by_path(base_path, with_decryption):
            env_name = parameter_env_name(parameter["Name"], base_path, env_prefix)
            value = str(parameter["Value"])
            lines.append(f"{env_name}={value}")
            if mask_path:
                sensitive_values.append(value)

    for key in deployment.get("ssm_env", []):
        ssm_config = config_value(project_config, f"ssm.{key}")
        if not isinstance(ssm_config, dict):
            raise ValueError(f"ssm.{key} must be a mapping")
        if ssm_config.get("enabled", True) is False:
            continue
        env_name = str(ssm_config.get("env", str(key).upper()))
        path = resolve_spec_value(ssm_config["name"], project_config, project)
        value = ssm_parameter(path, bool(ssm_config.get("with_decryption", True)))
        lines.append(f"{env_name}={value}")
        if ssm_config.get("mask") or "/private/" in path:
            sensitive_values.append(value)

    for name, spec in env_spec.items():
        value = resolve_entry(str(name), spec, secret_names, secret_cache, project_config, project)
        lines.append(f"{name}={value}")
        if isinstance(spec, dict) and (spec.get("mask") or "secret" in spec or spec.get("sensitive")):
            sensitive_values.append(value)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    encoded = base64.b64encode(output_file.read_bytes()).decode("ascii")
    for value in sensitive_values:
        mask(value)
    mask(encoded)

    write_github_output("runtime-env-file", str(output_file))
    write_github_output("runtime-env-b64", encoded)

    print(f"Resolved deployment {project}/{deployment_name} to {output_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from fdroid_repo.models import AppConfig, AppDefaults, Config, RepoSettings


class ConfigError(ValueError):
    """Raised when apps.yml is invalid."""


def _as_str_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"'{field_name}' must be a list of strings")
    return tuple(value)


def _as_non_neg_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"'{field_name}' must be a non-negative integer")
    return value


def load_config(path: str | Path) -> Config:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a YAML mapping")

    repo_raw = raw.get("repo") or {}
    if not isinstance(repo_raw, dict):
        raise ConfigError("'repo' must be a mapping")
    repo_name = str(repo_raw.get("name") or "hddq's repo").strip()
    repo_desc = str(
        repo_raw.get("description")
        or "Central F-Droid repository for hddq's Android apps."
    ).strip()
    repo_url_raw = repo_raw.get("url")
    repo_url = str(repo_url_raw).strip().rstrip("/") if repo_url_raw else None
    repo_icon_raw = repo_raw.get("icon")
    repo_icon = str(repo_icon_raw).strip() if repo_icon_raw else None
    repo_settings = RepoSettings(
        name=repo_name, description=repo_desc, url=repo_url, icon=repo_icon
    )

    defaults_raw = raw.get("defaults") or {}
    if not isinstance(defaults_raw, dict):
        raise ConfigError("'defaults' must be a mapping")
    base_defaults = AppDefaults()
    defaults = AppDefaults(
        stable_count=_as_non_neg_int(
            defaults_raw.get("stable_count", base_defaults.stable_count),
            "defaults.stable_count",
        ),
        beta_count=_as_non_neg_int(
            defaults_raw.get("beta_count", base_defaults.beta_count),
            "defaults.beta_count",
        ),
        include_apk_patterns=_as_str_tuple(
            defaults_raw.get("include_apk_patterns", list(base_defaults.include_apk_patterns)),
            "defaults.include_apk_patterns",
        ),
        exclude_apk_patterns=_as_str_tuple(
            defaults_raw.get("exclude_apk_patterns", list(base_defaults.exclude_apk_patterns)),
            "defaults.exclude_apk_patterns",
        ),
        fastlane_path=str(
            defaults_raw.get("fastlane_path", base_defaults.fastlane_path)
        ).strip("/"),
        metadata_ref=str(defaults_raw.get("metadata_ref", base_defaults.metadata_ref)).strip(),
        tag_regex=str(defaults_raw.get("tag_regex", base_defaults.tag_regex)),
    )

    apps_raw = raw.get("apps")
    if not isinstance(apps_raw, list) or len(apps_raw) == 0:
        raise ConfigError("'apps' must be a non-empty list")

    apps: list[AppConfig] = []
    seen_repos: set[str] = set()
    for idx, entry in enumerate(apps_raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"apps[{idx}] must be a mapping")
        repo = entry.get("repo")
        if not isinstance(repo, str) or "/" not in repo or len(repo.split("/")) != 2:
            raise ConfigError(f"apps[{idx}].repo must be in 'owner/name' format")
        if repo in seen_repos:
            raise ConfigError(f"Duplicate app repo in config: {repo}")
        seen_repos.add(repo)

        app_id_raw = entry.get("app_id")
        app_id = str(app_id_raw).strip() if app_id_raw else None

        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"apps[{idx}].enabled must be a boolean")

        stable_count = _as_non_neg_int(
            entry.get("stable_count", defaults.stable_count),
            f"apps[{idx}].stable_count",
        )
        beta_count = _as_non_neg_int(
            entry.get("beta_count", defaults.beta_count),
            f"apps[{idx}].beta_count",
        )
        include_patterns = _as_str_tuple(
            entry.get("include_apk_patterns", list(defaults.include_apk_patterns)),
            f"apps[{idx}].include_apk_patterns",
        )
        exclude_patterns = _as_str_tuple(
            entry.get("exclude_apk_patterns", list(defaults.exclude_apk_patterns)),
            f"apps[{idx}].exclude_apk_patterns",
        )
        fastlane_path = str(entry.get("fastlane_path", defaults.fastlane_path)).strip("/")
        metadata_ref = str(entry.get("metadata_ref", defaults.metadata_ref)).strip()
        tag_regex = str(entry.get("tag_regex", defaults.tag_regex))

        metadata = entry.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ConfigError(f"apps[{idx}].metadata must be a mapping")

        apps.append(
            AppConfig(
                repo=repo,
                app_id=app_id,
                enabled=enabled,
                stable_count=stable_count,
                beta_count=beta_count,
                include_apk_patterns=include_patterns,
                exclude_apk_patterns=exclude_patterns,
                fastlane_path=fastlane_path,
                metadata_ref=metadata_ref,
                tag_regex=tag_regex,
                metadata=dict(metadata),
            )
        )

    return Config(repo=repo_settings, defaults=defaults, apps=tuple(apps))

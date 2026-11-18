from __future__ import annotations

from pathlib import Path

import pytest

from fdroid_repo.config import ConfigError, load_config


def test_load_repo_apps_yml() -> None:
    cfg = load_config(Path(__file__).resolve().parents[1] / "apps.yml")
    assert cfg.repo.name == "hddq's repo"
    assert cfg.repo.url == "https://fdroid.hddq.org/repo"
    assert cfg.defaults.stable_count == 3
    assert cfg.defaults.beta_count == 1
    assert len(cfg.apps) >= 3
    by_repo = {app.repo: app for app in cfg.apps}
    restoid = by_repo["hddq/restoid"]
    assert restoid.app_id == "io.github.hddq.restoid"
    assert restoid.stable_count == 3
    assert restoid.beta_count == 1

    bluehop = by_repo["hddq/bluehop"]
    assert bluehop.app_id == "org.hddq.bluehop"
    assert bluehop.metadata["Categories"] == ["Connectivity", "System"]
    assert bluehop.metadata["Changelog"] == "https://github.com/hddq/bluehop/releases"

    quicklaunch = by_repo["hddq/launcher3-quicklaunch"]
    assert quicklaunch.app_id == "org.hddq.launcher3.quicklaunch"
    assert quicklaunch.metadata["Categories"] == ["System"]
    assert (
        quicklaunch.metadata["Changelog"]
        == "https://github.com/hddq/launcher3-quicklaunch/releases"
    )


def test_per_app_overrides(tmp_path: Path) -> None:
    yml = tmp_path / "apps.yml"
    yml.write_text(
        """
repo:
  name: "hddq's repo"
defaults:
  stable_count: 3
  beta_count: 1
apps:
  - repo: "hddq/app1"
    stable_count: 5
    beta_count: 0
    exclude_apk_patterns: []
""",
        encoding="utf-8",
    )
    cfg = load_config(yml)
    assert cfg.apps[0].stable_count == 5
    assert cfg.apps[0].beta_count == 0
    assert cfg.apps[0].exclude_apk_patterns == ()


def test_invalid_config_raises(tmp_path: Path) -> None:
    yml = tmp_path / "apps.yml"
    yml.write_text("apps: []\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(yml)

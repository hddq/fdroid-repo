from __future__ import annotations

from fdroid_repo.models import AppConfig
from fdroid_repo.versioning import parse_semver, select_releases


def _make_app(stable_count: int = 3, beta_count: int = 1) -> AppConfig:
    return AppConfig(
        repo="hddq/restoid",
        app_id="io.github.hddq.restoid",
        enabled=True,
        stable_count=stable_count,
        beta_count=beta_count,
        include_apk_patterns=("*.apk",),
        exclude_apk_patterns=("*universal*",),
        fastlane_path="fastlane/metadata/android",
        metadata_ref="latest_release",
        tag_regex=r"^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$",
    )


def _gh_release(
    tag: str,
    *,
    prerelease: bool = False,
    draft: bool = False,
    assets: list[str] | None = None,
) -> dict:
    if assets is None:
        assets = [
            "app-arm64-v8a-release.apk",
            "app-x86_64-release.apk",
            "app-universal-release.apk",
            "SHA256SUMS.txt",
        ]
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "published_at": "2026-11-15T12:00:00Z",
        "html_url": f"https://github.com/hddq/restoid/releases/tag/{tag}",
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://example.com/{tag}/{name}",
                "size": 1000,
            }
            for name in assets
        ],
    }


def test_semver_ordering() -> None:
    v080 = parse_semver("0.8.0")
    v081 = parse_semver("0.8.1")
    v090_b1 = parse_semver("0.9.0-beta.1")
    v090_b2 = parse_semver("0.9.0-beta.2")
    v090 = parse_semver("0.9.0")
    assert v080 is not None
    assert v081 is not None
    assert v090_b1 is not None
    assert v090_b2 is not None
    assert v090 is not None
    assert v080 < v081 < v090_b1 < v090_b2 < v090


def test_select_releases_three_stable_plus_one_newer_beta() -> None:
    releases = [
        _gh_release("v0.9.0-beta.2", prerelease=True),
        _gh_release("v0.9.0-beta.1", prerelease=True),
        _gh_release("v0.8.1"),
        _gh_release("v0.8.0"),
        _gh_release("v0.7.0"),
        _gh_release("v0.6.6"),
        _gh_release("v0.8.0-beta.1", prerelease=True),  # older than latest stable -> excluded
        _gh_release("v0.9.1-beta.1", prerelease=True, draft=True),  # draft -> excluded
    ]
    selected = select_releases(_make_app(stable_count=3, beta_count=1), releases)

    assert [r.tag_name for r in selected.stable] == ["v0.8.1", "v0.8.0", "v0.7.0"]
    assert [r.tag_name for r in selected.betas] == ["v0.9.0-beta.2"]
    assert selected.latest_stable is not None
    assert selected.latest_stable.tag_name == "v0.8.1"
    # Universal APK and SHA256SUMS.txt are excluded
    assert [a.name for a in selected.stable[0].apk_assets] == [
        "app-arm64-v8a-release.apk",
        "app-x86_64-release.apk",
    ]


def test_select_releases_drops_beta_once_stable_catches_up() -> None:
    releases = [
        _gh_release("v0.9.0"),
        _gh_release("v0.9.0-beta.2", prerelease=True),
        _gh_release("v0.8.1"),
        _gh_release("v0.8.0"),
        _gh_release("v0.7.0"),
    ]
    selected = select_releases(_make_app(stable_count=3, beta_count=1), releases)
    assert [r.tag_name for r in selected.stable] == ["v0.9.0", "v0.8.1", "v0.8.0"]
    assert selected.betas == ()


def test_select_releases_configurable_counts_and_only_betas() -> None:
    releases = [
        _gh_release("v0.2.0-beta.2", prerelease=True),
        _gh_release("v0.2.0-beta.1", prerelease=True),
        _gh_release("v0.1.0-beta.1", prerelease=True),
    ]
    selected = select_releases(_make_app(stable_count=2, beta_count=2), releases)
    assert selected.stable == ()
    assert [r.tag_name for r in selected.betas] == ["v0.2.0-beta.2", "v0.2.0-beta.1"]


def test_select_releases_skips_release_without_matching_apks() -> None:
    releases = [
        _gh_release("v0.8.2", assets=["app-universal-release.apk"]),
        _gh_release("v0.8.1"),
    ]
    selected = select_releases(_make_app(stable_count=3, beta_count=1), releases)
    assert [r.tag_name for r in selected.stable] == ["v0.8.1"]
    assert any("v0.8.2" in w for w in selected.warnings)


def test_select_releases_supports_two_part_tags() -> None:
    app = AppConfig(
        repo="hddq/launcher3-quicklaunch",
        app_id="org.hddq.launcher3.quicklaunch",
        enabled=True,
        stable_count=3,
        beta_count=1,
        include_apk_patterns=("*.apk",),
        exclude_apk_patterns=("*universal*",),
        fastlane_path="fastlane/metadata/android",
        metadata_ref="latest_release",
        tag_regex=r"^v?(\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$",
    )
    releases = [
        _gh_release("v1.0", assets=["app-release.apk"]),
        _gh_release("v1.1", assets=["QuickLaunch-v1.1.apk"]),
    ]
    selected = select_releases(app, releases)
    assert [r.tag_name for r in selected.stable] == ["v1.1", "v1.0"]
    assert selected.latest_stable is not None
    assert str(selected.latest_stable.version) == "1.1.0"
    assert selected.warnings == ()

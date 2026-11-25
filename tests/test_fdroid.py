from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from fdroid_repo.fdroid import (
    _apk_repo_filename,
    _render_cloudflare_worker,
    build_fdroid_repo,
    get_keystore_sha256_fingerprint,
    inspect_apk,
)


def test_render_cloudflare_worker() -> None:
    worker_js = _render_cloudflare_worker(
        {
            "b.apk": "https://github.com/hddq/b/releases/download/v1.0.0/b.apk",
            "a.apk": "https://github.com/hddq/a/releases/download/v2.0.0/a.apk",
        }
    )
    assert '"a.apk": "https://github.com/hddq/a/releases/download/v2.0.0/a.apk"' in worker_js
    assert '"b.apk": "https://github.com/hddq/b/releases/download/v1.0.0/b.apk"' in worker_js
    assert 'decodeURIComponent(rawFilename)' in worker_js
    assert 'request.headers.get("If-Range")' in worker_js
    assert "upstream.status === 416" in worker_js
    assert 'redirect: "follow"' in worker_js
    assert "env.ASSETS.fetch(request)" in worker_js


def test_build_fdroid_repo_excludes_apks_and_writes_redirects(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from fdroid_repo.models import (
        ApkInfo,
        AppConfig,
        AppDefaults,
        Config,
        ParsedRelease,
        ReleaseAsset,
        RepoSettings,
        SelectedReleases,
        SemVer,
    )

    app = AppConfig(
        repo="hddq/bluehop",
        app_id="org.hddq.bluehop",
        enabled=True,
        stable_count=3,
        beta_count=1,
        include_apk_patterns=("*.apk",),
        exclude_apk_patterns=(),
        fastlane_path="",
        metadata_ref="latest_release",
        tag_regex=AppDefaults.tag_regex,
    )
    asset = ReleaseAsset(
        name="bluehop-arm64.apk",
        download_url="https://github.com/hddq/bluehop/releases/download/v0.1.0/bluehop-arm64.apk",
    )
    rel = ParsedRelease(
        tag_name="v0.1.0",
        version=SemVer(0, 1, 0),
        is_prerelease=False,
        published_at="2026-01-01T00:00:00Z",
        html_url="https://github.com/hddq/bluehop/releases/tag/v0.1.0",
        apk_assets=(asset,),
    )
    sel = SelectedReleases(app=app, stable=(rel,), betas=(), latest_stable=rel)
    cfg = Config(
        repo=RepoSettings(name="hddq's repo", description="Desc", url="https://fdroid.hddq.org/repo"),
        defaults=AppDefaults(),
        apps=(app,),
    )

    client = MagicMock()
    client.download_asset.side_effect = lambda _a, dest: (
        dest.parent.mkdir(parents=True, exist_ok=True),
        dest.write_bytes(b"fake-apk"),
    )

    def fake_fdroid_run(cmd: list[str], cwd: Path, check: bool) -> subprocess.CompletedProcess:
        assert cmd == ["fdroid", "update", "--create-metadata"]
        (cwd / "repo" / "index-v2.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with (
        patch("fdroid_repo.fdroid.get_keystore_sha256_fingerprint", return_value="AABBCC"),
        patch(
            "fdroid_repo.fdroid.inspect_apk",
            return_value=ApkInfo(
                package_name="org.hddq.bluehop",
                version_code=1,
                version_name="0.1.0",
                label="BlueHop",
            ),
        ),
        patch("subprocess.run", side_effect=fake_fdroid_run),
    ):
        output_dir = tmp_path / "dist"
        build_fdroid_repo(
            config=cfg,
            selections=[sel],
            client=client,
            work_dir=tmp_path / "work",
            output_dir=output_dir,
            repo_url="https://fdroid.hddq.org/repo",
            keystore_bytes=b"ks",
            keystore_pass="kspass",
            key_alias="fdroid",
            key_pass="kpass",
        )

    assert (output_dir / "repo" / "index-v2.json").is_file()
    assert list((output_dir / "repo").glob("*.apk")) == []
    assert not (output_dir / ".nojekyll").exists()
    assert not (output_dir / "_redirects").exists()
    not_found_html = (output_dir / "404.html").read_text(encoding="utf-8")
    assert "404 Not Found" in not_found_html
    assert 'href="/"' in not_found_html
    worker_js = (output_dir / "_worker.js").read_text(encoding="utf-8")
    assert (
        '"org.hddq.bluehop-bluehop-arm64-v0.1.0.apk": '
        '"https://github.com/hddq/bluehop/releases/download/v0.1.0/bluehop-arm64.apk"'
    ) in worker_js


def test_apk_repo_filename() -> None:
    assert (
        _apk_repo_filename("io.github.hddq.restoid", "app-arm64-v8a-release.apk", "v0.8.1")
        == "io.github.hddq.restoid-app-arm64-v8a-release-v0.8.1.apk"
    )
    assert (
        _apk_repo_filename(
            "io.github.hddq.restoid", "io.github.hddq.restoid-release.apk", "v0.8.1"
        )
        == "io.github.hddq.restoid-release-v0.8.1.apk"
    )


def test_inspect_apk_parses_aapt2_output(tmp_path: Path) -> None:
    fake_apk = tmp_path / "app.apk"
    fake_apk.write_bytes(b"")
    sample_stdout = (
        "package: name='io.github.hddq.restoid' versionCode='282' versionName='0.8.1'\n"
        "sdkVersion:'29'\n"
        "application-label:'Restoid'\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["aapt2"], returncode=0, stdout=sample_stdout, stderr=""
        )
        info = inspect_apk(fake_apk)
    assert info.package_name == "io.github.hddq.restoid"
    assert info.version_code == 282
    assert info.version_name == "0.8.1"
    assert info.label == "Restoid"


def test_get_keystore_fingerprint_parses_keytool_output(tmp_path: Path) -> None:
    ks = tmp_path / "test.jks"
    ks.write_bytes(b"")
    sample_stdout = (
        "Alias name: fdroid\n"
        "Certificate fingerprints:\n"
        "\t SHA1: AA:BB:CC\n"
        "\t SHA256: E6:62:9E:27:D6:CD:C8:7B:15:F6:8C:43:F7:D7:DF:89:"
        "04:AC:8E:FC:76:D8:7C:79:03:97:6C:3A:38:23:3A:C5\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["keytool"], returncode=0, stdout=sample_stdout, stderr=""
        )
        fp = get_keystore_sha256_fingerprint(ks, "pass", "fdroid")
    assert fp == "E6629E27D6CDC87B15F68C43F7D7DF8904AC8EFC76D87C7903976C3A38233AC5"


def test_landing_html_uses_repo_subpath() -> None:
    from fdroid_repo.html_index import render_landing_html
    from fdroid_repo.models import BuiltAppSummary

    html_out = render_landing_html(
        repo_name="hddq's repo",
        repo_description="Desc",
        repo_url="https://fdroid.hddq.org/repo",
        fingerprint="AABBCCDD",
        apps=[
            BuiltAppSummary(
                repo="hddq/bluehop",
                app_id="org.hddq.bluehop",
                display_name="BlueHop",
                summary="Summary",
                stable_tags=("v0.1.0",),
                beta_tags=(),
                current_version="0.1.0",
                current_version_code=1,
                apk_count=1,
                icon_relpath="org.hddq.bluehop/en-US/icon.png",
            )
        ],
    )
    assert 'href="repo/index.html"' in html_out
    assert 'src="repo/org.hddq.bluehop/en-US/icon.png"' in html_out
    assert "https://fdroid.hddq.org/repo" in html_out


def test_resolve_repo_url_uses_config_and_repo_fallback(monkeypatch) -> None:
    from fdroid_repo.cli import resolve_repo_url
    from fdroid_repo.models import AppDefaults, Config, RepoSettings

    cfg_explicit = Config(
        repo=RepoSettings(name="n", description="d", url="https://fdroid.hddq.org/repo/"),
        defaults=AppDefaults(),
        apps=(),
    )
    assert resolve_repo_url(cfg_explicit, None) == "https://fdroid.hddq.org/repo"

    cfg_default = Config(
        repo=RepoSettings(name="n", description="d", url=None),
        defaults=AppDefaults(),
        apps=(),
    )
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "hddq")
    monkeypatch.setenv("GITHUB_REPOSITORY", "hddq/fdroid-repo")
    assert resolve_repo_url(cfg_default, None) == "https://hddq.github.io/fdroid-repo/repo"

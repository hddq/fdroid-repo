from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from fdroid_repo.fdroid import _apk_repo_filename, get_keystore_sha256_fingerprint, inspect_apk


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

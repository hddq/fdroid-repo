from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from fdroid_repo.fastlane import extract_fastlane_summary, transform_fastlane_to_fdroid
from fdroid_repo.github_client import GitHubClient
from fdroid_repo.html_index import render_landing_html, render_not_found_html
from fdroid_repo.models import (
    ApkInfo,
    AppConfig,
    BuiltAppSummary,
    Config,
    SelectedReleases,
)

_PACKAGE_RE = re.compile(
    r"^package:\s+name='([^']+)'\s+versionCode='(\d+)'\s+versionName='([^']*)'"
)
_LABEL_RE = re.compile(r"^application-label(?:-en[^:]*)?:'([^']*)'")
_SHA256_RE = re.compile(r"SHA256:\s*([0-9A-Fa-f:]+)")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class FDroidBuildError(RuntimeError):
    """Raised when building or inspecting the F-Droid repo fails."""


def _prepare_repo_icon(icon_source: str, client: GitHubClient, dest_path: Path) -> None:
    if icon_source.startswith(("http://", "https://")):
        raw_bytes = client.download_url_bytes(icon_source)
    else:
        src_path = Path(icon_source)
        if not src_path.is_file():
            raise FDroidBuildError(f"Repository icon file not found: {src_path}")
        raw_bytes = src_path.read_bytes()

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_bytes.startswith(_PNG_SIGNATURE):
        dest_path.write_bytes(raw_bytes)
        return

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img.save(dest_path, format="PNG")
    except Exception as exc:
        raise FDroidBuildError(
            f"Failed to convert repository icon '{icon_source}' to PNG: {exc}"
        ) from exc


def inspect_apk(apk_path: Path, aapt2_bin: str = "aapt2") -> ApkInfo:
    try:
        proc = subprocess.run(
            [aapt2_bin, "dump", "badging", str(apk_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise FDroidBuildError(
            f"'{aapt2_bin}' not found in PATH. Run inside 'nix develop' or install aapt2."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise FDroidBuildError(
            f"aapt2 failed on {apk_path.name}: {exc.stderr.strip()}"
        ) from exc

    pkg_name = ""
    version_code: int | None = None
    version_name = ""
    label = ""

    for line in proc.stdout.splitlines():
        if not pkg_name:
            m = _PACKAGE_RE.match(line)
            if m:
                pkg_name = m.group(1)
                version_code = int(m.group(2))
                version_name = m.group(3)
                continue
        if not label:
            m_lbl = _LABEL_RE.match(line)
            if m_lbl:
                label = m_lbl.group(1)

    if not pkg_name or version_code is None:
        raise FDroidBuildError(f"Could not parse package metadata from {apk_path.name}")

    return ApkInfo(
        package_name=pkg_name,
        version_code=version_code,
        version_name=version_name,
        label=label,
    )


def get_keystore_sha256_fingerprint(
    keystore_path: Path,
    keystore_pass: str,
    key_alias: str,
    keytool_bin: str = "keytool",
) -> str:
    env = os.environ.copy()
    env["FDROID_KS_PASS"] = keystore_pass
    try:
        proc = subprocess.run(
            [
                keytool_bin,
                "-list",
                "-v",
                "-keystore",
                str(keystore_path),
                "-storepass:env",
                "FDROID_KS_PASS",
                "-alias",
                key_alias,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise FDroidBuildError(
            f"'{keytool_bin}' not found in PATH. Run inside 'nix develop' or install JDK."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise FDroidBuildError(
            f"keytool failed inspecting keystore alias '{key_alias}': {exc.stderr.strip()}"
        ) from exc

    m = _SHA256_RE.search(proc.stdout)
    if not m:
        raise FDroidBuildError("Could not extract SHA256 fingerprint from keytool output")
    return m.group(1).replace(":", "").upper()


def _parse_iso_timestamp(value: str) -> float | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _apk_repo_filename(app_id: str, asset_name: str, tag_name: str) -> str:
    stem = Path(asset_name).stem
    if asset_name.startswith(f"{app_id}-") or asset_name.startswith(f"{app_id}_"):
        return f"{stem}-{tag_name}.apk"
    return f"{app_id}-{stem}-{tag_name}.apk"


def _render_cloudflare_worker(apk_urls: dict[str, str]) -> str:
    mapping_json = json.dumps(dict(sorted(apk_urls.items())), indent=2)
    return (
        f"const APK_URLS = {mapping_json};\n\n"
        "export default {\n"
        "  async fetch(request, env) {\n"
        "    const url = new URL(request.url);\n"
        '    if (url.pathname.startsWith("/repo/")) {\n'
        '      const rawFilename = url.pathname.slice("/repo/".length);\n'
        "      let upstreamUrl = APK_URLS[rawFilename];\n"
        "      if (!upstreamUrl) {\n"
        "        try {\n"
        "          upstreamUrl = APK_URLS[decodeURIComponent(rawFilename)];\n"
        "        } catch {\n"
        "          upstreamUrl = undefined;\n"
        "        }\n"
        "      }\n"
        "      if (upstreamUrl) {\n"
        "        const upstreamHeaders = new Headers();\n"
        '        const range = request.headers.get("Range");\n'
        '        if (range) upstreamHeaders.set("Range", range);\n'
        '        const ifRange = request.headers.get("If-Range");\n'
        '        if (ifRange) upstreamHeaders.set("If-Range", ifRange);\n'
        "        const upstream = await fetch(upstreamUrl, {\n"
        '          method: request.method === "HEAD" ? "HEAD" : "GET",\n'
        "          headers: upstreamHeaders,\n"
        '          redirect: "follow",\n'
        "        });\n"
        "        if (upstream.status === 416) {\n"
        "          const headers = new Headers();\n"
        '          const contentRange = upstream.headers.get("Content-Range");\n'
        '          if (contentRange) headers.set("Content-Range", contentRange);\n'
        "          return new Response(null, { status: 416, headers });\n"
        "        }\n"
        "        if (!upstream.ok && upstream.status !== 206) {\n"
        "          return new Response(`Upstream error: ${upstream.status}`, { status: 502 });\n"
        "        }\n"
        "        const headers = new Headers();\n"
        '        headers.set("Content-Type", "application/vnd.android.package-archive");\n'
        "        for (const key of [\n"
        '          "Content-Length",\n'
        '          "Content-Range",\n'
        '          "Accept-Ranges",\n'
        '          "ETag",\n'
        '          "Last-Modified",\n'
        "        ]) {\n"
        "          const val = upstream.headers.get(key);\n"
        "          if (val) headers.set(key, val);\n"
        "        }\n"
        '        headers.set("Cache-Control", "public, max-age=3600");\n'
        '        return new Response(request.method === "HEAD" ? null : upstream.body, {\n'
        "          status: upstream.status,\n"
        "          headers,\n"
        "        });\n"
        "      }\n"
        "    }\n"
        "    return env.ASSETS.fetch(request);\n"
        "  },\n"
        "};\n"
    )


def _resolve_metadata_ref(
    app: AppConfig,
    selected: SelectedReleases,
    client: GitHubClient,
) -> str:
    if app.metadata_ref == "latest_release":
        if selected.all_selected:
            newest = max(selected.all_selected, key=lambda r: r.version)
            return newest.tag_name
        return client.get_default_branch(app.repo)
    if app.metadata_ref == "default_branch":
        return client.get_default_branch(app.repo)
    return app.metadata_ref


def build_fdroid_repo(
    config: Config,
    selections: list[SelectedReleases],
    client: GitHubClient,
    work_dir: Path,
    output_dir: Path,
    repo_url: str,
    keystore_bytes: bytes,
    keystore_pass: str,
    key_alias: str,
    key_pass: str,
    aapt2_bin: str = "aapt2",
    fdroid_bin: str = "fdroid",
    keytool_bin: str = "keytool",
) -> list[BuiltAppSummary]:
    fdroid_dir = work_dir / "fdroid"
    if fdroid_dir.exists():
        shutil.rmtree(fdroid_dir)
    repo_dir = fdroid_dir / "repo"
    metadata_dir = fdroid_dir / "metadata"
    repo_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    keystore_path = fdroid_dir / "keystore.jks"
    config_yml_path = fdroid_dir / "config.yml"

    summaries: list[BuiltAppSummary] = []
    apk_redirects: dict[str, str] = {}

    try:
        keystore_path.write_bytes(keystore_bytes)
        os.chmod(keystore_path, 0o600)

        fingerprint = get_keystore_sha256_fingerprint(
            keystore_path=keystore_path,
            keystore_pass=keystore_pass,
            key_alias=key_alias,
            keytool_bin=keytool_bin,
        )

        repo_icon_name: str | None = None
        if config.repo.icon:
            repo_icon_name = "icon.png"
            _prepare_repo_icon(config.repo.icon, client, repo_dir / "icons" / repo_icon_name)

        fdroid_config: dict[str, Any] = {
            "repo_url": repo_url,
            "repo_name": config.repo.name,
            "repo_description": config.repo.description,
            "keystore": "keystore.jks",
            "keystorepass": keystore_pass,
            "keypass": key_pass,
            "repo_keyalias": key_alias,
            "archive_older": 0,
        }
        if repo_icon_name:
            fdroid_config["repo_icon"] = repo_icon_name
        config_yml_path.write_text(
            yaml.safe_dump(fdroid_config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.chmod(config_yml_path, 0o600)

        dl_tmp = work_dir / "downloads"
        if dl_tmp.exists():
            shutil.rmtree(dl_tmp)
        dl_tmp.mkdir(parents=True, exist_ok=True)

        for sel in selections:
            app = sel.app
            if not sel.all_selected:
                continue

            app_dl_dir = dl_tmp / app.repo.replace("/", "__")
            app_dl_dir.mkdir(parents=True, exist_ok=True)

            # 1. Download APKs and inspect them with aapt2
            release_apk_infos: dict[str, list[ApkInfo]] = {}
            downloaded_files: list[tuple[str, Path, ApkInfo, str, str]] = []
            detected_app_id: str | None = app.app_id
            detected_label = ""

            for rel in sel.all_selected:
                infos: list[ApkInfo] = []
                for asset in rel.apk_assets:
                    tmp_apk = app_dl_dir / rel.tag_name / asset.name
                    client.download_asset(asset, tmp_apk)
                    info = inspect_apk(tmp_apk, aapt2_bin=aapt2_bin)
                    if detected_app_id is None:
                        detected_app_id = info.package_name
                    elif info.package_name != detected_app_id:
                        raise FDroidBuildError(
                            f"{app.repo} ({rel.tag_name}) APK {asset.name} has package "
                            f"'{info.package_name}', expected '{detected_app_id}'"
                        )
                    if not detected_label and info.label:
                        detected_label = info.label
                    infos.append(info)
                    downloaded_files.append(
                        (rel.tag_name, tmp_apk, info, asset.download_url, rel.published_at)
                    )
                release_apk_infos[rel.tag_name] = infos

            assert detected_app_id is not None
            app_id = detected_app_id

            for tag_name, tmp_apk, _info, download_url, published_at in downloaded_files:
                repo_apk_name = _apk_repo_filename(app_id, tmp_apk.name, tag_name)
                dest_apk = repo_dir / repo_apk_name
                shutil.move(str(tmp_apk), str(dest_apk))
                published_ts = _parse_iso_timestamp(published_at)
                if published_ts is not None:
                    os.utime(dest_apk, (published_ts, published_ts))
                apk_redirects[repo_apk_name] = download_url

            # 2. Fetch and transform Fastlane metadata
            app_meta_dir = metadata_dir / app_id
            fastlane_tmp = dl_tmp / f"fastlane-{app_id}"
            fastlane_summary = extract_fastlane_summary(app_meta_dir)
            if app.fastlane_path:
                meta_ref = _resolve_metadata_ref(app, sel, client)
                if client.download_repo_subpath(
                    app.repo, meta_ref, app.fastlane_path, fastlane_tmp
                ):
                    fastlane_summary = transform_fastlane_to_fdroid(fastlane_tmp, app_meta_dir)

            # 3. Determine CurrentVersion / CurrentVersionCode from newest stable release
            current_version: str | None = None
            current_version_code: int | None = None
            if sel.stable:
                latest_stable = sel.stable[0]
                stable_infos = release_apk_infos.get(latest_stable.tag_name, [])
                if stable_infos:
                    best = max(stable_infos, key=lambda i: i.version_code)
                    current_version = best.version_name or latest_stable.tag_name.lstrip("v")
                    current_version_code = best.version_code

            app_yml: dict[str, Any] = dict(app.metadata)
            if current_version is not None and current_version_code is not None:
                app_yml["CurrentVersion"] = str(current_version)
                app_yml["CurrentVersionCode"] = int(current_version_code)

            if app_yml:
                (metadata_dir / f"{app_id}.yml").write_text(
                    yaml.safe_dump(app_yml, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )

            icon_relpath: str | None = None
            if fastlane_summary.icon_path is not None:
                # fdroid update copies locale resources into repo/<app_id>/<locale>/...
                rel_icon = fastlane_summary.icon_path.relative_to(app_meta_dir)
                icon_relpath = f"{app_id}/{rel_icon.as_posix()}"

            summaries.append(
                BuiltAppSummary(
                    repo=app.repo,
                    app_id=app_id,
                    display_name=fastlane_summary.display_name or detected_label or app_id,
                    summary=fastlane_summary.summary,
                    stable_tags=tuple(r.tag_name for r in sel.stable),
                    beta_tags=tuple(r.tag_name for r in sel.betas),
                    current_version=current_version,
                    current_version_code=current_version_code,
                    apk_count=len(downloaded_files),
                    source_code=str(app.metadata.get("SourceCode") or f"https://github.com/{app.repo}"),
                    license_name=str(app.metadata.get("License") or "") or None,
                    icon_relpath=icon_relpath,
                )
            )

        # 4. Run fdroid update --create-metadata --use-date-from-apk
        try:
            subprocess.run(
                [fdroid_bin, "update", "--create-metadata", "--use-date-from-apk"],
                cwd=fdroid_dir,
                check=True,
            )
        except FileNotFoundError as exc:
            raise FDroidBuildError(
                f"'{fdroid_bin}' not found in PATH. Run inside 'nix develop' or install fdroid."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise FDroidBuildError(f"fdroid update failed with exit code {exc.returncode}") from exc

        # 5. Prepare clean publish directory (NO keystore, NO config.yml, NO .apk binaries!)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        out_fdroid_repo = output_dir / "repo"
        shutil.copytree(repo_dir, out_fdroid_repo, ignore=shutil.ignore_patterns("*.apk"))

        (output_dir / "_worker.js").write_text(
            _render_cloudflare_worker(apk_redirects),
            encoding="utf-8",
        )

        # Ensure icon_relpath exists in output repo
        verified_summaries: list[BuiltAppSummary] = []
        for s in summaries:
            icon_rel = s.icon_relpath
            if icon_rel and not (out_fdroid_repo / icon_rel).is_file():
                icon_rel = None
            verified_summaries.append(
                BuiltAppSummary(
                    repo=s.repo,
                    app_id=s.app_id,
                    display_name=s.display_name,
                    summary=s.summary,
                    stable_tags=s.stable_tags,
                    beta_tags=s.beta_tags,
                    current_version=s.current_version,
                    current_version_code=s.current_version_code,
                    apk_count=s.apk_count,
                    source_code=s.source_code,
                    license_name=s.license_name,
                    icon_relpath=icon_rel,
                )
            )

        repo_icon_relpath: str | None = None
        if repo_icon_name and (out_fdroid_repo / "icons" / repo_icon_name).is_file():
            repo_icon_relpath = f"icons/{repo_icon_name}"

        landing_html = render_landing_html(
            repo_name=config.repo.name,
            repo_description=config.repo.description,
            repo_url=repo_url,
            fingerprint=fingerprint,
            apps=verified_summaries,
            repo_icon_relpath=repo_icon_relpath,
        )
        (output_dir / "index.html").write_text(landing_html, encoding="utf-8")
        (output_dir / "404.html").write_text(
            render_not_found_html(config.repo.name),
            encoding="utf-8",
        )

        manifest = {
            "repo_name": config.repo.name,
            "repo_url": repo_url,
            "fingerprint": fingerprint,
            "apps": [
                {
                    "repo": s.repo,
                    "app_id": s.app_id,
                    "stable_tags": list(s.stable_tags),
                    "beta_tags": list(s.beta_tags),
                    "current_version": s.current_version,
                    "current_version_code": s.current_version_code,
                    "apk_count": s.apk_count,
                }
                for s in verified_summaries
            ],
        }
        (output_dir / "repo-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

        return verified_summaries
    finally:
        keystore_path.unlink(missing_ok=True)
        config_yml_path.unlink(missing_ok=True)

from __future__ import annotations

import fnmatch
import re
from typing import Any

from fdroid_repo.models import (
    AppConfig,
    ParsedRelease,
    ReleaseAsset,
    SelectedReleases,
    SemVer,
)

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def parse_semver(version_str: str) -> SemVer | None:
    match = _SEMVER_RE.match(version_str.strip())
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3))
    pre_raw = match.group(4)
    build = match.group(5) or ""

    prerelease: tuple[int | str, ...] = ()
    if pre_raw:
        parts: list[int | str] = []
        for ident in pre_raw.split("."):
            if ident.isdigit():
                parts.append(int(ident))
            else:
                parts.append(ident)
        prerelease = tuple(parts)

    return SemVer(
        major=major,
        minor=minor,
        patch=patch,
        prerelease=prerelease,
        build=build,
        raw=version_str.strip(),
    )


def parse_tag_version(tag_name: str, tag_regex: str) -> SemVer | None:
    match = re.match(tag_regex, tag_name.strip())
    if not match:
        return None
    version_part = match.group(1) if match.lastindex else match.group(0)
    return parse_semver(version_part)


def filter_apk_assets(
    assets: list[ReleaseAsset] | tuple[ReleaseAsset, ...],
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
) -> tuple[ReleaseAsset, ...]:
    matched: list[ReleaseAsset] = []
    for asset in assets:
        name = asset.name
        if include_patterns and not any(
            fnmatch.fnmatchcase(name, pat) for pat in include_patterns
        ):
            continue
        if exclude_patterns and any(
            fnmatch.fnmatchcase(name, pat) for pat in exclude_patterns
        ):
            continue
        matched.append(asset)
    return tuple(sorted(matched, key=lambda a: a.name))


def select_releases(
    app: AppConfig,
    raw_releases: list[dict[str, Any]],
) -> SelectedReleases:
    stable_candidates: list[ParsedRelease] = []
    beta_candidates: list[ParsedRelease] = []
    warnings: list[str] = []

    for rel in raw_releases:
        if rel.get("draft"):
            continue
        tag = str(rel.get("tag_name") or "").strip()
        if not tag:
            continue

        version = parse_tag_version(tag, app.tag_regex)
        if version is None:
            warnings.append(f"{app.repo}: skipped tag '{tag}' (does not match SemVer pattern)")
            continue

        raw_assets = rel.get("assets") or []
        assets = [
            ReleaseAsset(
                name=str(a.get("name") or ""),
                download_url=str(a.get("browser_download_url") or ""),
                size=int(a.get("size") or 0),
                digest=a.get("digest"),
            )
            for a in raw_assets
            if a.get("name") and a.get("browser_download_url")
        ]
        apk_assets = filter_apk_assets(
            assets,
            app.include_apk_patterns,
            app.exclude_apk_patterns,
        )
        if not apk_assets:
            warnings.append(f"{app.repo}: skipped release '{tag}' (no matching APK assets)")
            continue

        is_pre = bool(rel.get("prerelease")) or version.is_prerelease
        parsed = ParsedRelease(
            tag_name=tag,
            version=version,
            is_prerelease=is_pre,
            published_at=str(rel.get("published_at") or rel.get("created_at") or ""),
            html_url=str(rel.get("html_url") or ""),
            apk_assets=apk_assets,
        )
        if is_pre:
            beta_candidates.append(parsed)
        else:
            stable_candidates.append(parsed)

    stable_candidates.sort(key=lambda r: r.version, reverse=True)
    beta_candidates.sort(key=lambda r: r.version, reverse=True)

    selected_stable = tuple(stable_candidates[: app.stable_count])
    latest_stable = stable_candidates[0] if stable_candidates else None

    if app.beta_count > 0:
        if latest_stable is not None:
            newer_betas = [
                b for b in beta_candidates if b.version > latest_stable.version
            ]
        else:
            newer_betas = beta_candidates
        selected_betas = tuple(newer_betas[: app.beta_count])
    else:
        selected_betas = ()

    return SelectedReleases(
        app=app,
        stable=selected_stable,
        betas=selected_betas,
        latest_stable=latest_stable,
        warnings=tuple(warnings),
    )

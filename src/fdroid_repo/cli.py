from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from fdroid_repo.config import load_config
from fdroid_repo.fdroid import build_fdroid_repo
from fdroid_repo.github_client import GitHubClient
from fdroid_repo.models import BuiltAppSummary, Config, SelectedReleases
from fdroid_repo.versioning import select_releases


def resolve_repo_url(config: Config, explicit_url: str | None) -> str:
    if explicit_url:
        return explicit_url.rstrip("/")
    if config.repo.url:
        return config.repo.url.rstrip("/")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    full_repo = os.environ.get("GITHUB_REPOSITORY")
    if owner and full_repo and "/" in full_repo:
        repo_name = full_repo.split("/", 1)[1]
        return f"https://{owner}.github.io/{repo_name}/repo"
    return "https://hddq.github.io/fdroid-repo/repo"


def _resolve_keystore_bytes(keystore_path: str | None) -> bytes:
    if keystore_path:
        path = Path(keystore_path)
        if not path.is_file():
            raise SystemExit(f"Keystore file not found: {path}")
        return path.read_bytes()

    env_path = os.environ.get("FDROID_REPO_KEYSTORE_PATH")
    if env_path:
        path = Path(env_path)
        if not path.is_file():
            raise SystemExit(f"FDROID_REPO_KEYSTORE_PATH not found: {path}")
        return path.read_bytes()

    b64 = os.environ.get("FDROID_REPO_KEYSTORE_BASE64", "").strip()
    if b64:
        return base64.b64decode(b64)

    raise SystemExit(
        "Missing keystore: pass --keystore or set "
        "FDROID_REPO_KEYSTORE_BASE64 / FDROID_REPO_KEYSTORE_PATH"
    )


def _require_secret(cli_val: str | None, env_name: str, label: str) -> str:
    val = cli_val if cli_val is not None else os.environ.get(env_name, "")
    if not val:
        raise SystemExit(f"Missing {label}: pass CLI option or set {env_name}")
    return val


def _fetch_selections(
    config: Config,
    client: GitHubClient,
    app_filter: str | None = None,
) -> list[SelectedReleases]:
    selections: list[SelectedReleases] = []
    for app in config.apps:
        if not app.enabled:
            continue
        if app_filter and app_filter not in (app.repo, app.app_id or ""):
            continue
        raw_releases = client.list_releases(app.repo)
        selections.append(select_releases(app, raw_releases))
    if app_filter and not selections:
        raise SystemExit(f"No enabled app matched filter '{app_filter}'")
    return selections


def _format_check_markdown(selections: list[SelectedReleases]) -> str:
    lines = [
        "## F-Droid Release Check Summary",
        "",
        "| App Repo | App ID | Policy (Stable/Beta) "
        "| Selected Stable | Selected Beta | Latest Stable |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for sel in selections:
        stable_str = ", ".join(r.tag_name for r in sel.stable) or "_none_"
        beta_str = ", ".join(r.tag_name for r in sel.betas) or "_none_"
        latest_str = sel.latest_stable.tag_name if sel.latest_stable else "_none_"
        lines.append(
            f"| `{sel.app.repo}` | `{sel.app.app_id or 'auto'}` | "
            f"`{sel.app.stable_count}` / `{sel.app.beta_count}` | "
            f"{stable_str} | {beta_str} | {latest_str} |"
        )
    all_warnings = [w for sel in selections for w in sel.warnings]
    if all_warnings:
        lines.extend(["", "### Warnings", ""])
        lines.extend(f"- {w}" for w in all_warnings)
    return "\n".join(lines) + "\n"


def _format_build_markdown(
    repo_name: str,
    repo_url: str,
    summaries: list[BuiltAppSummary],
) -> str:
    lines = [
        f"## F-Droid Repository Built: {repo_name}",
        "",
        f"- **Repo URL**: `{repo_url}`",
        "",
        "| App ID | Source Repo | CurrentVersion | CurrentVersionCode | Stable | Beta | APKs |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in summaries:
        stable_str = ", ".join(s.stable_tags) or "_none_"
        beta_str = ", ".join(s.beta_tags) or "_none_"
        lines.append(
            f"| `{s.app_id}` | `{s.repo}` | "
            f"`{s.current_version or '-'}` | `{s.current_version_code or '-'}` | "
            f"{stable_str} | {beta_str} | {s.apk_count} |"
        )
    return "\n".join(lines) + "\n"


def _write_summary(summary_file: str | None, content: str) -> None:
    target = summary_file or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(content)


def cmd_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    client = GitHubClient()
    selections = _fetch_selections(config, client, app_filter=args.app)

    if args.json:
        payload = [
            {
                "repo": sel.app.repo,
                "app_id": sel.app.app_id,
                "stable_count_limit": sel.app.stable_count,
                "beta_count_limit": sel.app.beta_count,
                "latest_stable": sel.latest_stable.tag_name if sel.latest_stable else None,
                "selected_stable": [
                    {
                        "tag": r.tag_name,
                        "version": str(r.version),
                        "apks": [a.name for a in r.apk_assets],
                    }
                    for r in sel.stable
                ],
                "selected_betas": [
                    {
                        "tag": r.tag_name,
                        "version": str(r.version),
                        "apks": [a.name for a in r.apk_assets],
                    }
                    for r in sel.betas
                ],
                "warnings": list(sel.warnings),
            }
            for sel in selections
        ]
        print(json.dumps(payload, indent=2))
    else:
        for sel in selections:
            print(f"App: {sel.app.repo} (app_id={sel.app.app_id or 'auto'})")
            print(
                f"  Policy: up to {sel.app.stable_count} stable + "
                f"{sel.app.beta_count} newer beta"
            )
            print(f"  Latest stable: {sel.latest_stable.tag_name if sel.latest_stable else 'none'}")
            print("  Selected stable:")
            for r in sel.stable:
                apks = ", ".join(a.name for a in r.apk_assets)
                print(f"    - {r.tag_name} ({apks})")
            if not sel.stable:
                print("    - (none)")
            print("  Selected betas:")
            for r in sel.betas:
                apks = ", ".join(a.name for a in r.apk_assets)
                print(f"    - {r.tag_name} ({apks})")
            if not sel.betas:
                print("    - (none)")
            for w in sel.warnings:
                print(f"  [warn] {w}", file=sys.stderr)

    _write_summary(args.summary_file, _format_check_markdown(selections))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    client = GitHubClient()
    selections = _fetch_selections(config, client, app_filter=None)

    _write_summary(args.summary_file, _format_check_markdown(selections))

    repo_url = resolve_repo_url(config, args.repo_url)
    keystore_bytes = _resolve_keystore_bytes(args.keystore)
    keystore_pass = _require_secret(
        args.keystore_pass, "FDROID_REPO_KEYSTORE_PASSWORD", "keystore password"
    )
    key_alias = _require_secret(args.key_alias, "FDROID_REPO_KEY_ALIAS", "key alias")
    key_pass = _require_secret(args.key_pass, "FDROID_REPO_KEY_PASSWORD", "key password")

    summaries = build_fdroid_repo(
        config=config,
        selections=selections,
        client=client,
        work_dir=Path(args.work_dir),
        output_dir=Path(args.output),
        repo_url=repo_url,
        keystore_bytes=keystore_bytes,
        keystore_pass=keystore_pass,
        key_alias=key_alias,
        key_pass=key_pass,
    )

    _write_summary(
        args.summary_file,
        _format_build_markdown(config.repo.name, repo_url, summaries),
    )

    print(f"Built F-Droid repository '{config.repo.name}' at {args.output}")
    for s in summaries:
        print(
            f"  - {s.app_id}: stable={list(s.stable_tags)} beta={list(s.beta_tags)} "
            f"(CurrentVersion={s.current_version}, CurrentVersionCode={s.current_version_code}, "
            f"APKs={s.apk_count})"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdroid-repo",
        description="Manage and build hddq's central multi-app F-Droid repository",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="Check latest GitHub releases of configured apps")
    check_p.add_argument("--config", default="apps.yml", help="Path to apps.yml")
    check_p.add_argument("--app", default=None, help="Filter to a single app repo or app_id")
    check_p.add_argument("--json", action="store_true", help="Output JSON")
    check_p.add_argument(
        "--summary-file", default=None, help="Optional Markdown summary output file"
    )
    check_p.set_defaults(func=cmd_check)

    build_p = sub.add_parser("build", help="Download releases and build F-Droid repo output")
    build_p.add_argument("--config", default="apps.yml", help="Path to apps.yml")
    build_p.add_argument("--output", default="dist", help="Output publish directory")
    build_p.add_argument("--work-dir", default="work", help="Working directory")
    build_p.add_argument("--repo-url", default=None, help="Public F-Droid repo URL")
    build_p.add_argument("--keystore", default=None, help="Path to signing keystore (.jks)")
    build_p.add_argument("--keystore-pass", default=None, help="Keystore password")
    build_p.add_argument("--key-alias", default=None, help="Key alias")
    build_p.add_argument("--key-pass", default=None, help="Key password")
    build_p.add_argument(
        "--summary-file", default=None, help="Optional Markdown summary output file"
    )
    build_p.set_defaults(func=cmd_build)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import requests

from fdroid_repo.models import ReleaseAsset


class GitHubClientError(RuntimeError):
    """Raised when a GitHub API request fails."""


class GitHubClient:
    def __init__(self, token: str | None = None, api_base: str = "https://api.github.com") -> None:
        self.api_base = api_base.rstrip("/")
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "hddq-fdroid-repo/0.1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code >= 400:
            raise GitHubClientError(
                f"GitHub API error {resp.status_code} for {url}: {resp.text[:300]}"
            )
        return resp.json()

    def get_repo_info(self, repo: str) -> dict[str, Any]:
        return self._get_json(f"{self.api_base}/repos/{repo}")

    def get_default_branch(self, repo: str) -> str:
        info = self.get_repo_info(repo)
        branch = info.get("default_branch")
        if not branch:
            raise GitHubClientError(f"Could not determine default branch for {repo}")
        return str(branch)

    def list_releases(self, repo: str, max_pages: int = 3) -> list[dict[str, Any]]:
        releases: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            batch = self._get_json(
                f"{self.api_base}/repos/{repo}/releases",
                params={"per_page": 100, "page": page},
            )
            if not isinstance(batch, list):
                raise GitHubClientError(f"Unexpected releases payload for {repo}")
            releases.extend(batch)
            if len(batch) < 100:
                break
        return releases

    def download_url_bytes(self, url: str) -> bytes:
        resp = self.session.get(url, timeout=30)
        if resp.status_code >= 400:
            raise GitHubClientError(f"Failed to download {url} ({resp.status_code})")
        return resp.content

    def download_asset(self, asset: ReleaseAsset, dest_path: Path) -> Path:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session.get(asset.download_url, stream=True, timeout=120) as resp:
            if resp.status_code >= 400:
                raise GitHubClientError(
                    f"Failed to download {asset.name} ({resp.status_code}): {asset.download_url}"
                )
            hasher = hashlib.sha256()
            with dest_path.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        fh.write(chunk)
                        hasher.update(chunk)

        if asset.digest and asset.digest.startswith("sha256:"):
            expected = asset.digest.split(":", 1)[1].lower()
            actual = hasher.hexdigest().lower()
            if actual != expected:
                dest_path.unlink(missing_ok=True)
                raise GitHubClientError(
                    f"SHA256 mismatch for {asset.name}: expected {expected}, got {actual}"
                )

        return dest_path

    def download_repo_subpath(
        self, repo: str, ref: str, subpath: str, dest_dir: Path
    ) -> bool:
        """Download a subpath from a GitHub repo tarball at `ref` into `dest_dir`."""
        subpath_norm = subpath.strip("/")
        url = f"{self.api_base}/repos/{repo}/tarball/{ref}"
        resp = self.session.get(url, timeout=120)
        if resp.status_code >= 400:
            raise GitHubClientError(
                f"Failed to download tarball for {repo}@{ref} ({resp.status_code})"
            )

        extracted_any = False
        dest_root = dest_dir.resolve()
        dest_root.mkdir(parents=True, exist_ok=True)

        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                posix_parts = PurePosixPath(member.name).parts
                if len(posix_parts) < 2:
                    continue
                # Strip top-level GitHub tarball directory (e.g. owner-repo-sha/)
                rel_in_repo = PurePosixPath(*posix_parts[1:])
                rel_str = rel_in_repo.as_posix()
                prefix = f"{subpath_norm}/"
                if not rel_str.startswith(prefix):
                    continue
                rel_sub = rel_str[len(prefix) :]
                if not rel_sub:
                    continue

                target = (dest_root / rel_sub).resolve()
                if not target.is_relative_to(dest_root):
                    raise GitHubClientError(f"Unsafe path in tarball: {member.name}")

                target.parent.mkdir(parents=True, exist_ok=True)
                src_f = tf.extractfile(member)
                if src_f is None:
                    continue
                with src_f, target.open("wb") as out_f:
                    out_f.write(src_f.read())
                extracted_any = True

        return extracted_any

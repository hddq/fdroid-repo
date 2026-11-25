from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RepoSettings:
    name: str
    description: str
    url: str | None = None
    icon: str | None = None


@dataclass(frozen=True)
class AppDefaults:
    stable_count: int = 3
    beta_count: int = 1
    include_apk_patterns: tuple[str, ...] = ("*.apk",)
    exclude_apk_patterns: tuple[str, ...] = ("*universal*",)
    fastlane_path: str = "fastlane/metadata/android"
    metadata_ref: str = "latest_release"
    tag_regex: str = r"^v?(\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$"


@dataclass(frozen=True)
class AppConfig:
    repo: str
    app_id: str | None
    enabled: bool
    stable_count: int
    beta_count: int
    include_apk_patterns: tuple[str, ...]
    exclude_apk_patterns: tuple[str, ...]
    fastlane_path: str
    metadata_ref: str
    tag_regex: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    repo: RepoSettings
    defaults: AppDefaults
    apps: tuple[AppConfig, ...]


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] = ()
    build: str = ""
    raw: str = ""

    @property
    def is_prerelease(self) -> bool:
        return len(self.prerelease) > 0

    def _sort_key(self) -> tuple[Any, ...]:
        # SemVer 2.0.0 precedence:
        # 1. major, minor, patch numerically
        # 2. Normal version > pre-release version (is_stable flag: 1 > 0)
        # 3. Pre-release identifiers compared left-to-right:
        #    numeric < alphanumeric; numeric compared numerically; string lexicographically
        #    a larger set of pre-release fields has higher precedence if all preceding are equal
        pre_key = tuple(
            (0, part) if isinstance(part, int) else (1, part)
            for part in self.prerelease
        )
        return (
            self.major,
            self.minor,
            self.patch,
            1 if not self.is_prerelease else 0,
            pre_key,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key() <= other._sort_key()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key() > other._sort_key()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key() >= other._sort_key()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._sort_key() == other._sort_key()

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += "-" + ".".join(str(p) for p in self.prerelease)
        if self.build:
            base += f"+{self.build}"
        return base


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int = 0
    digest: str | None = None


@dataclass(frozen=True)
class ParsedRelease:
    tag_name: str
    version: SemVer
    is_prerelease: bool
    published_at: str
    html_url: str
    apk_assets: tuple[ReleaseAsset, ...]


@dataclass(frozen=True)
class SelectedReleases:
    app: AppConfig
    stable: tuple[ParsedRelease, ...]
    betas: tuple[ParsedRelease, ...]
    latest_stable: ParsedRelease | None
    warnings: tuple[str, ...] = ()

    @property
    def all_selected(self) -> tuple[ParsedRelease, ...]:
        return self.betas + self.stable


@dataclass(frozen=True)
class ApkInfo:
    package_name: str
    version_code: int
    version_name: str
    label: str = ""


@dataclass(frozen=True)
class BuiltAppSummary:
    repo: str
    app_id: str
    display_name: str
    summary: str
    stable_tags: tuple[str, ...]
    beta_tags: tuple[str, ...]
    current_version: str | None
    current_version_code: int | None
    apk_count: int
    source_code: str | None = None
    license_name: str | None = None
    icon_relpath: str | None = None

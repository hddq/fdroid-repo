from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppFastlaneSummary:
    display_name: str = ""
    summary: str = ""
    icon_path: Path | None = None


def transform_fastlane_to_fdroid(
    fastlane_dir: Path,
    fdroid_app_metadata_dir: Path,
) -> AppFastlaneSummary:
    """Convert Fastlane Android metadata layout to F-Droid metadata/<app_id>/ layout."""
    if not fastlane_dir.is_dir():
        return AppFastlaneSummary()

    if fdroid_app_metadata_dir.exists():
        shutil.rmtree(fdroid_app_metadata_dir)
    fdroid_app_metadata_dir.mkdir(parents=True, exist_ok=True)

    rename_map = {
        "full_description.txt": "description.txt",
        "short_description.txt": "summary.txt",
        "title.txt": "name.txt",
    }

    for entry in sorted(fastlane_dir.iterdir()):
        if not entry.is_dir():
            continue
        target_locale = fdroid_app_metadata_dir / entry.name
        target_locale.mkdir(parents=True, exist_ok=True)

        for item in entry.iterdir():
            if item.name == "images" and item.is_dir():
                for img_item in item.iterdir():
                    dest = target_locale / img_item.name
                    if img_item.is_dir():
                        shutil.copytree(img_item, dest, dirs_exist_ok=True)
                    elif img_item.is_file():
                        shutil.copy2(img_item, dest)
            elif item.is_dir():
                shutil.copytree(item, target_locale / item.name, dirs_exist_ok=True)
            elif item.is_file():
                dest_name = rename_map.get(item.name, item.name)
                shutil.copy2(item, target_locale / dest_name)

    return extract_fastlane_summary(fdroid_app_metadata_dir)


def extract_fastlane_summary(fdroid_app_metadata_dir: Path) -> AppFastlaneSummary:
    if not fdroid_app_metadata_dir.is_dir():
        return AppFastlaneSummary()

    locale_dirs = [p for p in sorted(fdroid_app_metadata_dir.iterdir()) if p.is_dir()]
    preferred_order = ["en-US", "en"]
    ordered: list[Path] = []
    for pref in preferred_order:
        match = fdroid_app_metadata_dir / pref
        if match in locale_dirs:
            ordered.append(match)
    for d in locale_dirs:
        if d not in ordered:
            ordered.append(d)

    display_name = ""
    summary = ""
    icon_path: Path | None = None

    for d in ordered:
        if not display_name and (d / "name.txt").is_file():
            display_name = (d / "name.txt").read_text(encoding="utf-8").strip()
        if not summary and (d / "summary.txt").is_file():
            summary = (d / "summary.txt").read_text(encoding="utf-8").strip()
        if icon_path is None and (d / "icon.png").is_file():
            icon_path = d / "icon.png"

    return AppFastlaneSummary(
        display_name=display_name,
        summary=summary,
        icon_path=icon_path,
    )

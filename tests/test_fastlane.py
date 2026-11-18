from __future__ import annotations

from pathlib import Path

from fdroid_repo.fastlane import transform_fastlane_to_fdroid


def test_transform_fastlane_to_fdroid(tmp_path: Path) -> None:
    src = tmp_path / "fastlane"
    en = src / "en-US"
    (en / "images" / "phoneScreenshots").mkdir(parents=True)
    (en / "changelogs").mkdir(parents=True)
    (en / "title.txt").write_text("Restoid\n", encoding="utf-8")
    (en / "short_description.txt").write_text("Backup tool\n", encoding="utf-8")
    (en / "full_description.txt").write_text("Full description\n", encoding="utf-8")
    (en / "images" / "icon.png").write_bytes(b"PNG")
    (en / "images" / "phoneScreenshots" / "1.png").write_bytes(b"SHOT1")
    (en / "changelogs" / "282.txt").write_text("* Bugfixes\n", encoding="utf-8")

    dest = tmp_path / "fdroid_meta"
    summary = transform_fastlane_to_fdroid(src, dest)

    assert (dest / "en-US" / "name.txt").read_text(encoding="utf-8") == "Restoid\n"
    assert (dest / "en-US" / "summary.txt").read_text(encoding="utf-8") == "Backup tool\n"
    assert (dest / "en-US" / "description.txt").read_text(encoding="utf-8") == "Full description\n"
    assert (dest / "en-US" / "icon.png").read_bytes() == b"PNG"
    assert (dest / "en-US" / "phoneScreenshots" / "1.png").read_bytes() == b"SHOT1"
    assert (dest / "en-US" / "changelogs" / "282.txt").read_text(encoding="utf-8") == "* Bugfixes\n"
    assert not (dest / "en-US" / "images").exists()

    assert summary.display_name == "Restoid"
    assert summary.summary == "Backup tool"
    assert summary.icon_path == dest / "en-US" / "icon.png"

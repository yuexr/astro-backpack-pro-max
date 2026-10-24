"""Zip the checked PAK for Vortex."""

import hashlib
import json
import zipfile

from settings import (
    ARCHIVE_NAME,
    AUTO_ARM_BLOCKER,
    MODEL_STYLE,
    OUT,
    PAK_NAME,
    PANEL_RETRACTION_FIX,
    ROOT,
    VERSION,
)

DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)
report = json.loads((OUT / "build-report.json").read_text())
assert report["version"] == VERSION
assert report["model_style"] == MODEL_STYLE
assert (
    len(report["offline_checks"])
    == 34 + 4 * int(PANEL_RETRACTION_FIX) + 4 * int(AUTO_ARM_BLOCKER)
    and report["printer_tooltip_verified"]
    and report["printer_preference_verified"]
)
assert report["panel_retraction_fix"] == PANEL_RETRACTION_FIX
assert report["auto_arm_verified"] == AUTO_ARM_BLOCKER
assert report["event_visuals_verified"] and report["build_options_verified"]
assert report["vehicle_visuals_verified"]
pak = OUT / PAK_NAME
assert hashlib.sha256(pak.read_bytes()).hexdigest() == report["pak_sha256"]
archive = DIST / ARCHIVE_NAME
assert not archive.exists(), (
    "ZIP already exists; use a new test version instead of overwriting it"
)
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(pak, pak.name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None and z.namelist() == [pak.name]
    assert z.read(pak.name) == pak.read_bytes()
release = {
    "version": VERSION,
    "model_style": MODEL_STYLE,
    "archive": str(archive),
    "bytes": archive.stat().st_size,
    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "pak_sha256": report["pak_sha256"],
    "installed": False,
    "gameplay_tested": False,
}
(OUT / "release-report.json").write_text(json.dumps(release, indent=2))
print(f"Ready: {archive}")

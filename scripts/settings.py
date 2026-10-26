"""Version and build settings."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.3.1"
DEVELOPMENT = "-test." in VERSION
GAME_BUILD = "1.45.1.0"
ITEM_SIZE_MULTIPLIER = 0.8
MAIN_SLOT_SCALE = 0.25 * ITEM_SIZE_MULTIPLIER
AUTO_ARM_BLOCKER = (
    os.environ.get("BPM_AUTO_ARM_BLOCKER", "1" if DEVELOPMENT else "0") == "1"
)
MODEL_STYLE = os.environ.get("BPM_MODEL", "base")
if MODEL_STYLE not in ("base", "luxe"):
    raise ValueError("BPM_MODEL must be base or luxe")


def model_paths(style):
    if style not in ("base", "luxe"):
        raise ValueError("choose base or luxe")
    filename = "backpack-pro-max" + ("-luxe" if style == "luxe" else "")
    folder = ROOT / "models"
    return folder / (filename + ".glb"), folder / (filename + ".json")


OUT = ROOT / "build" / VERSION
if MODEL_STYLE == "luxe":
    OUT = OUT / "luxe"
if AUTO_ARM_BLOCKER:
    OUT = OUT / "auto-arm"
# old saves still use this path
PKG = "/Game/Mods/CompactBackpack16/"
VARIANT = ("-Luxe" if MODEL_STYLE == "luxe" else "") + (
    "-AutoArm" if AUTO_ARM_BLOCKER else ""
)
PAK_NAME = f"000-BackpackProMax-{VERSION}_P.pak"
ARCHIVE_NAME = f"Backpack-Pro-Max{VARIANT}-{VERSION}-Vortex.zip"
PRINTER_ICON_SCALE = 0.85

# turn this off if vanilla fixes the catalog/mission log bugs
PANEL_RETRACTION_FIX = True

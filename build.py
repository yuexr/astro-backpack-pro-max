"""Build and package Backpack Pro Max."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    from game_assets import GUI, PAK, REPAK, UMODEL
    from settings import DEVELOPMENT, VERSION, model_paths

    parser = argparse.ArgumentParser(
        description=f"Build Backpack Pro Max {VERSION}.",
        epilog=(
            "Install requirements.txt first. Set BPM_REPAK, BPM_UASSETGUI and "
            "BPM_UMODEL, or put the tools in tools/. Set BPM_GAME_PAK if needed. "
            "Models go in models/. Blender is just for previewing. "
            "This won't install anything into the game."
        ),
    )
    parser.add_argument("command", choices=["prepare", "build", "verify", "package"])
    features = parser.add_mutually_exclusive_group()
    features.add_argument(
        "--auto-arm-blocker",
        action="store_true",
        help="Include the auto-arm blocker.",
    )
    features.add_argument(
        "--base",
        dest="auto_arm_blocker",
        action="store_false",
        help="Leave out the auto-arm blocker. Model choice is separate.",
    )
    parser.add_argument(
        "--model",
        choices=["base", "luxe"],
        default="base",
        help="Choose the model. Luxe needs its own GLB and JSON first.",
    )
    parser.set_defaults(auto_arm_blocker=DEVELOPMENT)
    args = parser.parse_args()
    missing = [path for path in model_paths(args.model) if not path.is_file()]
    if missing:
        parser.error(
            f"{args.model} model isn't ready; missing: " + ", ".join(map(str, missing))
        )
    os.environ["BPM_AUTO_ARM_BLOCKER"] = "1" if args.auto_arm_blocker else "0"
    os.environ["BPM_MODEL"] = args.model
    for label, path in [
        ("BPM_GAME_PAK", PAK),
        ("BPM_REPAK", REPAK),
        ("BPM_UASSETGUI", GUI),
        ("BPM_UMODEL", UMODEL),
    ]:
        if not path.is_file():
            parser.error(f"{label}: file not found: {path}")

    steps = {
        "prepare": ["prepare_assets.py"],
        "build": ["prepare_assets.py", "backpack.py", "verify.py"],
        "verify": ["verify.py"],
        "package": ["verify.py", "package.py"],
    }
    # one ZIP for testing; release combinations can wait
    if args.command == "build" and DEVELOPMENT:
        steps["build"].append("package.py")
    for script in steps[args.command]:
        subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True)


if __name__ == "__main__":
    main()

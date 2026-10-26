"""Extract the vanilla assets needed for the build."""

import hashlib
import json
import subprocess

from asset_io import HERE
from game_assets import UMODEL, extract


def prepare():
    # The game already supplies the materials; we only need the meshes and blueprints.
    for asset in [
        "Models/backpack_mk2/backpack_mk2",
        "Items/BackpackRail",
        "Character/AstroCorpse",
        "Items/Catalog/BackpackCatalog",
        "Items/Catalog/BackpackCatalog_Creative",
        "Components/Printhead_Backpack",
        "Components/PrintheadSelector",
        "ControlPanels/ModularControlPanel/PanelParts/ControlPanelButton_Round",
        "ControlPanels/ModularControlPanel/PanelParts/ControlPanelButtonBase",
        "Models/ControlPanels/control_panel_button_round_arrow",
    ]:
        extract("Astro/Content/" + asset)
    extract("Astro/Content/Models/backpack_mk2/backpack_mk2_Skeleton", as_json=False)
    meshes = [
        "Astro/Content/Models/backpack_mk2/backpack_mk2",
        "Astro/Content/Slots/Content/new/slot_t1b_i",
        "Astro/Content/Models/ControlPanels/control_panel_button_round_arrow",
    ]
    meshes.append(
        "Astro/Content/Animations/ControlPanels/ControlPanelMission/ControlPanelMissionBackpack_skinned"
    )
    for asset in meshes:
        source = extract(asset, as_json=False)
        subprocess.run(
            [
                str(UMODEL),
                "-export",
                "-gltf",
                "-noanim",
                "-notex",
                "-game=ue4.27",
                "-path=" + str(HERE / "vanilla"),
                "-out=" + str(HERE / "exports"),
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
    # Triangle indices are tied to this game mesh. Stop if it has changed.
    manifest = json.loads((HERE / "mesh-parts.json").read_text())
    mesh = HERE / "vanilla/Astro/Content/Models/backpack_mk2/backpack_mk2.uexp"
    assert (
        hashlib.sha256(mesh.read_bytes()).hexdigest() == manifest["mesh_uexp_sha256"]
    ), "Unsupported base-game mesh; expected Astroneer " + manifest["game_build"]


if __name__ == "__main__":
    prepare()

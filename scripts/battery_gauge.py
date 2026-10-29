"""Private ten-cell native gauge with wider divider components only."""

import copy

from asset_io import es, name, ps, xyz
from blueprint import Blueprint
from game_assets import extract
from settings import PKG

SOURCE = "Astro/Content/Components/Power_Bars/PowerBar_Ringed_10"
PARENT = "Astro/Content/Components/Power_Bars/PowerBar_Ringed"
LABEL = "BackpackPowerBar"


def gauge_asset(revision):
    document = copy.deepcopy(extract(SOURCE))
    replacements = {
        "PowerBar_Ringed_10_C": LABEL + "_C",
        "Default__PowerBar_Ringed_10_C": "Default__" + LABEL + "_C",
    }
    document["NameMap"] = [replacements.get(n, n) for n in document["NameMap"]]
    for export in document["Exports"]:
        export["ObjectName"] = replacements.get(
            export["ObjectName"], export["ObjectName"]
        )
    # Reuse a native vector property's serialization schema. The native
    # construction script still generates every ring and cell instance.
    parent = extract(PARENT)
    scale = copy.deepcopy(ps(es(parent)["Scene_GEN_VARIABLE"])["RelativeScale3D"])
    xy = revision["spacer_component_scale_xy"]
    xyz(scale).update(X=xy, Y=xy, Z=1.0)
    es(document)["Spacer Meshes_GEN_VARIABLE"]["Data"].append(scale)
    for value in ["RelativeScale3D", "Vector"]:
        name(document, value)
    return LABEL, document


def bind_gauge(document):
    editor = Blueprint(document)
    package = editor.imp(PKG + LABEL, kind="Package")
    cls = editor.imp(LABEL + "_C", package, "BlueprintGeneratedClass", "/Script/Engine")
    ps(es(document)["Power Bar_GEN_VARIABLE"])["ChildActorClass"]["Value"] = cls

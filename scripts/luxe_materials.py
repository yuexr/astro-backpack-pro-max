"""Fixed satin gold for luxe decorations."""

import copy

from asset_io import ps
from game_assets import extract
from settings import MODEL_STYLE, PKG

SOURCE = "Astro/Content/Materials/modules/module_gold_01"
SAMPLES = {
    "LuxeGoldSatin": {"metal": 0.4, "roughness": 1.05, "colour": (0.95, 0.64, 0.20)},
    "LuxeGoldStars": {"metal": 0.4, "roughness": 1.0, "colour": (0.95, 0.64, 0.20)},
    "LuxeGoldDiamonds": {"metal": 0.4, "roughness": 0.6, "colour": (0.95, 0.64, 0.20)},
}


def members(entry):
    return {p["Name"]: p for p in entry["Value"]}


def parameter(entry):
    return members(members(entry)["ParameterInfo"])["Name"]["Value"]


def assets():
    if MODEL_STYLE != "luxe":
        return []
    original = extract(SOURCE)
    result = []
    for label, values in SAMPLES.items():
        document = copy.deepcopy(original)
        document["Exports"][0]["ObjectName"] = label
        document["NameMap"] = [
            PKG + label
            if n == "/Game/Materials/modules/module_gold_01"
            else label
            if n == "module_gold_01"
            else n
            for n in document["NameMap"]
        ]
        fields = ps(document["Exports"][0])
        for entry in fields["ScalarParameterValues"]["Value"]:
            value = members(entry)["ParameterValue"]
            if parameter(entry) == "Metalness":
                value["Value"] = values["metal"]
            elif parameter(entry) == "Roughness Multiplier":
                value["Value"] = values["roughness"]
        tint = next(
            e
            for e in fields["VectorParameterValues"]["Value"]
            if parameter(e) == "Color Tint"
        )
        colour = members(tint)["ParameterValue"]["Value"][0]["Value"]
        colour.update(dict(zip("RGB", values["colour"])))
        result.append((label, document))
    return result


def verify(cooked):
    if MODEL_STYLE != "luxe":
        return
    original = extract(SOURCE)
    for label, values in SAMPLES.items():
        document = cooked[label]
        fields = ps(document["Exports"][0])
        scalars = {
            parameter(e): float(members(e)["ParameterValue"]["Value"])
            for e in fields["ScalarParameterValues"]["Value"]
        }
        assert abs(scalars["Metalness"] - values["metal"]) < 1e-6
        assert abs(scalars["Roughness Multiplier"] - values["roughness"]) < 1e-6
        tint = next(
            e
            for e in fields["VectorParameterValues"]["Value"]
            if parameter(e) == "Color Tint"
        )
        colour = members(tint)["ParameterValue"]["Value"][0]["Value"]
        assert all(
            abs(float(colour[k]) - v) < 1e-6 for k, v in zip("RGB", values["colour"])
        )
        assert document["Imports"] == original["Imports"]
        assert fields["Parent"] == ps(original["Exports"][0])["Parent"]

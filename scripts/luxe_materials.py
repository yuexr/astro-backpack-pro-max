"""Fixed satin gold for luxe decorations."""

import copy

from asset_io import ps
from game_assets import extract
from settings import LUXE_GLOW, MODEL_STYLE, PKG

SOURCE = "Astro/Content/Materials/modules/module_gold_01"
SAMPLES = {
    "LuxeGoldSatin": {
        "metal": 0.4,
        "roughness": 1.05,
        "colour": (0.9473065367331999, 0.5906188409193369, 0.19120168274079138),
    },
    "LuxeGoldStars": {
        "metal": 0.4,
        "roughness": 1.0,
        "colour": (0.9473065367331999, 0.5906188409193369, 0.19120168274079138),
    },
    "LuxeGoldDiamonds": {
        "metal": 0.4,
        "roughness": 0.6,
        "colour": (0.9473065367331999, 0.5906188409193369, 0.19120168274079138),
    },
}
if LUXE_GLOW:
    SAMPLES.update(
        {
            "LuxeGoldOrnaments": {
                "metal": 0.68,
                "roughness": 0.6,
                "colour": SAMPLES["LuxeGoldStars"]["colour"],
                "glow": 0.05,
            },
            "LuxeGoldMorseGlow": {
                "metal": 0.68,
                "roughness": 0.6,
                "colour": SAMPLES["LuxeGoldStars"]["colour"],
                "glow": 0.075,
            },
            "LowerBatteryGlow": {
                "metal": 0.0,
                "roughness": 1.4,
                "colour": (
                    0.00010718736234124402,
                    0.18014428915439032,
                    0.4761772653974402,
                ),
                "glow": 1.1,
            },
        }
    )


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
        if values.get("glow"):
            # Use coloured emission alone; preserve the original diffuse material.
            emission = copy.deepcopy(tint)
            members(members(emission)["ParameterInfo"])["Name"]["Value"] = (
                "Emissive Tint"
            )
            members(emission)["ExpressionGUID"]["Value"][0]["Value"] = (
                "{4409C9A7-4E4F-05DB-A725-34A97134DCB3}"
            )
            rgba = members(emission)["ParameterValue"]["Value"][0]["Value"]
            rgba.update(
                dict(zip("RGB", [v * values["glow"] for v in values["colour"]]))
            )
            fields["VectorParameterValues"]["Value"].append(emission)
            # Retain the parent's black Emissive Map. A white map adds a white
            # contribution in this shader and washes out the coloured emission.
            if "Emissive Tint" not in document["NameMap"]:
                document["NameMap"].append("Emissive Tint")
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

        if values.get("glow"):
            emission = next(
                e
                for e in fields["VectorParameterValues"]["Value"]
                if parameter(e) == "Emissive Tint"
            )
            rgba = members(emission)["ParameterValue"]["Value"][0]["Value"]
            assert all(
                abs(float(rgba[k]) - v * values["glow"]) < 1e-6
                for k, v in zip("RGB", values["colour"])
            )
            assert "TextureParameterValues" not in fields
            parent = extract("Astro/Content/Materials/Master/master_character")
            cached = ps(parent["Exports"][0])["CachedExpressionData"]["Value"]
            parameters = next(e for e in cached if e["Name"] == "Parameters")["Value"]
            texture_entry = [e for e in parameters if e["Name"] == "RuntimeEntries"][2]
            infos = members(texture_entry)["ParameterInfos"]["Value"]
            names = [members(info)["Name"]["Value"] for info in infos]
            references = next(e for e in parameters if e["Name"] == "TextureValues")[
                "Value"
            ]
            defaults = dict(zip(names, [e["Value"] for e in references]))
            texture = parent["Imports"][-defaults["Emissive Map"] - 1]
            assert texture["ObjectName"] == "Black"
            assert (
                parent["Imports"][-texture["OuterIndex"] - 1]["ObjectName"]
                == "/Engine/EngineResources/Black"
            )

"""Read the backpack mesh and its palette bindings."""

import hashlib
import json
import struct

import numpy as np
from asset_io import HERE, gltf
from settings import MODEL_STYLE, model_paths

MODEL, INFO = model_paths(MODEL_STYLE)


def load_model():
    info = json.loads(INFO.read_text())
    if MODEL_STYLE == "luxe":
        base = json.loads(model_paths("base")[1].read_text())
        for key in ["socket_centre_native_x", "battery_back_shift"]:
            assert info[key] == base[key], "luxe must keep the base layout: " + key
    data = MODEL.read_bytes()
    magic, version, length = struct.unpack_from("<III", data)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    jlen = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20 : 20 + jlen])
    start = 20 + jlen + 8
    palette = {
        m["name"]: m["extras"]["nativePaletteBinding"]
        for m in doc["materials"]
        if m.get("extras", {}).get("nativePaletteBinding")
    }
    fixed = {
        m["name"]: m["extras"]["fixedMaterialBinding"]
        for m in doc["materials"]
        if m.get("extras", {}).get("fixedMaterialBinding")
    }
    pieces = []
    for mesh in doc["meshes"]:
        if mesh["name"].startswith(
            (
                "Original",
                "NativeSocket",
                "BatteryCell",
                "BatterySeparator",
                "OxygenGauge",
            )
        ):
            continue
        primitive = mesh["primitives"][0]
        accessor = doc["accessors"][primitive["attributes"]["POSITION"]]
        view = doc["bufferViews"][accessor["bufferView"]]
        points = (
            np.frombuffer(
                data,
                "<f4",
                count=accessor["count"] * 3,
                offset=start
                + view.get("byteOffset", 0)
                + accessor.get("byteOffset", 0),
            )
            .reshape(-1, 3)
            .astype(float)
            * 100
        )
        material = doc["materials"][primitive["material"]]["name"]
        assert material in palette or material in fixed, material
        if material in fixed:
            # Keep each gold face separate so the raised facets stay sharp.
            vertices, indices = points, np.arange(len(points))
        else:
            vertices, indices = np.unique(points, axis=0, return_inverse=True)
        pieces.append(
            {
                "name": mesh["name"],
                "mat": material,
                "v": vertices,
                "f": indices.reshape(-1, 3),
            }
        )
    _, attrs, indices = gltf(HERE / "exports/Models/backpack_mk2/backpack_mk2.gltf")
    positions = attrs["POSITION"][:, [0, 2, 1]] * 100
    groups = json.loads((HERE / "mesh-parts.json").read_text())["parts"]
    keep = np.ones(len(indices), bool)
    for group in groups:
        selected = np.array(group["indices"])
        p = positions[np.unique(indices[selected])]
        if group["root_only"] and group["id"] != 8663 and p[:, 0].max() < 0:
            keep[selected] = False
    for i in next(g["indices"] for g in groups if g["id"] == 8663):
        c = positions[indices[i]].mean(0)
        if c[0] < -5.5 and c[2] < 75 and abs(c[1]) < 59:
            keep[i] = False
    return {
        "parts": pieces,
        "keep": keep,
        "PALETTE_BINDINGS": palette,
        "FIXED_BINDINGS": fixed,
        "socket_centre_x": info["socket_centre_native_x"],
        "BATTERY_BACK_SHIFT": info["battery_back_shift"],
        "approved_model_sha256": hashlib.sha256(data).hexdigest(),
        "approved_model": info["version"],
    }

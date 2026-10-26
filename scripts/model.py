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
        native_uv = None
        if (
            doc["materials"][primitive["material"]]
            .get("extras", {})
            .get("preserveNativeSurfaceUV")
        ):
            uv_accessor = doc["accessors"][primitive["attributes"]["TEXCOORD_0"]]
            uv_view = doc["bufferViews"][uv_accessor["bufferView"]]
            native_uv = (
                np.frombuffer(
                    data,
                    "<f4",
                    count=uv_accessor["count"] * 2,
                    offset=start
                    + uv_view.get("byteOffset", 0)
                    + uv_accessor.get("byteOffset", 0),
                )
                .reshape(-1, 2)
                .astype(float)
            )
            assert len(native_uv) == len(points)
        if native_uv is not None:
            joined, indices = np.unique(
                np.column_stack([points, native_uv]), axis=0, return_inverse=True
            )
            vertices = joined[:, :3]
            native_uv = joined[:, 3:]
        elif material in fixed:
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
        if native_uv is not None:
            pieces[-1]["uv"] = native_uv
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
    replaced = np.asarray(info.get("native_replaced_triangles", []), dtype=int)
    if len(replaced):
        assert MODEL_STYLE == "luxe"
        assert np.all((replaced >= 0) & (replaced < len(keep)))
        assert len(np.unique(replaced)) == len(replaced)
        assert np.all(keep[replaced]), "Only retained native surfaces may be replaced"
        keep[replaced] = False
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

"""Check the static shell unwrap and the explicit luxe colour-point exceptions."""

import json
import struct

import numpy as np
from asset_io import HERE, gltf
from model import INFO, MODEL, load_model
from settings import MODEL_STYLE

POINT_EXCEPTIONS = {
    "SmoothFrontBase",
    "LowerBatteryAccentMount",
    "LuxeElbowStar_SettingShell_-1",
    "LuxeElbowMoon_SettingShell_1",
    *(f"PadEdge_{side}_{row}" for side in [-1, 1] for row in range(4)),
}
BASE_SHELL = {
    "SmoothFrontBase",
    "LowerBatteryAccentMount",
    *(f"Pad_{side}_{row}" for side in [-1, 1] for row in range(4)),
    *(
        f"Battery{end}{part}"
        for end in ["Top", "Bottom"]
        for part in ["Support", "Casing", "CasingWall_-1", "CasingWall_1"]
    ),
}


def check_shell_uv():
    data = MODEL.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20 : 20 + length])
    binary = data[28 + length :]
    policy = json.loads(INFO.read_text())["shell_uv_policy"]
    expected = BASE_SHELL - POINT_EXCEPTIONS if MODEL_STYLE == "luxe" else BASE_SHELL
    exceptions = POINT_EXCEPTIONS if MODEL_STYLE == "luxe" else set()
    revision = json.loads(INFO.read_text()).get("front_mapping_revision")
    if revision and MODEL_STYLE == "luxe":
        retired = {f"Battery{end}CasingWall_{side}" for end in ['Top','Bottom'] for side in [-1,1]}
        expected = (expected-set(revision['plain_parts'])-retired)|set(revision['mapped_parts'])
        exceptions = (exceptions-set(revision['mapped_parts']))|set(revision['plain_parts'])
    if json.loads(INFO.read_text()).get('joined_battery_casings'):
        expected-={f'Battery{end}CasingWall_{side}' for end in ['Top','Bottom'] for side in [-1,1]}
    if json.loads(INFO.read_text()).get('combined_battery_housings'):
        expected-={'BatteryTopSupport','BatteryBottomSupport'}
    assert set(policy["mapped_parts"]) == expected
    assert set(policy["point_sample_parts"]) == exceptions
    assert policy["runtime_processing_added"] is False
    _, native, indices = gltf(HERE / "exports/Models/backpack_mk2/backpack_mk2.gltf")
    assert "TEXCOORD_1" not in native
    a, b = native["TEXCOORD_0"][indices[[3002, 3004]]]
    corners = np.array([a[1], a[0], a[2], b[0]])
    assert np.array_equal(corners, policy["native_uv_corners"])
    surfaces = [corners[[0, 1, 2]], corners[[3, 1, 2]]]

    def array(index):
        accessor = doc["accessors"][index]
        view = doc["bufferViews"][accessor["bufferView"]]
        assert accessor["componentType"] == 5126 and not view.get("byteStride")
        width = {"VEC2": 2, "VEC3": 3}[accessor["type"]]
        return np.frombuffer(
            binary,
            "<f4",
            count=accessor["count"] * width,
            offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0),
        ).reshape(-1, width)

    found = set()
    loaded = {p["name"]: p for p in load_model()["parts"]}
    for mesh in doc["meshes"]:
        name = mesh["name"]
        primitive = mesh["primitives"][0]
        material = doc["materials"][primitive["material"]]
        extras = material.get("extras", {})
        if name in expected:
            assert extras.get("shellUVPolicy") == "rear-casing", name
            assert extras.get("preserveNativeSurfaceUV"), name
            assert material["name"] == (
                "Rear casing shell" if MODEL_STYLE == "luxe" else "shell"
            ), name
            uv = array(primitive["attributes"]["TEXCOORD_0"])
            assert np.isfinite(uv).all() and np.all(np.ptp(uv, axis=0) > 1e-5), name
            # Every corner must remain in the native rear-shell atlas island.
            scores = []
            for triangle in surfaces:
                weights = np.linalg.solve(
                    np.vstack([triangle.T, np.ones(3)]),
                    np.vstack([uv.T, np.ones(len(uv))]),
                )
                scores.append(weights.min(axis=0))
            assert np.all(np.max(scores, axis=0) > -2e-5), name
            # Relief sidewalls must retain area, rather than sampling a line.
            triangles = uv.reshape(-1, 3, 2).astype(float)
            edges = triangles[:, 1:] - triangles[:, :1]
            area = edges[:, 0, 0] * edges[:, 1, 1] - edges[:, 0, 1] * edges[:, 1, 0]
            assert np.all(np.abs(area) > 1e-16), (name, "collapsed UV face")
            part = loaded[name]
            assert np.array_equal(part["uv"][part["f"]].reshape(-1, 2), uv), name
            found.add(name)
        elif name in exceptions:
            assert material["name"] == "shell" and not extras.get(
                "preserveNativeSurfaceUV"
            ), name
            assert extras["nativePaletteBinding"]["uv"] == [
                0.970703125,
                0.09100341796875,
            ], name
            assert "uv" not in loaded[name], name
        else:
            assert extras.get("shellUVPolicy") != "rear-casing", name
    assert found == expected


if __name__ == "__main__":
    check_shell_uv()
    print(
        f"{MODEL_STYLE}: shell UV coverage, atlas island, loader seams and luxe exceptions passed"
    )

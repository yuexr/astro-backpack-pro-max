"""Check serialized UV precision and continuity across separate rear meshes."""

import base64
import json
import struct

import numpy as np
from asset_io import HERE, gltf
from model import INFO, load_model
from settings import OUT


def check_rear_precision(assets):
    info = json.loads(INFO.read_text())
    if "rear_uv_correction" not in info:
        return
    parts = {p["name"]: p for p in load_model()["parts"]}
    for name in info.get("flat_shoulder_settings", []):
        part = parts[name]
        tri = part["v"][part["f"]]
        face = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        face /= np.linalg.norm(face, axis=1)[:, None]
        assert "normal" in part
        assert np.allclose(
            part["normal"][part["f"]], face[:, None, :], atol=1e-6, rtol=0
        ), "White shoulder setting was smoothed"
    if info.get("red_arrow_revision"):
        arrow = parts["LuxeBatteryUpMarker"]
        revision = info["red_arrow_revision"]
        assert (
            len(arrow["f"]) == 2
            and len(np.unique(arrow["v"], axis=0)) == 4
            and arrow["mat"] == "red"
        )
        assert np.allclose(
            arrow["v"].min(0) / 100, revision["bounds_min"], atol=1e-7, rtol=0
        )
        assert np.allclose(
            arrow["v"].max(0) / 100, revision["bounds_max"], atol=1e-7, rtol=0
        )
    for side in [-1, 1]:
        for row in range(4):
            inner = parts[f"Pad_{side}_{row}"]
            edge = parts[f"PadEdge_{side}_{row}"]
            revision = info.get("front_mapping_revision")
            if revision:
                assert (
                    inner["mat"] == "shell"
                    and edge["mat"]
                    == parts["SmoothFrontBase"]["mat"]
                    == "Rear casing shell"
                )
                assert (
                    "uv" not in inner
                    and "uv" in edge
                    and "uv" in parts["SmoothFrontBase"]
                )
            else:
                assert (
                    inner["mat"] == "Rear casing shell"
                    and edge["mat"] == parts["SmoothFrontBase"]["mat"] == "shell"
                )
                assert "uv" in inner and "uv" not in edge
            assert len(inner["f"]) == 46 and len(edge["f"]) == 80
            assert inner["v"][:, 2].min() > 12 and edge["v"][:, 2].max() < 11
            triangles = inner["v"][inner["f"]]
            normals = np.cross(
                triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
            )
            assert np.all(normals[:, 2] > 0), (
                side,
                row,
                "Inward pad face is invisible from the front",
            )
            density = info.get("shell_pattern_density")
            if density and not revision:
                scale = density["native_rear_uv_per_model_unit"]
                ratios = np.ptp(inner["uv"], axis=0) / (
                    np.ptp(inner["v"][:, :2], axis=0) / 100
                )
                assert np.allclose(ratios, [scale, scale], rtol=1e-4, atol=1e-7)
    if info.get("shell_pattern_density"):
        affected = info["shell_pattern_density"]["parts"]
        assert len(affected) == (13 if info.get("front_mapping_revision") else 16) - (
            2 if info.get("combined_battery_housings") else 0
        )
        for name in affected:
            uv = parts[name]["uv"]
            assert np.any(uv != uv.astype("<f2").astype(float)), (
                name,
                "UVs were rounded back to half precision",
            )
    if info.get("raised_rear_stripe_revision"):
        # Restored native side faces keep their original UVs and normals.
        _, original, original_ids = gltf(
            HERE / "exports/Models/backpack_mk2/backpack_mk2.gltf"
        )
        _, current, current_ids = gltf(
            OUT / "mesh-check/Mods/CompactBackpack16/backpack_mk2.gltf"
        )
        restored = np.asarray(
            info["raised_rear_stripe_revision"]["restored_native_triangles"]
        )
        raw = base64.b64decode(assets["backpack_mk2"]["Exports"][0]["Extras"])
        serialized_ids = np.frombuffer(
            raw, "<u2", count=original_ids.size, offset=73944
        ).reshape(-1, 3)
        assert np.array_equal(serialized_ids[restored], original_ids[restored])
        for attr in ["NORMAL", "JOINTS_0", "WEIGHTS_0"]:
            assert np.array_equal(
                current[attr][current_ids[restored]],
                original[attr][original_ids[restored]],
            ), (attr, "Restored native side data changed")
        body = np.load(OUT / "body-expected.npz")
        corners = original_ids[restored]
        boundary = body["rear_uv_boundary"][corners]
        actual_uv = current["TEXCOORD_0"][current_ids[restored]]
        assert np.array_equal(
            actual_uv[~boundary], original["TEXCOORD_0"][corners][~boundary]
        )
        assert np.array_equal(actual_uv, body["uv"][corners])
        assert "LuxeRearStripeShellSurface" not in parts
    elif info.get("side_atlas_seam_fix"):
        side = parts["LuxeRearStripeShellSurface"]
        worst = 0
        for positions, uv in zip(side["v"][side["f"]] / 100, side["uv"][side["f"]]):
            if positions[:, 2].min() > -0.1:
                continue  # Rear flanks only.
            gradient = np.linalg.pinv(positions[1:] - positions[0]) @ (uv[1:] - uv[0])
            singular = np.linalg.svd(gradient, compute_uv=False)
            ratio = singular[0] / singular[-1]
            worst = max(worst, ratio)
            assert ratio < 3, (
                "Side atlas seam stretches pattern",
                ratio,
                positions,
                uv,
            )
    seen = {}
    duplicates = 0
    max_error = 0
    coeff = np.asarray(info["rear_uv_correction"]["coefficients"])
    geometry = json.loads((OUT / "geometry-report.json").read_text())
    for label in ["backpack_mk2"] + geometry["front_components"]:
        raw = base64.b64decode(assets[label]["Exports"][0]["Extras"])
        assert struct.unpack_from("<I", raw, 246134)[0] == 1
        assert struct.unpack_from("<I", raw, 319534)[0] == 8
        if label != "backpack_mk2" and not set(geometry["assets"][label]["parts"]) & {
            "LuxeRearShellSurface",
            "LuxeRearStripeShellSurface",
        }:
            continue
        _, a, ids = gltf(OUT / f"mesh-check/Mods/CompactBackpack16/{label}.gltf")
        active = ids[(ids[:, 0] != ids[:, 1]) & (ids[:, 1] != ids[:, 2])]
        for i in np.unique(active):
            pos = a["POSITION"][i]
            # Native X is the rear normal, glTF X retains this axis.
            if abs(pos[0] - 0.2702467143535614) > 2e-7:
                continue
            xy = np.array([pos[2], float(pos[1]) + 0.51])
            actual = a["TEXCOORD_0"][i]
            if label == "backpack_mk2" and actual[1] > 0.1:
                continue  # Original blue-band island.
            field = (
                np.asarray(info["lower_rear_uv"]["coefficients"])
                if label == "backpack_mk2"
                and xy[1] < 0.33229
                and info.get("lower_rear_uv")
                else coeff
            )
            expected = xy * field[:, 0] + field[:, 1]
            err = float(abs(actual - expected).max())
            max_error = max(max_error, err)
            assert err < 8e-8, (label, pos, actual, expected)
            key = tuple(np.round(pos, 6))
            if key in seen:
                duplicates += 1
                assert np.allclose(actual, seen[key], atol=8e-8, rtol=0), (label, key)
            seen[key] = actual
    assert duplicates > 20, (duplicates, len(seen))
    (OUT / "rear-precision-report.json").write_text(
        json.dumps(
            {
                "shared_vertices_checked": duplicates,
                "max_uv_error": max_error,
                "pad_edges_and_inner_bevels_verified": True,
            },
            indent=2,
        )
    )

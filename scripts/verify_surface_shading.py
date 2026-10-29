"""Check hard rims, smooth walls and cooked tangent frames."""

import base64

import numpy as np
from settings import MODEL_STYLE, OUT


def check_surface_shading(assets, geometry, model, info):
    if "battery_end_revision" not in info:
        return {}
    parts = {p["name"]: p for p in model["parts"]}
    report = {}
    for end in ["Top", "Bottom"]:
        name = "Battery" + end + "Casing"
        p = parts[name]
        tri = p["v"][p["f"]] / 100
        cut = info["battery_end_revision"][name]["flat_inner_end_y"]
        cap = np.all(abs(tri[:, :, 1] - cut) < 1e-7, axis=1)
        expected_cap = (
            info.get("combined_battery_housings", {})
            .get(name, {})
            .get("inner_cap_triangles", 16)
        )
        assert cap.sum() == expected_cap
        # Blender edits leave up to 2.7e-6 lateral rounding on the flat cap normals.
        assert np.allclose(
            p["normal"][p["f"][cap]], [0, -1 if end == "Top" else 1, 0], atol=5e-6
        )
        assert (
            np.all(tri[:, :, 1] >= cut - 1e-7)
            if end == "Top"
            else np.all(tri[:, :, 1] <= cut + 1e-7)
        )
    from verify_lower_accent import check_lower_accent

    report["lower_accent"] = check_lower_accent(model, info)
    report["accent_flat_face_corners"] = (
        info["power_mount_shading_revision"]["front_triangles"] * 3
    )
    if MODEL_STYLE != "luxe":
        return report
    for name in info["auxiliary_cuff_shading_revision"]:
        p = parts[name]
        t = p["v"][p["f"]]
        n = p["normal"][p["f"]]
        cross = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        face = cross / np.linalg.norm(cross, axis=1)[:, None]
        rim = abs(face[:, 0]) > 0.999
        wall = abs(face[:, 0]) < 1e-5
        bevel = ~(rim | wall)
        assert rim.sum() == 64 and wall.sum() == 64 and bevel.sum() == 64
        assert np.allclose(abs(n[rim, :, 0]), 1, atol=1e-6) and np.allclose(
            n[rim, :, 1:], 0, atol=1e-6
        )
        assert np.allclose(n[wall, :, 0], 0, atol=5e-6)
        centre = (t.reshape(-1, 3).min(0) + t.reshape(-1, 3).max(0)) / 2
        radial = t[wall, :, 1:] - centre[1:]
        radial /= np.linalg.norm(radial, axis=2)[:, :, None]
        assert np.allclose(abs((n[wall, :, 1:] * radial).sum(2)), 1, atol=2e-6)
        assert np.all((n[bevel] * face[bevel, None, :]).sum(2) > 0.98), (
            "Cuff bevel normals no longer follow the surface"
        )
    moon = info["right_moon_smoothing_revision"]
    right = parts[moon["part"]]
    assert (
        len(right["f"]) == 232 and "normal" in right and moon["sharp_peak_edges"] > 20
    )
    assert "LuxeElbowMoon_-1" not in parts and len(parts["LuxeElbowStar_-1"]["f"]) == 24
    for side in [-1, 1]:
        for row in range(4):
            p = parts[f"LuxePadInlay_{side}_{row}"]
            t = p["v"][p["f"]]
            face = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
            face /= np.linalg.norm(face, axis=1)[:, None]
            assert "normal" in p and np.allclose(
                p["normal"][p["f"]], face[:, None, :], atol=2e-6
            ), "Gold pad border must remain flat"
    rear = parts["LuxeRearShellSurface"]
    t = rear["v"][rear["f"]] / 100
    plane = info["rear_shading_revision"]["flat_plane_z"]
    flat = np.all(abs(t[:, :, 2] - plane) < 1e-7, axis=1)
    assert flat.sum() == info["rear_shading_revision"][
        "flat_triangles"
    ] and np.allclose(rear["normal"][rear["f"][flat]], [0, 0, -1], atol=1e-6)
    # Inspect serialized frames. The source UV/position arrays used here have
    # already been independently reopened and compared through UE Viewer.
    wanted = np.asarray(
        [0, np.sign(info["rear_uv_correction"]["coefficients"][0][0]), 0]
    )
    checked = 0
    minimum = 1.0
    for label, description in geometry["assets"].items():
        raw = base64.b64decode(assets[label]["Exports"][0]["Extras"])
        packed = np.frombuffer(raw, "i1", count=9173 * 8, offset=246150).reshape(-1, 8)
        expected = np.load(OUT / (label + "-expected.npz"))
        cursor = 0
        for name in description["parts"]:
            p = parts[name]
            count = len(p["v"])
            allocated = expected["allocated"][cursor : cursor + count]
            cursor += count
            if name != "LuxeRearShellSurface":
                continue
            tangent = packed[allocated, :3].astype(float)
            tangent /= np.linalg.norm(tangent, axis=1)[:, None]
            tri = p["v"][p["f"]] / 100
            onplane = np.all(abs(tri[:, :, 2] - plane) < 1e-7, axis=1)
            area = (
                np.linalg.norm(
                    np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1
                )
                / 2
            )
            corners = np.unique(p["f"][onplane & (area > 1e-7)])
            alignment = tangent[corners] @ wanted
            assert np.all(alignment > 0.99), (
                "Rear tangent rotates between panel triangles",
                alignment.min(),
            )
            minimum = min(minimum, float(alignment.min()))
            checked += len(corners)
    assert checked > 100
    report.update(
        auxiliary_cuffs_sharp_rims_smooth_walls=True,
        right_moon_peak_preserved=True,
        left_star_restored=True,
        all_gold_borders_flat=True,
        rear_tangent_vertices=checked,
        rear_tangent_min_alignment=minimum,
    )
    return report

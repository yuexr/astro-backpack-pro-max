"""Check the low-poly bezel, buried root and straight-sided blue insert."""

from collections import Counter

import numpy as np


def check_lower_accent(model, info):
    parts = {p["name"]: p for p in model["parts"]}
    revision = info["lower_accent_rebuild_revision"]
    mount = parts["LowerBatteryAccentMount"]
    accent = parts["LowerBatteryAccent"]
    white = mount["v"][mount["f"]] / 100
    blue = accent["v"][accent["f"]] / 100
    n = mount["normal"][mount["f"]]
    base = revision.get("blue_straight_walls", False)
    assert len(white) == (72 if base else 82)
    assert len(blue) == (34 if base else 46)
    assert np.allclose(np.linalg.norm(n, axis=2), 1, atol=1e-6)
    assert abs(np.ptp(white[:, :, 0]) - revision["width"]) < 2e-7
    assert abs(np.ptp(white[:, :, 1]) - revision["height"]) < 2e-7
    assert abs(white[:, :, 2].max() - revision["front_plane_z"]) < 1e-7
    housing = info["combined_battery_housings"]["BatteryBottomCasing"]
    assert white[:, :, 1].min() > housing["support_end_y"] + 0.001
    assert (
        white[:, :, 1].max()
        < info["battery_end_revision"]["BatteryBottomCasing"]["flat_inner_end_y"]
        - 0.001
    )

    assembly = np.concatenate([white, blue]) if base else white
    vertices, faces = np.unique(
        np.round(assembly.reshape(-1, 3), 7), axis=0, return_inverse=True
    )
    edges = Counter(
        tuple(sorted((int(a), int(b))))
        for f in faces.reshape(-1, 3)
        for a, b in zip(f, np.roll(f, -1))
    )
    assert set(edges.values()) == {1, 2}
    boundary = [edge for edge, count in edges.items() if count == 1]
    assert len(boundary) == 12 and len(vertices) - len(edges) + len(assembly) == 1
    perimeter = np.asarray(
        info["combined_battery_housings"]["BatteryBottomCasing"]["perimeter"]
    )

    def casing_depth(x):
        hits = []
        for a, b in zip(perimeter, np.roll(perimeter, -1, axis=0)):
            if abs(b[0] - a[0]) < 1e-12:
                continue
            w = (x - a[0]) / (b[0] - a[0])
            if -1e-6 <= w <= 1 + 1e-6:
                hits.append(a[1] + w * (b[1] - a[1]))
        assert hits
        return max(hits)

    cover = []
    for a, b in boundary:
        for p in (
            vertices[a] + (vertices[b] - vertices[a]) * np.linspace(0, 1, 65)[:, None]
        ):
            cover.append(casing_depth(p[0]) - p[2])
    assert min(cover) > 0.00019, "An open bezel edge is exposed"
    root = white[:, :, 2] < revision["side_wall_front_z"] - 1e-7
    assert root.any() and np.all(abs(n[root, 2]) < 1e-6), (
        "The casing contact must retain separate wall normals"
    )
    flat = np.all(abs(white[:, :, 2] - revision["front_plane_z"]) < 1e-7, axis=1)
    assert flat.sum() == (0 if base else 10)
    if flat.any():
        assert np.all(n[flat, :, 2] > 0.9)
    if base:
        z0 = revision["front_plane_z"]
        z1 = z0 + revision["blue_protrusion"]
        assert np.all(
            np.minimum(abs(blue[:, :, 2] - z0), abs(blue[:, :, 2] - z1)) < 1e-7
        )
        front = np.all(abs(blue[:, :, 2] - z1) < 1e-7, axis=1)
        assert front.sum() == 10 and (~front).sum() == 24
        assert np.allclose(accent["normal"][accent["f"]][front], [0, 0, 1], atol=1e-6)
        root_points = blue[abs(blue[:, :, 2] - z0) < 1e-7]
        tip_points = blue[abs(blue[:, :, 2] - z1) < 1e-7]
        assert all(
            np.linalg.norm(tip_points[:, :2] - p[:2], axis=1).min() < 1e-7
            for p in root_points
        )
        assert abs(np.ptp(blue[:, :, 2]) - revision["blue_protrusion"]) < 1e-7
    else:
        assert len(np.unique(np.round(blue[:, :, 2], 7))) == 2
        assert abs(blue[:, :, 2].min() - revision["symbol_base_z"]) < 1e-7
        assert revision["front_plane_z"] - blue[:, :, 2].min() > 0.00009
        centre = np.array([0.0, (white[:, :, 1].min() + white[:, :, 1].max()) / 2])
        half = (
            np.array([revision["width"], revision["height"]]) / 2
            - revision["bevel_insets"][-1]
        )
        q = abs(blue[:, :, :2] - centre) - (half - 0.0025)
        distance = (
            np.linalg.norm(np.maximum(q, 0), axis=2) + np.minimum(q.max(2), 0) - 0.0025
        )
        assert distance.max() < -0.001, "Luxe symbol exceeds its support face"
    return {
        "mount_triangles": len(white),
        "accent_triangles": len(blue),
        "buried_boundary_edges": len(boundary),
        "minimum_root_cover": float(min(cover)),
        "exposed_edges_smoothed": True,
        "casing_join_sharp": True,
        "blue_straight_walls": True,
    }

"""Verify common contact shading/gauge fits and Luxe surface repairs."""

import json

import numpy as np
from asset_io import HERE, gltf, ps, xyz
from model import INFO, load_model
from settings import MODEL_STYLE, OUT


def hull(points):
    points = sorted({tuple(float(v) for v in p) for p in points})

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower = []
    upper = []
    for p in points:
        while len(lower) > 1 and cross(lower[-2], lower[-1], p) <= 1e-12:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) > 1 and cross(upper[-2], upper[-1], p) <= 1e-12:
            upper.pop()
        upper.append(p)
    return np.asarray(lower[:-1] + upper[:-1])


def check_refinements(assets, geometry):
    info = json.loads(INFO.read_text())
    model = load_model()
    parts = {p["name"]: p for p in model["parts"]}
    report = {}
    from verify_current_model import check_current_model

    report["current_model_revision"] = check_current_model(model, info)
    for end in ["Top", "Bottom"]:
        name = "Battery" + end + "Casing"
        p = parts[name]
        assert not any(n.startswith(name + "Wall_") for n in parts)
        expected_count = (
            info.get("battery_end_revision", {}).get(name, {}).get("triangles", 264)
        )
        assert "normal" in p and len(p["f"]) == expected_count
        _, vertex = np.unique(np.round(p["v"] / 100, 6), axis=0, return_inverse=True)
        faces = vertex[p["f"]]
        adj = {int(i): set() for i in np.unique(faces)}
        for face in faces:
            for a, b in zip(face, np.roll(face, 1)):
                adj[int(a)].add(int(b))
                adj[int(b)].add(int(a))
        found = set()
        stack = [next(iter(adj))]
        while stack:
            v = stack.pop()
            if v in found:
                continue
            found.add(v)
            stack.extend(adj[v] - found)
        assert len(found) == len(adj), (name, "Casing contains disconnected walls")
    revision = info["pad_smoothing_revision"]
    front = parts["SmoothFrontBase"]
    assert np.allclose(front["normal"], [0, 0, 1], atol=1e-6)
    root_count = 0
    sharp_count = 0
    for name in revision["parts"]:
        p = parts[name]
        v = p["v"] / 100
        n = p["normal"]
        root = abs(v[:, 2] - revision["root_depth"]) < 1e-6
        assert np.allclose(n[root], [0, 0, 1], atol=1e-6)
        root_count += int(root.sum())
        t = v[p["f"]]
        normals = n[p["f"]]
        flat = np.all(abs(t[:, :, 2] - revision["inner_face_depth"]) < 1e-6, axis=1)
        bevel = (t[:, :, 2].min(1) > revision["inner_face_depth"] - 1e-5) & ~flat
        assert np.allclose(normals[flat], [0, 0, 1], atol=1e-6)
        low = abs(t[bevel, :, 2] - revision["inner_face_depth"]) < 1e-6
        if low.any():
            assert np.all(normals[bevel][low, 2] < 0.99), (
                "Inner bevel was averaged into the flat pad face"
            )
            sharp_count += int(low.sum())
    assert root_count >= 64 and sharp_count >= 128, (root_count, sharp_count)
    report["pad_root_vertices"] = root_count
    report["sharp_inner_join_corners"] = sharp_count
    geometry["battery_fit"]
    lower = parts["BatteryBottomCasing"]["v"][:, 1].max() - 51
    upper = parts["BatteryTopCasing"]["v"][:, 1].min() - 51
    gauge = {}
    for label in ["BackpackRail", "AstroCorpse"]:
        d = assets[label]
        e = next(e for e in d["Exports"] if e["ObjectName"] == "Power Bar_GEN_VARIABLE")
        p = ps(e)
        scale = float(xyz(p["RelativeScale3D"])["Z"])
        z = float(xyz(p["RelativeLocation"])["Z"])
        ends = z + np.asarray([-0.5, 100.5]) * scale
        assert np.allclose(ends, [lower, upper], atol=2e-5, rtol=0), (
            label,
            ends,
            lower,
            upper,
        )
        cls = d["Imports"][-p["ChildActorClass"]["Value"] - 1]["ObjectName"]
        assert cls == info["battery_divider_revision"]["private_child_class"]
        gauge[label] = {
            "separator_faces": ends.tolist(),
            "casing_edges": [float(lower), float(upper)],
        }
        if label == "BackpackRail":
            overlay = ps(
                next(
                    e
                    for e in d["Exports"]
                    if e["ObjectName"] == "PowerBarOverlay_GEN_VARIABLE"
                )
            )
            oz = float(xyz(overlay["RelativeLocation"])["Z"])
            os = float(xyz(overlay["RelativeScale3D"])["Z"])
            oe = oz + np.asarray([0, 90]) * os
            assert oe[0] >= lower - 2e-5 and oe[1] <= upper + 2e-5
    report["gauges"] = gauge
    result = [
        "joined top/bottom casings and authored pad-root smoothing with sharp inner bevel joins verified",
        "native ten-cell gauge and separator stack fitted to casing edges on live and corpse backpacks; overlay remains inside the fitted span",
    ]
    if MODEL_STYLE == "luxe":
        _, a, ids = gltf(HERE / "exports/Models/backpack_mk2/backpack_mk2.gltf")
        v = a["POSITION"].astype(float)
        v = np.column_stack([v[:, 2], v[:, 1] + 0.51, -(v[:, 0] - 0.0146842727662)])
        lower_info = info["lower_rear_uv"]
        body = np.load(OUT / "body-expected.npz")
        uv = body["uv"]
        selection = np.asarray(lower_info["native_triangles"], dtype=int)
        ratios = []
        for face in ids[selection]:
            p = v[face]
            u = uv[face]
            s = np.linalg.svd(
                np.linalg.pinv(p[1:] - p[0]) @ (u[1:] - u[0]), compute_uv=False
            )
            assert s[-1] > 1e-5, "Collapsed lower rear UV triangle"
            ratios.append(float(s[0] / s[-1]))
        assert max(ratios) < 2
        report["lower_rear_uv"] = {
            "triangles": len(selection),
            "worst_stretch": max(ratios),
            "median_stretch": float(np.median(ratios)),
        }
        t = v[ids[model["keep"]]]
        mat = np.stack([t[:, :, 0], t[:, :, 1], np.ones(t.shape[:2])], axis=1)
        valid = abs(np.linalg.det(mat)) > 1e-12
        mat = mat[valid]
        t = t[valid]
        seating = {}
        for name in info["emblem_seating_revision"]:
            p = parts[name]["v"] / 100
            base = p[:, 2].min()
            ring = hull(p[abs(p[:, 2] - base) < 1e-6, :2])
            gaps = []
            for start, end in zip(ring, np.roll(ring, -1, axis=0)):
                for point in start + (end - start) * np.linspace(0, 1, 65)[:, None]:
                    w = np.linalg.solve(
                        mat,
                        np.broadcast_to([point[0], point[1], 1], (len(mat), 3))[
                            :, :, None
                        ],
                    )[:, :, 0]
                    hit = w.min(1) > -1e-6
                    assert hit.any(), (
                        name,
                        "A base edge projects outside the native casing",
                    )
                    surface = (w * t[:, :, 2]).sum(1)[hit].max()
                    gaps.append(float(surface - base))
            assert min(gaps) >= -2e-7 and min(gaps) < 0.00015, (
                name,
                "Floating or excessively buried setting",
                min(gaps),
            )
            seating[name] = {
                "edge_samples": len(gaps),
                "minimum_embed": min(gaps),
                "maximum_embed": max(gaps),
            }
        report["emblem_seating"] = seating
        result.append(
            "lower rear UVs retain noncollapsed mapping; both octagonal settings remain at their outward seating limits without floating"
        )
    from verify_surface_shading import check_surface_shading

    report["surface_shading"] = check_surface_shading(assets, geometry, model, info)
    (OUT / "model-refinements-report.json").write_text(json.dumps(report, indent=2))
    return result

"""Verify real closed battery unions and continuous side-wall texture fields."""

from collections import Counter

import numpy as np


def check_joined_housings(parts, info):
    result = {}
    for end in ["Top", "Bottom"]:
        name = "Battery" + end + "Casing"
        h = info["combined_battery_housings"][name]
        p = parts[name]
        t = p["v"][p["f"]] / 100
        n = p["normal"][p["f"]]
        uv = p["uv"][p["f"]]
        assert "Battery" + end + "Support" not in parts, (
            "Retired support still exported"
        )
        v, f = np.unique(np.round(t.reshape(-1, 3), 7), axis=0, return_inverse=True)
        e = Counter(
            tuple(sorted([int(a), int(b)]))
            for face in f.reshape(-1, 3)
            for a, b in zip(face, np.roll(face, -1))
        )
        assert set(e.values()) == {2} and len(v) - len(e) + len(t) == 2, (
            "Housing is not one closed genus-zero union"
        )
        assert len(t) == h["triangles"] < h["previous_case_and_support_triangles"]
        assert np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() > 0, (
            "Housing winding inverted"
        )
        b = np.asarray(h["support_region_bounds"])
        target = np.asarray(
            info["battery_support_edge_revision"][end]["casing_vertex_right"]
        )
        cz = h["cylinder_centre_z"]
        radius = h["cylinder_radius"]
        assert (
            abs(target[0] - radius * np.cos(np.pi / 8)) < 2e-7
            and abs(target[1] - (cz - radius * np.sin(np.pi / 8))) < 2e-7
        )
        assert (
            np.allclose(b[:, 0], [-target[0], target[0]], atol=1e-8, rtol=0)
            and abs(b[1, 2] - target[1]) < 1e-8
        )
        root = h["support_end_y"]
        inner = info["battery_end_revision"][name]["flat_inner_end_y"]
        sign = 1 if end == "Top" else -1
        caps = np.ptp(t[:, :, 1], axis=1) < 1e-7
        inner_cap = np.all(abs(t[:, :, 1] - inner) < 1e-7, axis=1)
        assert inner_cap.sum() == h["inner_cap_triangles"] and np.allclose(
            n[inner_cap], [0, -sign, 0], atol=1e-7
        )
        ledge = np.all(abs(t[:, :, 1] - root) < 1e-7, axis=1)
        assert ledge.sum() == h["support_ledge_triangles"] and np.allclose(
            n[ledge], [0, sign, 0], atol=1e-7
        )
        body = (sign * (t[:, :, 1] - inner)).max(1) <= sign * (root - inner) + 1e-7
        buried = body & ~caps & (t[:, :, 2].mean(1) < target[1] - 1e-7)
        for face in t[buried]:
            assert (
                np.all(abs(face[:, 0] - target[0]) < 1e-7)
                or np.all(abs(face[:, 0] + target[0]) < 1e-7)
                or np.all(abs(face[:, 2] - b[0, 2]) < 1e-7)
            ), "Internal overlap face survived the union"
        continuity = {}
        perimeter = np.asarray(h["perimeter"])
        s = np.asarray(h["perimeter_distances"])
        u0, v0 = h["uv_origin"]
        d = h["uv_density"]
        centre = h["uv_y_centre"]
        for side, k in [(1, 1), (-1, len(perimeter) - 2)]:
            seam = (
                (~caps)[:, None]
                & (abs(t[:, :, 0] - side * target[0]) < 1e-7)
                & (abs(t[:, :, 2] - target[1]) < 1e-7)
                & (sign * (t[:, :, 1] - inner) >= -1e-7)
                & (sign * (t[:, :, 1] - root) <= 1e-7)
            )
            assert seam.sum() >= 6
            expected = np.stack(
                [np.full(seam.sum(), u0 + d * s[k]), v0 - d * (t[seam, 1] - centre)],
                axis=1,
            )
            error = float(abs(uv[seam] - expected).max())
            assert error < 7e-8, ("Casing/support UV seam", end, side, error)
            assert np.allclose(
                n[seam],
                info["battery_support_edge_revision"][end]["shared_join_normals"][
                    str(side)
                ],
                atol=2e-7,
            )
            continuity[str(side)] = {
                "corners": int(seam.sum()),
                "maximum_uv_error": error,
            }
        result[end] = {
            "width": float(np.ptp(b[:, 0])),
            "front_depth": float(b[1, 2]),
            "matched_casing_vertex": target.tolist(),
            "triangles": len(t),
            "previous_triangles": h["previous_case_and_support_triangles"],
            "uv_joins": continuity,
            "closed": True,
        }
    assert (
        result["Top"]["width"] == result["Bottom"]["width"]
        and result["Top"]["front_depth"] == result["Bottom"]["front_depth"]
    )
    return result

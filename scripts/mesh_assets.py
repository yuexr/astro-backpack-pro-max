"""build the meshes on the vanilla skeleton"""

import base64
import copy
import json

import numpy as np
from asset_io import HERE, gltf
from model import load_model
from settings import MODEL_STYLE, OUT, PKG

OUT.mkdir(parents=True, exist_ok=True)
OFF = {"position": 136048, "tangent": 246150, "uv": 319542, "index": 73944}
N = 9173


def source():
    return json.loads(
        (
            HERE / "vanilla/Astro/Content/Models/backpack_mk2/backpack_mk2.json"
        ).read_text()
    )


def rename_mesh(d, label, raw):
    d["Exports"][0]["Extras"] = base64.b64encode(raw).decode()
    d["Exports"][0]["ObjectName"] = label
    d["NameMap"] = [
        PKG + label if x == "/Game/Models/backpack_mk2/backpack_mk2" else x
        for x in d["NameMap"]
    ]
    if label not in d["NameMap"]:
        d["NameMap"].append(label)
    return d


def build_meshes():
    # the GLB is the source; Blender is just a preview
    model = load_model()
    _, a, ids = gltf(HERE / "exports/Models/backpack_mk2/backpack_mk2.gltf")
    root = np.flatnonzero(np.all((a["JOINTS_0"] == 0) | (a["WEIGHTS_0"] == 0), axis=1))
    p = a["POSITION"][:, [0, 2, 1]] * 100
    original = source()
    raw = bytearray(base64.b64decode(original["Exports"][0]["Extras"]))
    assert np.array_equal(
        np.frombuffer(raw, "<u2", count=ids.size, offset=OFF["index"]).reshape(-1, 3),
        ids,
    )
    assert np.allclose(
        np.frombuffer(raw, "<f4", count=N * 3, offset=OFF["position"]).reshape(-1, 3),
        p,
        atol=1e-4,
    )
    result = {}
    report = {
        "approved_model": model["approved_model"],
        "assets": {},
        "atlas_uv": {},
        "socket_centre_native_x": float(model["socket_centre_x"]),
        "battery_centre_native_x": -13.8 + model["BATTERY_BACK_SHIFT"],
        "approved_model_sha256": model["approved_model_sha256"],
        "model_style": MODEL_STYLE,
    }
    # keep the rear, shoulders and animated parts
    bodyids = ids.copy()
    bodyids[~model["keep"]] = 0
    raw[OFF["index"] : OFF["index"] + ids.nbytes] = bodyids.astype("<u2").tobytes()
    # Preserve all native body UVs. The drone mount is a separate runtime mesh.
    uv = a["TEXCOORD_0"].copy()
    result["backpack_mk2"] = rename_mesh(copy.deepcopy(original), "backpack_mk2", raw)
    np.savez(
        OUT / "body-expected.npz",
        positions=p,
        indices=bodyids,
        keep=model["keep"],
        uv=uv,
    )
    # keep the socket's original UVs, tangents and bone weights
    native_groups = json.loads((HERE / "mesh-parts.json").read_text())["parts"]
    si = np.array(next(g["indices"] for g in native_groups if g["id"] == 8825))
    sv = np.unique(ids[si])
    centre = (p[sv].min(0) + p[sv].max(0)) / 2
    group = {
        "group": 8825,
        "triangles": si.tolist(),
        "vertices": sv.tolist(),
        "centre": centre.tolist(),
        "scale": 0.88,
    }
    q = p.copy()
    q[sv] -= centre
    newids = np.zeros_like(ids)
    newids[si] = ids[si]
    raw = bytearray(base64.b64decode(original["Exports"][0]["Extras"]))
    raw[OFF["position"] : OFF["position"] + p.nbytes] = q.astype("<f4").tobytes()
    raw[OFF["index"] : OFF["index"] + ids.nbytes] = newids.astype("<u2").tobytes()
    result["backpack_socket"] = rename_mesh(
        copy.deepcopy(original), "backpack_socket", raw
    )
    (OUT / "socket-source.json").write_text(json.dumps(group, indent=2))
    # Sample the vanilla atlas so colours follow the player palette.
    palette = {
        name: binding["uv"] for name, binding in model["PALETTE_BINDINGS"].items()
    }
    report["atlas_uv"] = palette
    report["palette_sources"] = model["PALETTE_BINDINGS"]
    pieces = model["parts"]
    # split between parts if the native mesh buffer fills up
    batches = []
    batch = []
    nv = nt = 0
    for piece in pieces:
        if nv + len(piece["v"]) > len(root) or nt + len(piece["f"]) > len(ids):
            batches.append(batch)
            batch = []
            nv = nt = 0
        assert len(piece["v"]) <= len(root) and len(piece["f"]) <= len(ids)
        batch.append(piece)
        nv += len(piece["v"])
        nt += len(piece["f"])
    if batch:
        batches.append(batch)
    if MODEL_STYLE == "luxe":
        assert len(batches) == 1, "luxe needs to fit the same front1 component as base"
    for number, batch in enumerate(batches, 1):
        label = f"front{number}"
        verts = []
        faces = []
        uvs = []
        count = 0
        for piece in batch:
            v = piece["v"]
            verts.extend(
                np.column_stack([1.46842727662 - v[:, 2], v[:, 0], v[:, 1] - 51])
            )
            faces.extend(piece["f"] + count)
            uvs.extend([palette[piece["mat"]]] * len(v))
            count += len(v)
        v = np.array(verts)
        f = np.array(faces)
        uv = np.array(uvs)
        # UE native mesh winding is opposite its outward normal in native axes.
        normal = np.zeros_like(v)
        crosses = -np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        for k in range(3):
            np.add.at(normal, f[:, k], crosses)
        length = np.linalg.norm(normal, axis=1)
        normal[length < 1e-8] = [1, 0, 0]
        normal /= np.linalg.norm(normal, axis=1)[:, None]
        basis = np.zeros_like(normal)
        basis[np.arange(len(v)), np.argmin(abs(normal), axis=1)] = 1
        tangent = np.cross(basis, normal)
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        raw = bytearray(base64.b64decode(original["Exports"][0]["Extras"]))
        pos = np.zeros((N, 3), "<f4")
        tex = np.zeros((N, 2), "<f2")
        tan = np.zeros((N, 8), "i1")
        allocated = root[: len(v)]
        pos[allocated] = v
        tex[allocated] = uv
        tan[allocated, :3] = np.round(tangent * 127).astype("i1")
        tan[allocated, 3] = 127
        tan[allocated, 4:7] = np.round(normal * 127).astype("i1")
        tan[allocated, 7] = 127
        indices = np.zeros_like(ids)
        indices[: len(f)] = allocated[f]
        for key, array in [
            ("position", pos),
            ("uv", tex),
            ("tangent", tan),
            ("index", indices.astype("<u2")),
        ]:
            raw[OFF[key] : OFF[key] + array.nbytes] = array.tobytes()
        result[label] = rename_mesh(copy.deepcopy(original), label, raw)
        np.savez(
            OUT / (label + "-expected.npz"),
            positions=pos,
            uv=tex.astype("f4"),
            indices=indices,
            normals=normal,
            allocated=allocated,
        )
        report["assets"][label] = {
            "vertices": len(v),
            "triangles": len(f),
            "parts": [x["name"] for x in batch],
            "materials": {x["name"]: x["mat"] for x in batch},
        }
    report["front_components"] = list(report["assets"])
    # use the vanilla drone socket mesh with backpack palette UVs
    _, da, di = gltf(HERE / "exports/Slots/Content/new/slot_t1b_i.gltf")
    dv = da["POSITION"][:, [0, 2, 1]] * 100
    du = da["TEXCOORD_0"]
    red = du[:, 0] > 0.2
    dark = du[:, 1] > 0.08
    grey = ~(red | dark)
    assert (red.sum(), grey.sum(), dark.sum()) == (160, 152, 25)
    assert len(dv) == 337 and len(di) == 312
    duv = np.empty_like(du)
    duv[red] = palette["red"]
    duv[grey] = palette["eyelet"]
    duv[dark] = palette["dark"]
    allocated = root[: len(dv)]
    pos = np.zeros((N, 3), "<f4")
    tex = np.zeros((N, 2), "<f2")
    tan = np.zeros((N, 8), "i1")
    pos[allocated] = dv
    tex[allocated] = duv
    tan[allocated, :3] = np.round(da["TANGENT"][:, [0, 2, 1]] * 127).astype("i1")
    tan[allocated, 3] = 127
    tan[allocated, 4:7] = np.round(da["NORMAL"][:, [0, 2, 1]] * 127).astype("i1")
    tan[allocated, 7] = 127
    drone_indices = np.zeros_like(ids)
    drone_indices[: len(di)] = allocated[di]
    raw = bytearray(base64.b64decode(original["Exports"][0]["Extras"]))
    for key, array in [
        ("position", pos),
        ("uv", tex),
        ("tangent", tan),
        ("index", drone_indices.astype("<u2")),
    ]:
        raw[OFF[key] : OFF[key] + array.nbytes] = array.tobytes()
    result["drone_socket"] = rename_mesh(copy.deepcopy(original), "drone_socket", raw)
    np.savez(
        OUT / "drone-expected.npz",
        positions=pos,
        uv=tex.astype("f4"),
        indices=drone_indices,
        allocated=allocated,
    )
    report["drone_palette"] = {
        "source": "vanilla slot_t1b_i; native backpack socket UV samples and shared dynamic material",
        "vertices": 337,
        "triangles": 312,
        "geometry_unchanged": True,
        "body_uv_unchanged": True,
        "live_only": True,
    }

    report["all_animated_triangles_preserved"] = bool(
        model["keep"][~np.all(np.isin(ids, root), axis=1)].all()
    )
    assert report["all_animated_triangles_preserved"]
    (OUT / "geometry-report.json").write_text(json.dumps(report, indent=2))
    return result, report

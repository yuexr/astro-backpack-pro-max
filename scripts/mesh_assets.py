"""build the meshes on the vanilla skeleton"""

import base64
import copy
import json
import struct

import numpy as np
from asset_io import HERE, gltf
from model import INFO, load_model
from settings import MODEL_STYLE, OUT, PKG
from surface_tangents import surface_tangents

OUT.mkdir(parents=True, exist_ok=True)
OFF = {
    "position": 136048,
    "tangent": 246150,
    "uv": 319542,
    "index": 73944,
    "skin": 356264,
}
N = 9173


def precise_uv_buffer(raw, uv):
    """Serialize UE4's float UV layout, retaining tangent and skin buffers."""
    assert struct.unpack_from("<IIII", raw, 246126) == (1, N, 0, 0)
    assert struct.unpack_from("<II", raw, OFF["uv"] - 8) == (4, N)
    struct.pack_into("<I", raw, 246134, 1)
    struct.pack_into("<I", raw, OFF["uv"] - 8, 8)
    raw[OFF["uv"] : OFF["uv"] + N * 4] = np.asarray(uv, dtype="<f4").tobytes()
    return raw


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
    model_info = json.loads(INFO.read_text())
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
    native_skin = (
        np.frombuffer(raw, "u1", count=N * 8, offset=OFF["skin"]).reshape(N, 8).copy()
    )
    assert np.array_equal(native_skin[:, 4:], a["WEIGHTS_0"])
    joint_skin = {}
    for joint in [0, 1, 2]:
        pure = np.flatnonzero(
            np.all((a["JOINTS_0"] == joint) | (a["WEIGHTS_0"] == 0), axis=1)
        )
        assert len(pure)
        joint_skin[joint] = native_skin[pure[0]].copy()
        assert np.all(native_skin[pure] == joint_skin[joint])
    result = {}
    report = {
        "approved_model": model["approved_model"],
        "assets": {},
        "atlas_uv": {},
        "socket_centre_native_x": float(model["socket_centre_x"]),
        "battery_centre_native_x": -13.8 + model["BATTERY_BACK_SHIFT"],
        "approved_model_sha256": model["approved_model_sha256"],
        "model_style": MODEL_STYLE,
        "battery_fit": model_info["battery_fit"],
        "battery_dividers": model_info["battery_divider_revision"],
    }
    # keep the rear, shoulders and animated parts
    bodyids = ids.copy()
    bodyids[~model["keep"]] = 0
    raw[OFF["index"] : OFF["index"] + ids.nbytes] = bodyids.astype("<u2").tobytes()
    # Preserve original colour-role islands, including the native blue band.
    uv = a["TEXCOORD_0"].copy()
    boundary = np.zeros(N, dtype=bool)
    if MODEL_STYLE == "luxe":
        correction = model_info.get("rear_uv_correction")
        if correction:
            boundary = (abs(a["POSITION"][:, 0] - .2702467143535614) < 2e-7) & (uv[:,0]>.89) & (uv[:,0]<.95) & (uv[:,1]<.1) & (a['POSITION'][:,1]+.51>=.33229)
            coordinates = np.column_stack([a["POSITION"][:, 2], a["POSITION"][:, 1] + .51])
            for axis, (slope, intercept) in enumerate(correction["coefficients"]):
                uv[boundary, axis] = coordinates[boundary, axis] * slope + intercept
        lower = model_info.get('lower_rear_uv')
        if lower:
            lower_ids=np.asarray(lower['native_vertex_ids'],dtype=int)
            uv[lower_ids]=np.asarray(lower['uv'],dtype='<f4');boundary[lower_ids]=True
    from rear_shading import body_buffers
    body=body_buffers(raw,bodyids,model['keep'],uv,boundary,model_info.get('native_rear_flank_shading'),OFF,N)
    if body['rear_uv_boundary'].any():raw=precise_uv_buffer(raw,body['uv'])
    result["backpack_mk2"] = rename_mesh(copy.deepcopy(original), "backpack_mk2", raw)
    np.savez(
        OUT / "body-expected.npz",
        keep=model["keep"],
        **body,
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
    fixed = model["FIXED_BINDINGS"]
    palette.update({name: binding["uv"] for name, binding in fixed.items()})
    report["atlas_uv"] = palette
    report["palette_sources"] = model["PALETTE_BINDINGS"]
    pieces = model["parts"]
    # Fixed gold has its own component so palette updates cannot recolour it.
    batches = []
    pools = {}
    for piece in pieces:
        material = fixed.get(piece["mat"], {}).get("asset")
        pools.setdefault(material, []).append(piece)
    for pool in pools.values():
        batch = []
        nv = nt = 0
        for piece in pool:
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
    for number, batch in enumerate(batches, 1):
        label = f"front{number}"
        verts = []
        faces = []
        uvs = []
        allocation = []
        joints = []
        count = 0
        authored_normals = []
        for piece in batch:
            v = piece["v"]
            joint = 0
            if piece["name"].startswith(
                ("LuxeShoulderSocketRing_", "LuxeElbowStar_", "LuxeElbowMoon_")
            ):
                joint = 1 if piece["name"].endswith("_-1") else 2
            selected = root[count : count + len(v)]
            assert len(selected) == len(v), (
                "Not enough native vertices for shoulder skinning"
            )
            allocation.extend(selected)
            joints.extend([joint] * len(v))
            verts.extend(
                np.column_stack([1.46842727662 - v[:, 2], v[:, 0], v[:, 1] - 51])
            )
            faces.extend(piece["f"] + count)
            uvs.extend(piece["uv"] if "uv" in piece else [palette[piece["mat"]]] * len(v))
            count += len(v)
            if "normal" in piece:
                n=piece["normal"]
                authored_normals.extend(np.column_stack([-n[:,2],n[:,0],n[:,1]]))
            else:
                authored_normals.extend(np.zeros((len(v),3)))
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
        provided=np.asarray(authored_normals)
        use=np.linalg.norm(provided,axis=1)>.5
        normal[use]=provided[use]
        normal /= np.linalg.norm(normal, axis=1)[:, None]
        tangent, handedness, mapped_tangents = surface_tangents(v, f, uv, normal)
        raw = bytearray(base64.b64decode(original["Exports"][0]["Extras"]))
        pos = np.zeros((N, 3), "<f4")
        tex = np.zeros((N, 2), "<f2")
        tan = np.zeros((N, 8), "i1")
        allocated = np.array(allocation)
        pos[allocated] = v
        tex[allocated] = uv
        tan[allocated, :3] = np.round(tangent * 127).astype("i1")
        tan[allocated, 3] = 127
        tan[allocated, 4:7] = np.round(normal * 127).astype("i1")
        tan[allocated, 7] = (handedness * 127).astype('i1')
        indices = np.zeros_like(ids)
        indices[: len(f)] = allocated[f]
        skin = native_skin.copy()
        for joint in [0, 1, 2]:
            skin[allocated[np.array(joints) == joint]] = joint_skin[joint]
        for key, array in [
            ("position", pos),
            ("uv", tex),
            ("tangent", tan),
            ("index", indices.astype("<u2")),
            ("skin", skin),
        ]:
            raw[OFF[key] : OFF[key] + array.nbytes] = array.tobytes()
        # Dense decorative meshes need float UVs: half precision visibly bends
        # patterns inside the backpack's very small native atlas island.
        full_uv = np.zeros((N, 2), "<f4")
        full_uv[allocated] = uv
        raw = precise_uv_buffer(raw, full_uv)
        result[label] = rename_mesh(copy.deepcopy(original), label, raw)
        np.savez(
            OUT / (label + "-expected.npz"),
            positions=pos,
            uv=full_uv,
            indices=indices,
            normals=normal,
            tangents=tangent,
            tangent_signs=handedness,
            mapped_tangents=mapped_tangents,
            allocated=allocated,
            joints=np.array(joints),
        )
        report["assets"][label] = {
            "vertices": len(v),
            "triangles": len(f),
            "parts": [x["name"] for x in batch],
            "materials": {x["name"]: x["mat"] for x in batch},
            "follows_shoulder_pose": any(joints),
            "authored_normal_parts": [x["name"] for x in batch if "normal" in x],
        }
        material = fixed.get(batch[0]["mat"], {}).get("asset")
        if material:
            report["assets"][label]["fixed_material"] = material
    report["front_components"] = list(report["assets"])
    # use the vanilla drone socket mesh with backpack palette UVs
    _, da, di = gltf(HERE / "exports/Slots/Content/new/slot_t1b_i.gltf")
    dv = da["POSITION"][:, [0, 2, 1]] * 100
    from drone_socket_fit import fit_socket
    casing_keep=model["keep"].copy()
    # Luxe replaces some original casing triangles with identical surface
    # patches. Restore those reference triangles for the contact measurement.
    replacements=json.loads(INFO.read_text()).get("native_replaced_triangles", [])
    casing_keep[np.asarray(replacements,dtype=int)]=True
    dv, fit_report = fit_socket(dv, p[ids[casing_keep]])
    (OUT / "drone-fit-report.json").write_text(json.dumps(fit_report, indent=2))
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
        source_vertices=da["POSITION"][:, [0, 2, 1]] * 100,
    )
    report["drone_palette"] = {
        "source": "vanilla slot_t1b_i; native backpack socket UV samples and shared dynamic material",
        "vertices": 337,
        "triangles": 312,
        "geometry_unchanged": False,
        "outer_back_edge_fitted_to_casing": True,
        "front_rim_and_inner_geometry_unchanged": True,
        "body_uv_unchanged": True,
        "live_only": True,
    }

    report["all_animated_triangles_preserved"] = bool(
        model["keep"][~np.all(np.isin(ids, root), axis=1)].all()
    )
    assert report["all_animated_triangles_preserved"]
    (OUT / "geometry-report.json").write_text(json.dumps(report, indent=2))
    return result, report

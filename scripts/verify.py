"""Check the cooked assets, slots, geometry and package."""

import base64
import copy
import hashlib
import json
import struct
import subprocess

import numpy as np
from asset_io import HERE, es, gltf, prop, ps, xyz
from auto_arm_items import ITEMS
from game_assets import ENV, GUI, REPAK, UMODEL
from settings import (
    AUTO_ARM_BLOCKER,
    MODEL_STYLE,
    OUT,
    PAK_NAME,
    PANEL_RETRACTION_FIX,
    VERSION,
)

STAGE = OUT / "staging"


def norm(x):
    if isinstance(x, float):
        return float(np.float32(x))
    if isinstance(x, str) and x in ["+0", "-0"]:
        return 0.0
    if isinstance(x, list):
        return [norm(a) for a in x]
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items()}
    return x


def vec(p):
    return np.array([float(xyz(p)[k]) for k in "XYZ"])


def type_(e):
    return e.get("$type", "").split(".")[-1].split(",")[0]


def size(e):
    t = type_(e)
    if t in [
        "EX_IntZero",
        "EX_Nothing",
        "EX_EndOfScript",
        "EX_Self",
        "EX_True",
        "EX_False",
    ]:
        return 1
    if t in ["EX_InstanceVariable", "EX_LocalVariable"]:
        return 9
    if t == "EX_NameConst":
        return 13
    if t in ["EX_FinalFunction", "EX_LocalFinalFunction"]:
        return 10 + sum(map(size, e["Parameters"]))
    if t == "EX_Context":
        assert e["Offset"] == size(e["ContextExpression"])
        return 13 + size(e["ObjectExpression"]) + size(e["ContextExpression"])
    if t == "EX_JumpIfNot":
        return 5 + size(e["BooleanExpression"])
    if t == "EX_Return":
        return 1 + size(e["ReturnExpression"])
    raise AssertionError(t)


assets = {}
for path in STAGE.rglob("*.uasset"):
    label = path.stem
    dest = OUT / f"verified-{label}.json"
    subprocess.run(
        [str(GUI), "--portable", "tojson", str(path), str(dest), "VER_UE4_27", "Astro"],
        env=ENV,
        check=True,
        timeout=90,
        capture_output=True,
    )
    d = json.loads(dest.read_text())
    expected = json.loads((OUT / (label + ".json")).read_text())
    assets[label] = d
    assert (
        d["Imports"] == expected["Imports"] and d["NameMap"] == expected["NameMap"]
    ), label
    assert len(d["Exports"]) == len(expected["Exports"])
    for a, b in zip(d["Exports"], expected["Exports"]):
        assert a["ObjectName"] == b["ObjectName"]
        for field in [
            "Data",
            "ScriptBytecode",
            "LoadedProperties",
            "FuncMap",
            "Children",
            "Extras",
        ]:
            assert norm(a.get(field)) == norm(b.get(field)), (
                label,
                a["ObjectName"],
                field,
            )
        if "FunctionExport" in a["$type"]:
            assert len(base64.b64decode(a["Extras"])) >= (
                10 if "FUNC_Net," in a["FunctionFlags"] else 8
            )
        for field in [
            "CreateBeforeSerializationDependencies",
            "SerializationBeforeSerializationDependencies",
            "CreateBeforeCreateDependencies",
            "SerializationBeforeCreateDependencies",
        ]:
            assert all(
                -len(d["Imports"]) <= v <= len(d["Exports"]) for v in a.get(field, [])
            )

geometry = json.loads((OUT / "geometry-report.json").read_text())
front_labels = geometry["front_components"]
positions = {}
resource_order = {}
for label, path, corpse in [
    ("BackpackRail", "Items/BackpackRail", False),
    ("AstroCorpse", "Character/AstroCorpse", True),
]:
    d = assets[label]
    original = json.loads(
        (HERE / "vanilla/Astro/Content" / path).with_suffix(".json").read_text()
    )
    ex, old = es(d), es(original)
    # Native behavior is untouched except extension of the resource array,
    # our material-sharing calls and the existing closed-printer speck correction.
    for n, e in old.items():
        if not e.get("ScriptBytecode"):
            continue
        expected = copy.deepcopy(e["ScriptBytecode"])
        actual = copy.deepcopy(ex[n]["ScriptBytecode"])
        added = 0
        if n == "UserConstructionScript":
            arrays = [
                x
                for x in actual
                if type_(x) == "EX_SetArray" and len(x["Elements"]) == 16
            ]
            assert len(arrays) == 1
            extra = arrays[0]["Elements"][8:]
            assert len(extra) == 8
            assert all(size(x) == 45 for x in extra)
            arrays[0]["Elements"] = arrays[0]["Elements"][:8]
            added = 360
        if n == "ReceiveBeginPlay":
            count = 1 if corpse else 2
            for _ in range(count):
                index = next(
                    i for i, expr in enumerate(actual) if type_(expr) == "EX_Return"
                )
                assert type_(actual.pop(index - 1)) == "EX_LocalFinalFunction"
            added = 10 * count
        if n == "CLIENT Printer View":
            from blueprint import replace_instruction
            from printer_tooltip import APPLY_OUTPUT

            # Only the two native output state requests are wrapped. Restore
            # them (and their jump offsets) before the byte-for-byte comparison.
            repaired = copy.deepcopy(ex[n])
            assert actual[47] == expected[47]
            for index, visible in [(81, False), (49, True)]:
                call = actual[index]
                assert type_(call) == "EX_LocalFinalFunction"
                assert d["Exports"][call["StackNode"] - 1]["ObjectName"] == APPLY_OUTPUT
                assert call["Parameters"][0] == expected[index]["ObjectExpression"]
                assert type_(call["Parameters"][1]) == (
                    "EX_True" if visible else "EX_False"
                )
                replace_instruction(repaired, index, copy.deepcopy(expected[index]))
            added += ex[n]["ScriptBytecodeSize"] - repaired["ScriptBytecodeSize"]
            actual = repaired["ScriptBytecode"]
            for i in [1, 7, 13]:
                expected[i]["Expression"]["Value"] = 0.001
            for i in [4, 10, 16]:
                expected[i]["Expression"]["Parameters"][1]["Value"] = 0.001
        assert norm(actual) == norm(expected), (label, n)
        assert ex[n]["ScriptBytecodeSize"] == e["ScriptBytecodeSize"] + added
    names = [
        ("ChildSlot" + (str(n) if n else "")) if corpse else f"Item Slot {n + 1}"
        for n in range(16)
    ]
    parent = "ItemSlots" if corpse else "Item Slots"
    origin = vec(ps(ex[parent + "_GEN_VARIABLE"])["RelativeLocation"])
    positions[label] = []
    for var in names:
        e = ex[var + "_GEN_VARIABLE"]
        p = ps(e)
        assert np.allclose(vec(p["RelativeScale3D"]), [0.2] * 3, atol=1e-7, rtol=0)
        assert not p["bVisible"]["Value"] and not p["SlotVisible"]["Value"]
        positions[label].append(vec(p["RelativeLocation"]) + origin)
        component_id = d["Exports"].index(e) + 1
        nodes = [
            x
            for x in d["Exports"]
            if ps(x).get("ComponentTemplate", {}).get("Value") == component_id
        ]
        assert len(nodes) == 1 and ps(nodes[0])["InternalVariableName"]["Value"] == var
        ni = d["Exports"].index(nodes[0]) + 1
        assert any(
            any(
                x.get("Value") == ni
                for x in ps(owner).get("ChildNodes", {}).get("Value", [])
            )
            for owner in d["Exports"]
        )
    assert len(np.unique(np.round(positions[label], 3), axis=0)) == 16
    code = ex["UserConstructionScript"]["ScriptBytecode"]
    refs = {}
    for op in code:
        expr = op.get("Expression", {})
        call = expr.get("ContextExpression", {})
        if (
            call.get("StackNode", 0) < 0
            and d["Imports"][-call["StackNode"] - 1]["ObjectName"] == "MakeReference"
            and call.get("Parameters")
        ):
            refs[op["Variable"]["Variable"]["New"]["Path"][0]] = call["Parameters"][0][
                "Value"
            ]
    array = next(
        x for x in code if type_(x) == "EX_SetArray" and len(x["Elements"]) == 16
    )
    resolved = []
    for x in array["Elements"]:
        if type_(x) == "EX_LocalVariable":
            resolved.append(refs[x["Variable"]["New"]["Path"][0]])
        else:
            resolved.append(x["ContextExpression"]["Parameters"][0]["Value"])
    assert resolved == names, (label, resolved)
    resource_order[label] = resolved
    expected_slots = copy.deepcopy(old["Slots_GEN_VARIABLE"]["Data"])
    if AUTO_ARM_BLOCKER and not corpse:
        for slot in ps({"Data": expected_slots})["Slots"]["Value"]:
            ps({"Data": slot["Value"]})["bAcceptsInputItems"]["Value"] = False
    assert ex["Slots_GEN_VARIABLE"]["Data"] == expected_slots
    # All auxiliary/template slot data stays byte-for-byte equivalent to vanilla.
    for component in old:
        if component.endswith("_GEN_VARIABLE") and any(
            word in component.lower() for word in ["aux", "drone"]
        ):
            expected_data = copy.deepcopy(old[component]["Data"])
            if component == "Creative Drone Slot_GEN_VARIABLE" and not corpse:
                match = next(
                    (q for q in expected_data if q["Name"] == "SlotVisible"), None
                )
                if match:
                    match["Value"] = False
                else:
                    expected_data.append(prop(d, "Bool", "SlotVisible", False))
            assert ex[component]["Data"] == expected_data, component
    for key in ["Power Bar_GEN_VARIABLE"] + (
        [] if corpse else ["PowerBarOverlay_GEN_VARIABLE"]
    ):
        p = ps(ex[key])
        assert np.allclose(vec(p["RelativeScale3D"])[:2], [0.09, 0.09])
        assert np.isclose(
            vec(p["RelativeLocation"])[0], geometry["battery_centre_native_x"]
        )
    if not corpse:
        for n in [
            "Printer Scene_GEN_VARIABLE",
            "Printer Head_GEN_VARIABLE",
            "Oxygen Bar_GEN_VARIABLE",
            "MissionLog_GEN_VARIABLE",
            "Catalog_GEN_VARIABLE",
            "CatalogCreative_GEN_VARIABLE",
        ]:
            assert ex[n]["Data"] == old[n]["Data"], n
    fn = ex["CB_ShareSocketMaterial"]
    assert sum(map(size, fn["ScriptBytecode"])) == fn["ScriptBytecodeSize"]
    assert all(
        x["CodeOffset"] == fn["ScriptBytecodeSize"] - 3
        for x in fn["ScriptBytecode"]
        if "CodeOffset" in x
    )
    assert sum(type_(x) == "EX_Context" for x in fn["ScriptBytecode"]) == 16 + len(
        front_labels
    ) + (0 if corpse else 2)
    if not corpse:
        comp = ex["NativeDroneSocket_GEN_VARIABLE"]
        p = ps(comp)
        native_slot = ps(old["Creative Drone Slot_GEN_VARIABLE"])
        assert np.allclose(vec(p["RelativeScale3D"]), 0.25)
        assert p["RelativeRotation"] == native_slot["RelativeRotation"]
        expected_loc = vec(native_slot["RelativeLocation"]) - vec(
            ps(old["backpack_mk2_GEN_VARIABLE"])["RelativeLocation"]
        )
        expected_loc[1] -= 0.75
        assert np.allclose(vec(p["RelativeLocation"]), expected_loc, atol=1e-6)
        ci = d["Exports"].index(comp) + 1
        node = next(
            x
            for x in d["Exports"]
            if ps(x).get("ComponentTemplate", {}).get("Value") == ci
        )
        ni = d["Exports"].index(node) + 1
        rootnode = next(
            x
            for x in d["Exports"]
            if ps(x).get("InternalVariableName", {}).get("Value") == "backpack_mk2"
        )
        assert any(x["Value"] == ni for x in ps(rootnode)["ChildNodes"]["Value"])
        calls = [x for x in fn["ScriptBytecode"] if type_(x) == "EX_Context"]
        assert calls[-1]["ObjectExpression"]["Variable"]["New"]["Path"] == [
            "NativeDroneSocket"
        ]
        assert not p["bVisible"]["Value"]
        assert p["bUseAttachParentBound"]["Value"]
    for n in [f"NativeBackpackSocket{i}" for i in range(1, 17)] + [
        "Compact_" + label for label in front_labels
    ]:
        component = ex[n + "_GEN_VARIABLE"]
        p = ps(component)
        assert np.allclose(
            vec(p["RelativeScale3D"]), 0.88 if n.startswith("Native") else 1.0
        )
        fields = {x["Name"]: x for x in p["BodyInstance"]["Value"]}
        assert (
            fields["CollisionEnabled"]["EnumValue"] == "ECollisionEnabled::NoCollision"
        )
distances = np.linalg.norm(
    np.array(positions["BackpackRail"])[:, None, :]
    - np.array(positions["AstroCorpse"])[None, :, :],
    axis=2,
)
assert np.all(distances.min(1) < 1e-4) and len(set(distances.argmin(1))) == 16

# Independent UE Viewer re-exports verify that the serialized vertex/index buffers
# describe the intended shape, normals, palette UVs and root-only skinning.
umodel = UMODEL
original, oa, oi = gltf(HERE / "exports/Models/backpack_mk2/backpack_mk2.gltf")
# Compare cooked triangles with the model file.
from model import MODEL

approved_path = MODEL
blob = approved_path.read_bytes()
jsize = struct.unpack_from("<I", blob, 12)[0]
approved = json.loads(blob[20 : 20 + jsize])
start = 20 + jsize + 8
approved_parts = {}
for mesh in approved["meshes"]:
    accessor = approved["accessors"][mesh["primitives"][0]["attributes"]["POSITION"]]
    view = approved["bufferViews"][accessor["bufferView"]]
    q = (
        np.frombuffer(
            blob,
            "<f4",
            count=accessor["count"] * 3,
            offset=start + view.get("byteOffset", 0) + accessor.get("byteOffset", 0),
        ).reshape(-1, 3)
        * 100
    )
    approved_parts[mesh["name"]] = np.column_stack(
        [1.46842727662 - q[:, 2], q[:, 0], q[:, 1] - 51]
    ).reshape(-1, 3, 3)
for label in ["backpack_mk2", "backpack_socket", "drone_socket"] + front_labels:
    subprocess.run(
        [
            str(umodel),
            "-export",
            "-gltf",
            "-noanim",
            "-game=ue4.27",
            "-path=" + str(STAGE),
            "-out=" + str(OUT / "mesh-check"),
            label + ".uasset",
        ],
        check=True,
        timeout=60,
        capture_output=True,
    )
    gd, a, indices = gltf(OUT / f"mesh-check/Mods/CompactBackpack16/{label}.gltf")
    nodes = copy.deepcopy(gd["nodes"])
    nodes[0]["name"] = original["nodes"][0]["name"]
    assert nodes == original["nodes"] and gd["skins"] == original["skins"]
    if label.startswith("front"):
        expected = np.load(OUT / (label + "-expected.npz"))
        wanted = expected["indices"]
        active = (wanted[:, 0] != wanted[:, 1]) & (wanted[:, 1] != wanted[:, 2])
        assert np.array_equal(
            (indices[:, 0] != indices[:, 1]) & (indices[:, 1] != indices[:, 2]), active
        )
        # UE Viewer compacts unused vertices, so compare triangle attributes.
        assert np.allclose(
            a["POSITION"][indices[active]][:, :, [0, 2, 1]] * 100,
            expected["positions"][wanted[active]],
            atol=2e-5,
        )
        reference = np.concatenate(
            [approved_parts[name] for name in geometry["assets"][label]["parts"]]
        )
        assert np.allclose(
            a["POSITION"][indices[active]][:, :, [0, 2, 1]] * 100,
            reference,
            atol=3e-5,
            rtol=0,
        ), "cooked mesh doesn't match the selected model"
        assert np.array_equal(
            a["TEXCOORD_0"][indices[active]], expected["uv"][wanted[active]]
        )
        used = np.unique(indices)
        assert np.all((a["JOINTS_0"][used] == 0) | (a["WEIGHTS_0"][used] == 0))
        normal = np.zeros_like(expected["positions"])
        normal[expected["allocated"]] = expected["normals"]
        assert np.allclose(
            a["NORMAL"][indices[active]][:, :, [0, 2, 1]],
            normal[wanted[active]],
            atol=0.009,
        )
    elif label == "backpack_mk2":
        expected = np.load(OUT / "body-expected.npz")
        keep = expected["keep"]
        for k in oa:
            expected_attr = expected["uv"] if k == "TEXCOORD_0" else oa[k]
            assert np.array_equal(a[k][indices[keep]], expected_attr[oi[keep]]), k
        changed = np.any(expected["uv"] != oa["TEXCOORD_0"], axis=1)
        assert not changed.any(), "Native body UVs must remain unchanged"
        animated = ~np.all(
            (oa["JOINTS_0"][oi] == 0) | (oa["WEIGHTS_0"][oi] == 0), axis=(1, 2)
        )
        assert animated.sum() == 2380 and keep[animated].all()
    elif label == "drone_socket":
        expected = np.load(OUT / "drone-expected.npz")
        wanted = expected["indices"][:312]
        _, da, di = gltf(HERE / "exports/Slots/Content/new/slot_t1b_i.gltf")
        active = (indices[:, 0] != indices[:, 1]) & (indices[:, 1] != indices[:, 2])
        assert active.sum() == 312
        assert np.allclose(
            a["POSITION"][indices[active]], da["POSITION"][di], atol=2e-7, rtol=0
        )
        assert np.allclose(a["NORMAL"][indices[active]], da["NORMAL"][di], atol=0.009)
        assert np.array_equal(a["TEXCOORD_0"][indices[active]], expected["uv"][wanted])
        rim = da["TEXCOORD_0"][:, 0] > 0.2
        assert rim.sum() == 160
        assert np.all(
            expected["uv"][expected["allocated"][rim]]
            == np.array(geometry["atlas_uv"]["red"], dtype="<f2").astype("f4")
        )
        assert np.all(
            (a["JOINTS_0"][indices[active]] == 0)
            | (a["WEIGHTS_0"][indices[active]] == 0)
        )
    else:
        info = json.loads((OUT / "socket-source.json").read_text())
        sel = np.array(info["triangles"])
        for k in ["TEXCOORD_0", "NORMAL", "TANGENT", "JOINTS_0", "WEIGHTS_0"]:
            assert np.array_equal(a[k][indices[sel]], oa[k][oi[sel]])

pak = OUT / PAK_NAME
listing = subprocess.check_output(
    [str(REPAK), "list", str(pak)], text=True
).splitlines()
expected = sorted(
    p.relative_to(STAGE).as_posix() for p in STAGE.rglob("*") if p.is_file()
)
assert (
    sorted(listing) == expected
    and len(listing)
    == 2
    * (
        11
        + len(front_labels)
        + int(PANEL_RETRACTION_FIX)
        + (2 + len(ITEMS)) * int(AUTO_ARM_BLOCKER)
    )
    + 1
)
for member in listing:
    data = subprocess.check_output([str(REPAK), "get", str(pak), member])
    assert data == (STAGE / member).read_bytes(), member
report = json.loads((OUT / "build-report.json").read_text())
assert report["model_style"] == MODEL_STYLE
assert hashlib.sha256(pak.read_bytes()).hexdigest() == report["pak_sha256"]
report["offline_checks"] = [
    f"{len(assets)} assets reparsed including function trailers and dependencies",
    "vanilla bytecode preserved except declared changes",
    "sixteen unique slot references and registered components on live and death backpacks",
    "80% main items (.2 component scale); auxiliary slots unchanged",
    "matching live and corpse attachment positions",
    "original control and printer transforms retained",
    "material helper bytecode and offsets verified",
    f"cooked geometry matches the selected {MODEL_STYLE} model; original body UVs unchanged",
    "new visible meshes root weighted and collision disabled",
    "all 2380 animated native triangles preserved",
    "actual native drone mount shape and normals retained; its rim uses main socket palette UV and material",
    f"{len(listing)} PAK entries independently extracted and byte matched",
]
report["resource_order"] = resource_order
from verify_behaviors import check_behaviors

report["offline_checks"].extend(check_behaviors(assets, geometry))
from verify_printer import check_printer

report["offline_checks"].extend(check_printer(assets))
from verify_panel_retraction import check_panel_retraction

report["offline_checks"].extend(check_panel_retraction(assets))
from verify_preferences import check_preferences

report["offline_checks"].extend(check_preferences(assets))
report["printer_preference_verified"] = True
report["printer_tooltip_verified"] = True
from verify_auto_arm import check_auto_arm

report["offline_checks"].extend(check_auto_arm(assets))
from verify_auto_arm_items import check_equipment

report["offline_checks"].extend(check_equipment(assets))
report["auto_arm_verified"] = AUTO_ARM_BLOCKER
from verify_visual_events import check_visual_events

report["offline_checks"].extend(check_visual_events(assets, geometry))
report["event_visuals_verified"] = True
from verify_build_options import check_build_options

report["offline_checks"].extend(check_build_options())
report["build_options_verified"] = True
from verify_vehicle_visuals import check_vehicle_visuals

report["offline_checks"].extend(check_vehicle_visuals(assets, geometry))
report["vehicle_visuals_verified"] = True
(OUT / "build-report.json").write_text(json.dumps(report, indent=2))
print(f"{VERSION}: {len(report['offline_checks'])} offline checks passed.")

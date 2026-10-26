"""Checks for luxe glow, geometry and native surface mapping."""

import hashlib
import json
import struct

import numpy as np
from accent_glow import MATERIAL, REFRESH
from asset_io import HERE, es, gltf
from game_assets import PAK
from kismet import kismet_size, op_type
from model import INFO, load_model
from settings import GLOW_TEST, PKG
from verify_behaviors import VM


class GlowVM(VM):
    def __init__(self, document, actor):
        super().__init__(document, actor)
        self.creations = 0

    def eval(self, expression, obj, local):
        kind = op_type(expression)
        if kind == "EX_ObjectConst":
            return {"asset": self.d["Imports"][-expression["Value"] - 1]["ObjectName"]}
        if kind in ["EX_FinalFunction", "EX_CallMath"] and expression["StackNode"] < 0:
            name = self.d["Imports"][-expression["StackNode"] - 1]["ObjectName"]
            args = [self.eval(p, obj, local) for p in expression["Parameters"]]
            if name == "GetBaseMaterial":
                return {"name": obj.get("base_name", "palette_exo_suits_master")}
            if name == "GetObjectName":
                return args[0]["name"]
            if name == "NotEqual_StriStri":
                return args[0].lower() != args[1].lower()
            if name == "CreateDynamicMaterialInstance":
                assert args[0] == 0 and args[1]["asset"] == "LowerBatteryGlow"
                self.creations += 1
                result = {
                    "material_class": "MaterialInstanceDynamic",
                    "parameters": {},
                    "creation": self.creations,
                }
                obj["material"] = result
                return result
            if name == "K2_GetVectorParameterValue":
                return obj["parameters"][args[0]]
            if name == "SetVectorParameterValue":
                obj["parameters"][args[0]] = args[1]
                return
            if name == "Multiply_LinearColorFloat":
                return tuple(v * args[1] for v in args[0])
        return super().eval(expression, obj, local)

    def run(self, name, args=()):
        if name != REFRESH:
            return super().run(name, args)
        function = es(self.d)[name]
        code = function["ScriptBytecode"]
        starts = {}
        position = 0
        for i, instruction in enumerate(code):
            starts[position] = i
            position += kismet_size(instruction)
        local = {"Source": None, "Tint": None}
        pc = 0
        for _ in range(100):
            instruction = code[pc]
            kind = op_type(instruction)
            if kind == "EX_Return":
                return
            if (
                kind == "EX_Jump"
                or kind == "EX_JumpIfNot"
                and not self.eval(instruction["BooleanExpression"], self.actor, local)
            ):
                pc = starts[instruction["CodeOffset"]]
            else:
                if kind != "EX_JumpIfNot":
                    self.eval(instruction, self.actor, local)
                pc += 1
        raise AssertionError("Accent helper did not finish")


def check_native_bindings(document):
    manifest = json.loads((HERE / "accent-glow-native.json").read_text())
    exe = PAK.parents[2] / "Binaries/Win64/Astro-Win64-Shipping.exe"
    raw = exe.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["exe_sha256"]
    pe = struct.unpack_from("<I", raw, 0x3C)[0]
    base = struct.unpack_from("<Q", raw, pe + 48)[0]
    count = struct.unpack_from("<H", raw, pe + 6)[0]
    optional = struct.unpack_from("<H", raw, pe + 20)[0]
    sections = [
        struct.unpack_from("<IIII", raw, pe + 24 + optional + 40 * i + 8)
        for i in range(count)
    ]

    def offset(rva):
        _, start, _, location = next(s for s in sections if s[1] <= rva < s[1] + s[0])
        return location + rva - start

    for item in manifest["functions"]:
        at = offset(int(item["name_pointer_rva"], 16))
        pointer = struct.unpack_from("<Q", raw, at)[0] - base
        start = offset(pointer)
        end = raw.index(b"\0", start)
        assert raw[start:end].decode() == item["function"]
        assert struct.unpack_from("<Q", raw, at - 16)[0] - base == int(
            item["owner_getter_rva"], 16
        )
        matches = [
            i
            for i in document["Imports"]
            if i["ObjectName"] == item["function"]
            and document["Imports"][-i["OuterIndex"] - 1]["ObjectName"] == item["owner"]
        ]
        assert len(matches) == 1, item


def check_glow(assets, geometry):
    if not GLOW_TEST:
        return []
    for label in ["BackpackRail", "AstroCorpse"]:
        document = assets[label]
        check_native_bindings(document)
        field = next(
            p
            for e in document["Exports"]
            if "ClassExport" in e["$type"]
            for p in e["LoadedProperties"]
            if p["Name"] == MATERIAL
        )
        assert field["PropertyFlags"] == "CPF_Transient"
        target = "Compact_" + next(
            n
            for n, v in geometry["assets"].items()
            if v.get("fixed_material") == PKG + "LowerBatteryGlow"
        )
        mesh = "Backpack_mk2" if label == "AstroCorpse" else "backpack_mk2"

        def source(
            rgb, kind="MaterialInstanceConstant", base="palette_exo_suits_master"
        ):
            return {
                "material_class": kind,
                "base_name": base,
                "parameters": {"PrimaryColor": rgb},
            }

        initial = source((0.2, 0.4, 0.7, 1.0))
        actor = {mesh: {"material": initial}, target: {"material": object()}}
        vm = GlowVM(document, actor)
        vm.run(REFRESH)
        glow = actor[MATERIAL]
        assert glow is actor[target]["material"] and vm.creations == 1
        assert glow["parameters"]["Color Tint"] == initial["parameters"]["PrimaryColor"]
        assert np.allclose(
            glow["parameters"]["Emissive Tint"],
            (0.22, 0.44, 0.77, 1.1),
            rtol=0,
            atol=1e-7,
        )
        for _ in range(100):
            vm.run(REFRESH)
        assert vm.creations == 1 and actor[MATERIAL] is glow and not vm.timers
        for kind in ["MaterialInstanceConstant", "MaterialInstanceDynamic"]:
            for colour in [(0.0, 0.0, 0.0, 1.0), (0.9, 0.1, 0.4, 1.0)]:
                actor[mesh]["material"] = source(colour, kind)
                vm.run(REFRESH)
                assert glow["parameters"]["Color Tint"] == colour
                assert np.allclose(
                    glow["parameters"]["Emissive Tint"],
                    tuple(v * 1.1 for v in colour),
                    rtol=0,
                    atol=1e-7,
                )
                assert vm.creations == 1
        rainbow = source((0, 0, 0, 1), base="M_suits_rainbow")
        rainbow["parameters"] = {}
        actor[mesh]["material"] = rainbow
        vm.run(REFRESH)
        assert actor[target]["material"] is rainbow and vm.creations == 1
        actor[mesh]["material"] = initial
        vm.run(REFRESH)
        assert actor[target]["material"] is glow and vm.creations == 1
        actor[mesh]["material"] = None
        vm.run(REFRESH)
        actor[target] = None
        vm.run(REFRESH)
        assert not vm.timers
    # Independent native UV interpolation check, not just an export round trip.
    current = load_model()
    _, native, native_indices = gltf(
        HERE / "exports/Models/backpack_mk2/backpack_mk2.gltf"
    )
    native_position = native["POSITION"][:, [0, 2, 1]] * 100
    world = np.column_stack(
        [
            native_position[:, 1] / 100,
            (native_position[:, 0] - 1.46842727662) / 100,
            (native_position[:, 2] + 51) / 100,
        ]
    )
    surfaces = []
    for index in [3002, 3004]:
        ids = native_indices[index]
        surfaces.append((world[ids][:, [0, 2]], native["TEXCOORD_0"][ids]))
    for part in current["parts"]:
        if "uv" not in part:
            continue
        if (
            part["name"].startswith("LuxeOxygenSupportBand_")
            or part["name"] == "LuxeRearStripeShellSurface"
        ):
            continue
        assert part["name"] in ["LuxeRearShellSurface", "LuxeYUEEngravingShell"]
        for p, uv in zip(part["v"], part["uv"]):
            choices = []
            for tri, source_uv in surfaces:
                weights = np.linalg.solve(
                    np.vstack([tri.T, np.ones(3)]),
                    np.array([p[0] / 100, p[1] / 100, 1]),
                )
                choices.append((min(weights), weights @ source_uv))
            score, expected = max(choices, key=lambda x: x[0])
            assert score > -0.00002 and np.allclose(uv, expected, atol=2e-7, rtol=0)
    info = json.loads(INFO.read_text())
    assert len(info["native_replaced_triangles"]) == 187
    assert not any(p["name"] == "LuxeYUEEngravingShell" for p in current["parts"]), (
        "Separate engraving insert returned"
    )
    # Border, Morse, row and side comparisons have separate static bindings.
    materials = {p["name"]: p["mat"] for p in current["parts"]}
    for name, material in materials.items():
        if name.startswith("LuxePadInlay_"):
            assert material == "Luxe stars gold", (name, material)
        elif name.startswith(("LuxePadStar_", "LuxePadDiamond_")):
            expected = "Luxe ornaments gold"
            assert material == expected, (name, material)
    assert materials["LuxeYueMorse"] == "Luxe Morse gold glow test"
    assert materials["LuxeYueMorsePolished"] == "Luxe Morse polished gold glow test"
    assert (
        np.mean(
            next(p for p in current["parts"] if p["name"] == "LuxeYueMorse")["v"][:, 0]
        )
        < 0
    )
    assert (
        min(
            next(p for p in current["parts"] if p["name"] == "LuxeYueMorsePolished")[
                "v"
            ][:, 0]
        )
        > 0
    )
    icon = next(p for p in current["parts"] if p["name"] == "LowerBatteryAccent")
    assert len(icon["f"]) == 60, "Flat power icon silhouette/extrusion changed"
    span = np.ptp(icon["v"], axis=0)
    assert abs(span[0] - 4.6) < 1e-4 and abs(span[1] - 6.64125) < 1e-4
    assert icon["mat"] == "Luxe accent glow test"
    assert materials["LuxeYUEEngravingGoldWalls"] == "Luxe stars gold"
    # Flat visible face planes; hidden backing intersects the native cylinder.
    casing = next(p for p in current["parts"] if p["name"] == "BatteryBottomCasing")
    casing_centre = (casing["v"][:, 1].min() + casing["v"][:, 1].max()) / 2
    for name in ["LowerBatteryAccentMount", "LowerBatteryAccent"]:
        part = next(p for p in current["parts"] if p["name"] == name)
        centre = (part["v"][:, 1].min() + part["v"][:, 1].max()) / 2
        assert abs(centre - casing_centre) < 1e-5
    assert len(np.unique(np.round(icon["v"][:, 2], 5))) == 2
    assert abs(np.ptp(icon["v"][:, 2]) - 0.6) < 1e-5
    reference = json.loads((HERE / "mission-handle-reference.json").read_text())
    mesh_path = (
        HERE
        / "vanilla/Astro/Content/Animations/ControlPanels/ControlPanelMission/ControlPanelMissionBackpack_skinned.uexp"
    )
    assert (
        hashlib.sha256(mesh_path.read_bytes()).hexdigest()
        == reference["source_uexp_sha256"]
    )
    for part in current["parts"]:
        if not part["name"].startswith("LuxeOxygenSupportBand_"):
            continue
        assert part["mat"] == "handle_accent" and "uv" in part
        uv = part["uv"]
        assert len(np.unique(uv, axis=0)) > 100, "Band UVs collapsed to one sample"
        assert np.allclose(uv.min(0), reference["uv0_min"], atol=1e-7, rtol=0)
        assert np.allclose(uv.max(0), reference["uv0_max"], atol=1e-7, rtol=0)
        tri = uv[part["f"]]
        a = tri[:, 1] - tri[:, 0]
        b = tri[:, 2] - tri[:, 0]
        twice_area = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
        assert np.count_nonzero(twice_area > 1e-10) > len(tri) * 0.9
    assert materials["LuxeElbowStar_-1"] == "Luxe ornaments gold"
    assert materials["LuxeElbowMoon_1"] == "Luxe ornaments gold"
    stripe_reference = json.loads((HERE / "rear-stripe-reference.json").read_text())
    assert (
        info["native_replaced_triangles"] == stripe_reference["all_native_replacements"]
    )
    source_mesh = HERE / "vanilla/Astro/Content/Models/backpack_mk2/backpack_mk2.uexp"
    assert (
        hashlib.sha256(source_mesh.read_bytes()).hexdigest()
        == stripe_reference["source_mesh_uexp_sha256"]
    )
    selected = stripe_reference["new_native_replacements"]
    source_triangles = [
        (world[native_indices[i]], native["TEXCOORD_0"][native_indices[i]])
        for i in selected
    ]
    stripe = next(p for p in current["parts"] if p["name"] == "LuxeRearCasingStripe")
    assert stripe["mat"] == "Luxe ornaments gold"
    assert stripe["v"][:, 0].min() < -50 and stripe["v"][:, 0].max() > 50
    assert stripe["v"][:, 2].max() > 0, "Stripe does not reach the side front edges"
    assert np.all(stripe["v"][:, 1] / 100 >= stripe_reference["low_z"] - 1e-6)
    assert np.all(stripe["v"][:, 1] / 100 <= stripe_reference["high_z"] + 1e-6)
    assert abs(np.ptp(stripe["v"][:, 1]) / 100 - 0.018) < 1e-6
    assert abs(stripe["v"][:, 1].min() / 100 - 0.3322991728782654) < 1e-6, (
        "Gap above native blue band"
    )

    # Every restored surface point remains on an original triangle with its
    # original UV. Gold stripe vertices are equally coplanar, without an offset.
    for part in current["parts"]:
        if part["name"] not in ("LuxeRearStripeShellSurface", "LuxeRearCasingStripe"):
            continue
        candidates = source_triangles + [
            (world[native_indices[i]], native["TEXCOORD_0"][native_indices[i]])
            for i in [3002, 3004]
        ]
        for j, p in enumerate(part["v"]):
            point = np.array([p[0] / 100, -p[2] / 100, p[1] / 100])
            choices = []
            for tri, uv in candidates:
                weights = np.linalg.lstsq(
                    np.vstack([tri.T, np.ones(3)]), np.r_[point, 1.0], rcond=None
                )[0]
                if np.linalg.norm(weights @ tri - point) < 2e-6:
                    choices.append((min(weights), weights @ uv))
            assert choices and max(c[0] for c in choices) > -3e-5
            if part["name"] == "LuxeRearStripeShellSurface":
                assert any(
                    score > -3e-5
                    and np.allclose(part["uv"][j], expected, atol=2e-7, rtol=0)
                    for score, expected in choices
                )

    # Gold is restricted to straight vertical engraving walls.
    walls = next(
        p for p in current["parts"] if p["name"] == "LuxeYUEEngravingGoldWalls"
    )
    triangles = walls["v"][walls["f"]]
    normals = np.cross(
        triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    )
    assert np.all(np.abs(normals[:, 2]) < 1e-8)
    surface = next(p for p in current["parts"] if p["name"] == "LuxeRearShellSurface")
    assert len(np.unique(np.round(surface["v"][:, 2], 5))) > 5, (
        "Rounded casing-colour lip missing"
    )
    assert (
        sum(
            len(p["f"])
            for p in current["parts"]
            if p["name"] in ("LuxeYueMorse", "LuxeYueMorsePolished")
        )
        == 336
    )
    return [
        "glow material parameters and native function owners verified against the installed executable",
        "accent glow simulated through both palette material types, black colour, rainbow fallback, missing references and 100 refreshes without new material allocation or timers",
        "unified preferred gold, flat inset badge and unchanged borders verified; approved lower-poly Morse on both sides (180 + 156 triangles), taller centred badge and integrated rear/side stripe",
        "rear surround and engraving floors retain native UVs; oxygen bands use noncollapsed mission-handle atlas UVs",
    ]

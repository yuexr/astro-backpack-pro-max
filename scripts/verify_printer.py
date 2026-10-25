"""check the info button, tooltip toggle and printer meshes"""

import copy
import json
import subprocess

import numpy as np
from asset_io import HERE, es, gltf, ps, xyz
from game_assets import UMODEL
from kismet import kismet_size, op_type
from printer_hover import CLICKABLE_CHANNEL, HOVER_COLLIDER, SYNC_HOVER
from printer_tooltip import APPLY_OUTPUT, BUTTON, GET_HIDDEN, HIDDEN, TOGGLE
from settings import OUT, PRINTER_ICON_SCALE
from verify_behaviors import VM


class PrinterVM(VM):
    def __init__(self, document, actor):
        super().__init__(document, actor)
        actor.setdefault(HOVER_COLLIDER, None)
        actor.setdefault("collision_requests", [])
        actor.setdefault("response_requests", [])

    def run(self, name, args=()):
        # Existing printer checks isolate the visual toggle from persistence;
        # verify_preferences exercises the save/load helpers and the getter.
        from printer_preferences import LOAD, SAVE

        if name in [LOAD, SAVE]:
            return
        if name in [APPLY_OUTPUT, SYNC_HOVER]:
            function = es(self.d)[name]
            local = {
                p["Name"]: value for p, value in zip(function["LoadedProperties"], args)
            }
            offsets = {}
            offset = 0
            for index, expression in enumerate(function["ScriptBytecode"]):
                offsets[offset] = index
                offset += kismet_size(expression)
            assert offset == function["ScriptBytecodeSize"]
            index = 0
            while True:
                expression = function["ScriptBytecode"][index]
                kind = op_type(expression)
                if kind == "EX_Return":
                    return
                if kind == "EX_Jump" or (
                    kind == "EX_JumpIfNot"
                    and not self.eval(
                        expression["BooleanExpression"], self.actor, local
                    )
                ):
                    index = offsets[expression["CodeOffset"]]
                    continue
                if kind != "EX_JumpIfNot":
                    self.eval(expression, self.actor, local)
                index += 1
        return super().run(name, args)

    def native_view(self):
        self.actor["native_view_calls"] += 1
        if self.actor["output"] is None:
            return
        self.actor["output"].setdefault("InputRespondingCollider", {"collision": 0})
        code = next(
            e for e in self.d["Exports"] if e["ObjectName"] == "CLIENT Printer View"
        )["ScriptBytecode"]
        show = self.eval(code[47]["AssignmentExpression"], self.actor, {})
        self.eval(
            code[49 if show else 81],
            self.actor,
            {"PrinterOutputSlotTooltipComponent": self.actor["output"]},
        )

    def eval(self, x, obj, local):
        kind = op_type(x)
        if kind == "EX_NoObject":
            return None
        if kind == "EX_LetObj":
            self.set(
                x["VariableExpression"],
                self.eval(x["AssignmentExpression"], obj, local),
                obj,
                local,
            )
            return
        if kind == "EX_ByteConst":
            return x["Value"]
        if kind in ["EX_CallMath", "EX_FinalFunction", "EX_LocalFinalFunction"]:
            node = x["StackNode"]
            fn = (
                self.d["Imports"][-node - 1]["ObjectName"]
                if node < 0
                else self.d["Exports"][node - 1]["ObjectName"]
            )
            args = [self.eval(arg, obj, local) for arg in x["Parameters"]]
            if fn == "IsLocallyControlled":
                return self.actor["local"]
            if fn == "Not_PreBool":
                return not args[0]
            if fn == "BooleanAND":
                return args[0] and args[1]
            if fn == "EqualEqual_ObjectObject":
                return args[0] is args[1]
            if fn == "EqualEqual_ByteByte":
                return args[0] == args[1]
            if fn == "GetCollisionEnabled":
                return obj["collision"]
            if fn == "SetCollisionEnabled":
                assert args[0] in [0, 1], "hover must never enable physics"
                obj["collision"] = args[0]
                self.actor["collision_requests"].append((obj, args[0]))
                return
            if fn == "GetCollisionResponseToChannel":
                assert args == [CLICKABLE_CHANNEL]
                return obj.get("responses", {}).get(CLICKABLE_CHANNEL, 0)
            if fn == "SetCollisionResponseToChannel":
                assert args[0] == CLICKABLE_CHANNEL
                obj.setdefault("responses", {})[args[0]] = args[1]
                self.actor["response_requests"].append((obj, *args))
                return
            if fn == "GetIndicatorTooltipForSlot":
                assert args[0] is self.actor["Printer Output Slot"] and args[1] == 0
                return self.actor["output"]
            if fn == "SetDesiredTooltipState":
                obj["state"] = args[0]
                self.actor["state_requests"].append(args[0])
                return
            if fn == "GetHasFocus":
                return obj.get("focus", False)
            if fn == "CLIENT Printer View":
                return self.native_view()
            if kind == "EX_CallMath":
                x = copy.deepcopy(x)
                x["$type"] = x["$type"].replace("EX_CallMath", "EX_FinalFunction")
        return super().eval(x, obj, local)


class PressVM(VM):
    def __init__(self, asset, actor, backpack_vm):
        super().__init__(asset, actor)
        self.backpack_vm = backpack_vm
        self.sounds = []

    def eval(self, x, obj, local):
        kind = op_type(x)
        if kind == "EX_ObjectConst":
            return self.d["Imports"][-x["Value"] - 1]["ObjectName"]
        if kind == "EX_Let":
            local[self.name(x["Variable"]["Variable"])] = self.eval(
                x["Expression"], obj, local
            )
            return
        if kind == "EX_VirtualFunction":
            assert (
                x["VirtualFunctionName"] in [TOGGLE, GET_HIDDEN]
                and obj is self.actor["parent"]
            )
            return self.backpack_vm.run(x["VirtualFunctionName"])
        if kind in ["EX_FinalFunction", "EX_CallMath"] and x["StackNode"] < 0:
            name = self.d["Imports"][-x["StackNode"] - 1]["ObjectName"]
            if name == "SelectString":
                args = [self.eval(p, obj, local) for p in x["Parameters"]]
                return args[0] if args[2] else args[1]
            if name == "GetAttachParentActor":
                return self.actor["parent"]
            if name == "PostEvent":
                assert obj == "Default__AstroAudioStatics"
                args = [self.eval(p, obj, local) for p in x["Parameters"]]
                self.sounds.append(args)
                return 123
        return super().eval(x, obj, local)


def check_printer(assets):
    backpack = assets["BackpackRail"]
    exports = es(backpack)
    cls = exports["BackpackRail_C"]
    field = next(p for p in cls["LoadedProperties"] if p["Name"] == HIDDEN)
    assert field["PropertyFlags"] == "CPF_None"
    assert ps(exports["Default__BackpackRail_C"])[HIDDEN]["Value"] is False
    assert "BPM_ApplyPrinterTooltip" not in exports
    getter = exports[GET_HIDDEN]
    assert "FUNC_Net" not in getter["FunctionFlags"]
    assert getter["LoadedProperties"][0]["Name"] == "ReturnValue"
    assert "CPF_ReturnParm" in getter["LoadedProperties"][0]["PropertyFlags"]
    assert (
        sum(map(kismet_size, getter["ScriptBytecode"])) == getter["ScriptBytecodeSize"]
    )
    apply = exports[APPLY_OUTPUT]
    assert "FUNC_Net" not in apply["FunctionFlags"]
    assert [p["Name"] for p in apply["LoadedProperties"]] == [
        "OutputTooltip",
        "OutputVisible",
    ]
    assert all(p["PropertyFlags"] == "CPF_Parm" for p in apply["LoadedProperties"])
    view = exports["CLIENT Printer View"]
    assert sum(map(kismet_size, view["ScriptBytecode"])) == view["ScriptBytecodeSize"]
    for label in [TOGGLE]:
        function = exports[label]
        assert "FUNC_Net" not in function["FunctionFlags"]
        assert function["LoadedProperties"] == []
        assert (
            sum(map(kismet_size, function["ScriptBytecode"]))
            == function["ScriptBytecodeSize"]
        )

    def fresh(local=True):
        return {
            HIDDEN: False,
            "local": local,
            "Printer Output Slot": object(),
            "output": {"state": 2},
            "PrinterVisible": True,
            "REP_ShowPrinterOutputSlotTooltip": True,
            "native_view_calls": 0,
            "state_requests": [],
        }

    actor = fresh()
    vm = PrinterVM(backpack, actor)
    vm.native_view()
    assert actor["output"]["state"] == 2
    for i in range(6):
        vm.run(TOGGLE)
        assert actor[HIDDEN] == (i % 2 == 0)
        assert actor["output"]["state"] == (0 if actor[HIDDEN] else 2)
    assert actor["native_view_calls"] == 7
    # Native indicator meshes start with collision disabled. Arm once per
    # hologram, restore on toggle/close, and never change slot clickability.
    hover = fresh()
    hover[HIDDEN] = True
    hover_vm = PrinterVM(backpack, hover)
    hover_vm.native_view()
    first = hover["output"]["InputRespondingCollider"]
    assert first["collision"] == 1 and hover[HOVER_COLLIDER] is first
    assert first["responses"][CLICKABLE_CHANNEL] == 2
    for _ in range(100):
        hover_vm.native_view()
    assert hover["collision_requests"] == [(first, 1)]
    assert hover["response_requests"] == [(first, CLICKABLE_CHANNEL, 2)]
    second = {"collision": 0}
    hover["output"]["InputRespondingCollider"] = second
    hover_vm.native_view()
    assert first["collision"] == 0 and second["collision"] == 1
    assert first["responses"][CLICKABLE_CHANNEL] == 0
    assert second["responses"][CLICKABLE_CHANNEL] == 2
    hover["PrinterVisible"] = False
    hover_vm.native_view()
    assert second["collision"] == 0 and hover[HOVER_COLLIDER] is None
    assert second["responses"][CLICKABLE_CHANNEL] == 0
    hover["PrinterVisible"] = True
    hover_vm.native_view()
    hover_vm.run(TOGGLE)
    assert second["collision"] == 0 and hover[HOVER_COLLIDER] is None
    for native_collision in [1, 2, 3]:
        hover[HIDDEN] = True
        hover["output"]["InputRespondingCollider"] = {"collision": native_collision}
        hover_vm.native_view()
        assert hover[HOVER_COLLIDER] is None
        assert (
            hover["output"]["InputRespondingCollider"]["collision"] == native_collision
        )
    hover["output"]["InputRespondingCollider"] = None
    hover_vm.native_view()
    assert hover[HOVER_COLLIDER] is None
    # Keep every other response, and restore a non-default prior response too.
    custom = {"collision": 0, "responses": {CLICKABLE_CHANNEL: 1, 3: 0, 15: 0}}
    hover["output"]["InputRespondingCollider"] = custom
    hover_vm.native_view()
    assert custom["responses"] == {CLICKABLE_CHANNEL: 2, 3: 0, 15: 0}
    hover[HIDDEN] = False
    hover_vm.native_view()
    assert custom["collision"] == 0
    assert custom["responses"] == {CLICKABLE_CHANNEL: 1, 3: 0, 15: 0}
    original_backpack = json.loads(
        (HERE / "vanilla/Astro/Content/Items/BackpackRail.json").read_text()
    )
    output_template = "Printer Slot_GEN_VARIABLE"
    assert ps(es(backpack)[output_template])["Unclickable"]["Value"] is True
    assert (
        es(backpack)[output_template]["Data"]
        == es(original_backpack)[output_template]["Data"]
    )
    vm.run(TOGGLE)
    actor["state_requests"].clear()
    for _ in range(100):
        actor["output"] = {"state": 2}
        vm.native_view()
        assert actor["output"]["state"] == 0
    # Check every request, not just the final state: a transient show followed by
    # hide passes the old test but restarts the icon animation on each frame.
    assert actor["state_requests"] == [0] * 100
    actor["PrinterVisible"] = False
    vm.native_view()
    actor["PrinterVisible"] = True
    vm.native_view()
    assert actor["state_requests"] == [0] * 102 and actor[HIDDEN]
    assert actor["output"]["VisibilityControl"] == 0
    # A hidden output uses the engine's hover mode, with one state request per
    # update. Mouse focus never changes the preference or runs a save callback.
    for focus in [True, False, True, False]:
        actor["output"]["focus"] = focus
        actor["state_requests"].clear()
        vm.native_view()
        assert actor["state_requests"] == [2 if focus else 0]
        assert actor[HIDDEN] and actor["output"]["VisibilityControl"] == 0
    actor["PrinterVisible"] = False
    vm.run(TOGGLE)
    assert actor["output"]["state"] == 0 and not actor[HIDDEN]
    actor["PrinterVisible"] = True
    vm.run(TOGGLE)
    vm.run(TOGGLE)
    assert actor["output"]["state"] == 2
    actor["REP_ShowPrinterOutputSlotTooltip"] = False
    vm.run(TOGGLE)
    vm.run(TOGGLE)
    assert actor["output"]["state"] == 0
    actor["output"] = None
    vm.run(TOGGLE)
    vm.native_view()
    vm.run(TOGGLE)
    remote = fresh(False)
    remote_vm = PrinterVM(backpack, remote)
    remote_vm.run(TOGGLE)
    assert not remote[HIDDEN] and remote["native_view_calls"] == 0
    remote_vm.native_view()
    assert remote["output"]["state"] == 2

    for visible in [False, True]:
        for recipe in [False, True]:
            for hidden in [False, True]:
                for focus in [False, True]:
                    case = fresh()
                    case.update(
                        PrinterVisible=visible, REP_ShowPrinterOutputSlotTooltip=recipe
                    )
                    case[HIDDEN] = hidden
                    case["output"]["focus"] = focus
                    PrinterVM(backpack, case).native_view()
                    assert case["state_requests"] == [
                        2 if visible and recipe and (not hidden or focus) else 0
                    ]
                    assert case["output"]["VisibilityControl"] == (
                        0 if visible and recipe and hidden else 7
                    )

    head = assets["Printhead_Backpack"]
    hx = es(head)
    component = hx[BUTTON + "_GEN_VARIABLE"]
    assert (
        head["Imports"][-component["ClassIndex"] - 1]["ObjectName"]
        == "ControlPanelButtonChildActorComponent"
    )
    component_id = head["Exports"].index(component) + 1
    node = next(
        e
        for e in head["Exports"]
        if ps(e).get("ComponentTemplate", {}).get("Value") == component_id
    )
    assert ps(node)["ParentComponentOrVariableName"]["Value"] == "Scene"
    assert ps(node)["ParentComponentOwnerClassName"]["Value"] == "PrintheadSelector_C"
    child = head["Imports"][-ps(component)["ChildButtonClass"]["Value"] - 1]
    assert child["ObjectName"] == "PrinterEyeButton_C"
    actor_source = json.loads(
        (HERE / "vanilla/Astro/Content/Components/PrintheadSelector.json").read_text()
    )
    left = ps(es(actor_source)["ControlPanelButtonChildActor_LeftButton_GEN_VARIABLE"])
    right = ps(
        es(actor_source)["ControlPanelButtonChildActor_RightButton_GEN_VARIABLE"]
    )
    a, b, c = [xyz(p["RelativeLocation"]) for p in [left, right, ps(component)]]
    assert np.allclose(
        [float(c[k]) for k in "XYZ"],
        [(float(a[k]) + float(b[k])) / 2 for k in "XYZ"],
        atol=1e-4,
    )
    assert ps(component)["RelativeRotation"] == left["RelativeRotation"]
    scs = next(
        e
        for e in head["Exports"]
        if e["ObjectName"].startswith("SimpleConstructionScript_")
    )
    node_id = head["Exports"].index(node) + 1
    assert any(p["Value"] == node_id for p in ps(scs)["AllNodes"]["Value"])
    assert any(p["Value"] == node_id for p in ps(scs)["RootNodes"]["Value"])
    binding = ps(hx["BPM_PrinterEyeBinding"])["ComponentDelegateBindings"]["Value"]
    assert len(binding) == 1
    fields = {p["Name"]: p["Value"] for p in binding[0]["Value"]}
    assert fields == {
        "ComponentPropertyName": BUTTON,
        "DelegatePropertyName": "OnButtonPressed",
        "FunctionNameToBind": "BPM_EyePressed",
    }
    callback = hx["BPM_EyePressed"]
    assert (
        sum(map(kismet_size, callback["ScriptBytecode"]))
        == callback["ScriptBytecodeSize"]
    )
    virtual = callback["ScriptBytecode"][2]["ContextExpression"]
    assert (
        op_type(virtual) == "EX_VirtualFunction"
        and virtual["VirtualFunctionName"] == TOGGLE
    )
    native_click = es(actor_source)["NavigateRight"]["ScriptBytecode"][0]["Expression"][
        "ContextExpression"
    ]
    sound = callback["ScriptBytecode"][1]["Expression"]["ContextExpression"]
    assert head["Imports"][-sound["StackNode"] - 1]["ObjectName"] == "PostEvent"
    selection = sound["Parameters"][0]
    assert head["Imports"][-selection["StackNode"] - 1]["ObjectName"] == "SelectString"
    assert selection["Parameters"][0] == native_click["Parameters"][0]
    native_left = es(actor_source)["NavigateLeft"]["ScriptBytecode"][0]["Expression"][
        "ContextExpression"
    ]
    assert selection["Parameters"][1] == native_left["Parameters"][0]
    assert (
        selection["Parameters"][2]["ContextExpression"]["VirtualFunctionName"]
        == GET_HIDDEN
    )
    assert sound["Parameters"][2] == native_click["Parameters"][2]
    assert sound["Parameters"][1]["ObjectExpression"]["Variable"]["New"]["Path"] == [
        BUTTON
    ]
    parent = fresh()
    eye_actor = object()
    press = PressVM(
        head,
        {BUTTON: {"ChildActor": eye_actor}, "parent": parent},
        PrinterVM(backpack, parent),
    )
    press.run("BPM_EyePressed")
    assert parent[HIDDEN] and parent["output"]["state"] == 0
    press.run("BPM_EyePressed")
    assert not parent[HIDDEN] and parent["output"]["state"] == 2
    assert press.sounds == [
        ["play_sym_left", eye_actor, False],
        ["play_sym_right", eye_actor, False],
    ]
    press.actor["parent"] = None
    press.run("BPM_EyePressed")
    assert len(press.sounds) == 2 and parent["native_view_calls"] == 2

    original_head = json.loads(
        (HERE / "vanilla/Astro/Content/Components/Printhead_Backpack.json").read_text()
    )
    for old in original_head["Exports"]:
        name = old["ObjectName"]
        if name != "Printhead_Backpack_C" and not name.startswith(
            "SimpleConstructionScript_"
        ):
            assert {k: v for k, v in hx[name].items() if k != "SerialOffset"} == {
                k: v for k, v in old.items() if k != "SerialOffset"
            }, name
    original_button = json.loads(
        (
            HERE
            / "vanilla/Astro/Content/ControlPanels/ModularControlPanel/PanelParts/ControlPanelButton_Round.json"
        ).read_text()
    )
    assert (
        ps(es(assets["PrinterEyeButton"])["Default__PrinterEyeButton_C"])[
            "bButtonEnabled"
        ]["Value"]
        is True
    )
    assert (
        es(assets["PrinterEyeButton"])["ButtonMesh_GEN_VARIABLE"]["Data"]
        == es(original_button)["ButtonMesh_GEN_VARIABLE"]["Data"]
    )
    button = assets["PrinterEyeButton"]
    assert not any("Rays" in e["ObjectName"] for e in button["Exports"])
    assert "PrinterEyeRays" not in assets
    # Static material references stay native; no palette or RGB parameters are changed.
    old_mesh = json.loads(
        (
            HERE
            / "vanilla/Astro/Content/Models/ControlPanels/control_panel_button_round_arrow.json"
        ).read_text()
    )
    assert (
        ps(es(assets["PrinterEyeMesh"])["PrinterEyeMesh"])["StaticMaterials"]
        == ps(es(old_mesh)["control_panel_button_round_arrow"])["StaticMaterials"]
    )
    assert assets["PrinterEyeMesh"]["Imports"] == old_mesh["Imports"]

    def active(faces):
        return (
            (faces[:, 0] != faces[:, 1])
            & (faces[:, 1] != faces[:, 2])
            & (faces[:, 0] != faces[:, 2])
        )

    approved = json.loads((HERE.parent / "models/printer-info.json").read_text())
    assert sum(len(p["triangles"]) for p in approved["parts"].values()) == 41
    for label, part in [("PrinterEyeMesh", "info")]:
        assert assets[label]["Imports"] == old_mesh["Imports"]
        assert (
            ps(es(assets[label])[label])["StaticMaterials"]
            == ps(es(old_mesh)["control_panel_button_round_arrow"])["StaticMaterials"]
        )
        subprocess.run(
            [
                str(UMODEL),
                "-export",
                "-gltf",
                "-lods",
                "-notex",
                "-game=ue4.27",
                "-path=" + str(OUT / "staging"),
                "-out=" + str(OUT / "eye-check"),
                label + ".uasset",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        _, attrs, indices = gltf(OUT / f"eye-check/Mods/CompactBackpack16/{label}.gltf")
        expected = np.load(OUT / f"printer-{part}-expected.npz")
        wanted = expected["indices"]
        assert np.array_equal(active(indices), active(wanted))
        assert np.allclose(
            attrs["POSITION"][indices[active(indices)]][:, :, [0, 2, 1]] * 100,
            expected["positions"][wanted[active(wanted)]],
            atol=2e-6,
            rtol=0,
        )
        assert np.array_equal(
            attrs["TEXCOORD_0"][indices[active(indices)]],
            expected["uv"][wanted[active(wanted)]],
        )
        casing = expected["casing"]
        assert np.array_equal(
            expected["positions"][casing], expected["original_positions"][casing]
        )
        _, original_attrs, _ = gltf(
            HERE / "exports/Models/ControlPanels/control_panel_button_round_arrow.gltf"
        )
        assert np.array_equal(
            expected["uv"][casing], original_attrs["TEXCOORD_0"][casing]
        )
        glyph_triangles = wanted[active(wanted)]
        glyph_triangles = glyph_triangles[
            ~np.any(np.isin(glyph_triangles, casing), axis=1)
        ]
        assert len(glyph_triangles) == len(approved["parts"][part]["triangles"])
        source_points = np.array(approved["parts"][part]["positions"])
        cooked_points = expected["positions"][np.unique(glyph_triangles)]
        assert np.allclose(cooked_points[:, 0], source_points[0, 0])
        assert np.allclose(
            np.ptp(cooked_points[:, 1:], axis=0),
            np.ptp(source_points[:, 1:], axis=0) * PRINTER_ICON_SCALE,
            atol=2e-6,
        )
    return [
        "eye button uses native left sound when hiding and right when showing; no recipe navigation",
        "tooltip starts visible; its hide setting is local and not replicated",
        "hidden output arms query-only hover once per hologram and restores on toggle/close; slot remains unclickable, with no transient show/hide requests",
        "remote backpacks cannot change the local tooltip preference",
        "existing printer components, rounded button shape and material colours preserved",
        "approved 41-triangle info disc matches cooked mesh; native casing and white glyph UV retained",
    ]

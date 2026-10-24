"""Offline checks for the optional native panel retraction workaround."""

import copy
import json
import struct

from asset_io import HERE, es, ps
from catalog import patch_catalog_startup
from kismet import op_type
from panel_retraction import OPEN_EVENTS, PREFIX, without_hooks
from settings import PANEL_RETRACTION_FIX
from verify_behaviors import VM


class PanelVM(VM):
    def __init__(self, document, actor):
        super().__init__(document, actor)
        self.native_events = {}
        self.event_calls = []

    def run(self, name, args=()):
        if name == "ExecuteUbergraph_BackpackCatalog":
            assert len(args) == 1 and args[0] in self.native_events
            self.event_calls.append(args[0])
            self.eval(self.native_events[args[0]], self.actor, {})
            return
        return super().run(name, args)

    def set(self, expr, value, obj, local):
        if op_type(expr) == "EX_LocalVariable":
            local[self.name(expr["Variable"])] = value
            return
        super().set(expr, value, obj, local)

    def eval(self, x, obj, local):
        t = op_type(x)
        if t == "EX_IntConst":
            return int(x["Value"])
        if t == "EX_FloatConst":
            return float(x["Value"])
        if t == "EX_VectorConst":
            return tuple(float(x["Value"][k]) for k in "XYZ")
        if t in ["EX_Let", "EX_LetObj"]:
            field, value = (
                ("Variable", "Expression")
                if t == "EX_Let"
                else ("VariableExpression", "AssignmentExpression")
            )
            self.set(x[field], self.eval(x[value], obj, local), obj, local)
            return
        if t in ["EX_CallMath", "EX_FinalFunction"] and x["StackNode"] < 0:
            name = self.d["Imports"][-x["StackNode"] - 1]["ObjectName"]
            params = x["Parameters"]
            if name == "BreakTransform":
                transform = self.eval(params[0], obj, local)
                for field, key in zip(params[1:], ["location", "rotation", "scale"]):
                    self.set(field, transform[key], obj, local)
                return
            if name == "K2_SetRelativeLocation":
                obj["location"] = self.eval(params[0], obj, local)
                return True
            if name in [
                "Not_PreBool",
                "GetClosedRelativeTransform",
                "SetClosedRelativeTransform",
                "MakeTransform",
                "Stop",
                "SetPlaybackPosition",
                "Multiply_FloatFloat",
                "MakeVector",
                "K2_GetRootComponent",
                "GetCracked",
            ]:
                args = [self.eval(p, obj, local) for p in params]
                if name == "Not_PreBool":
                    return not args[0]
                if name == "GetCracked":
                    return obj["cracked"]
                if name == "GetClosedRelativeTransform":
                    return copy.deepcopy(obj["closed_transform"])
                if name == "SetClosedRelativeTransform":
                    obj["closed_transform"] = copy.deepcopy(args[0])
                    return
                if name == "MakeTransform":
                    return dict(zip(["location", "rotation", "scale"], args))
                if name == "Stop":
                    obj["playing"] = False
                    obj["calls"].append((name, args))
                    return
                if name == "SetPlaybackPosition":
                    obj["position"] = args[0]
                    obj["calls"].append((name, args))
                    assert args == [0.0, False, True]
                    # Execute the unchanged native inward-slide update at its
                    # verified zero-time curve value, rather than assuming a reset.
                    self.actor[
                        "MissionLogSlide_SlideInProgress_94F5C5674C73ED42E79A3097058A58AE"
                    ] = 0.0
                    native = es(self.d)[
                        "ExecuteUbergraph_MissionsControlPanel_Backpack"
                    ]
                    update_local = {}
                    for expr in native["ScriptBytecode"][13:17]:
                        self.eval(expr, self.actor, update_local)
                    return
                if name == "Multiply_FloatFloat":
                    return float(args[0]) * float(args[1])
                if name == "MakeVector":
                    return tuple(float(v) for v in args)
                if name == "K2_GetRootComponent":
                    return self.actor["SkeletalMesh"]
        return super().eval(x, obj, local)


def canonical(value):
    if isinstance(value, str) and value in ["+0", "-0"]:
        return 0.0
    if isinstance(value, float):
        # Generated constants are serialized as 32-bit floats in the PAK.
        return struct.unpack("<f", struct.pack("<f", value))[0]
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def check_catalog_opening_events(catalog):
    original = json.loads(
        (HERE / "vanilla/Astro/Content/Items/Catalog/BackpackCatalog.json").read_text()
    )
    native = es(original)
    graph = native["ExecuteUbergraph_BackpackCatalog"]["ScriptBytecode"]
    event_actions = {}
    for event, field, value in zip(
        OPEN_EVENTS, ["ExtendTop", "ExtendPanel"], ["EX_False", "EX_True"]
    ):
        # Exercise the actual native field writes reached by the two event
        # wrappers; the VM does not attempt to emulate the whole UI graph.
        call = native[event]["ScriptBytecode"][0]
        entry = call["Parameters"][0]["Value"]
        actions = [
            x
            for x in graph
            if op_type(x) == "EX_LetBool"
            and x["VariableExpression"].get("Variable", {}).get("New", {}).get("Path")
            == [field]
            and op_type(x["AssignmentExpression"]) == value
        ]
        assert len(actions) == 1
        event_actions[entry] = actions[0]
    # Closing before, between or after the two events must yield the same
    # closed inputs. Deliver stale callbacks even after Stop as a guard check.
    for close_time in [0.0, 0.02, 0.059, 0.06, 0.1, 0.259, 0.26, 0.3, 0.8]:
        actor = {
            "BPM_CatalogPosePending": False,
            "BPM_CatalogPoseStarted": False,
            "ExtendTop": True,
            "ExtendPanel": False,
            "rendered": True,
            "SkeletalMesh": {
                "bNoSkeletonUpdate": False,
                "visible": True,
                "tick_enabled": True,
                "VisibilityBasedAnimTickOption": 3,
            },
            "CrackableActorComponent": {"fully_closed": False, "cracked": True},
            "SpindleTransition": {"playing": True, "calls": []},
        }
        vm = PanelVM(catalog, actor)
        vm.native_events = event_actions
        for event, event_time in zip(OPEN_EVENTS, [0.06, 0.26]):
            if event_time < close_time:
                vm.run(event)
        actor["CrackableActorComponent"]["cracked"] = False
        for expr in graph[223:226]:
            vm.eval(expr, actor, {})
        vm.run(PREFIX + "CatalogClosed", [False])
        assert not actor["SpindleTransition"]["playing"]
        assert actor["ExtendTop"] is True and actor["ExtendPanel"] is False
        calls = list(vm.event_calls)
        for event in OPEN_EVENTS:
            vm.run(event)
        assert vm.event_calls == calls
        assert actor["ExtendTop"] is True and actor["ExtendPanel"] is False
        actor["CrackableActorComponent"]["fully_closed"] = True
        vm.run("BPM_TrySetCatalogClosedPose")
        vm.run("BPM_FreezeCatalogClosedPose")
        assert actor["ExtendTop"] is True and actor["ExtendPanel"] is False
        assert actor["SkeletalMesh"]["bNoSkeletonUpdate"]

        # A later genuine opening must still receive both native events.
        actor["CrackableActorComponent"].update(fully_closed=False, cracked=True)
        vm.run("BPM_ReleaseCatalogClosedPoseIfOpened", [True])
        actor["SpindleTransition"]["playing"] = True
        for event in OPEN_EVENTS:
            vm.run(event)
        assert actor["ExtendTop"] is False and actor["ExtendPanel"] is True
        assert actor["SpindleTransition"]["playing"]
        assert not vm.timers
        actor["CrackableActorComponent"] = None
        for event in OPEN_EVENTS:
            vm.run(event)


def check_panel_retraction(assets):
    catalog = assets["BackpackCatalog"]
    if not PANEL_RETRACTION_FIX:
        assert "MissionsControlPanel_Backpack" not in assets
        assert not any(e["ObjectName"].startswith(PREFIX) for e in catalog["Exports"])
        return []
    mission = assets["MissionsControlPanel_Backpack"]
    check_catalog_opening_events(catalog)
    # All original scripts still execute verbatim; only the declared post-hooks
    # are added. The catalog uses native closed-state inputs during initialization.
    reference = patch_catalog_startup()
    clean = without_hooks(catalog)
    for name, old in es(reference).items():
        if old.get("ScriptBytecode"):
            assert canonical(es(clean)[name]["ScriptBytecode"]) == canonical(
                old["ScriptBytecode"]
            ), name
            assert es(clean)[name]["ScriptBytecodeSize"] == old["ScriptBytecodeSize"], (
                name
            )
    original = json.loads(
        (
            HERE
            / "vanilla/Astro/Content/ControlPanels/Missions/MissionsControlPanel_Backpack.json"
        ).read_text()
    )
    clean_mission = es(without_hooks(mission))
    for name, old in es(original).items():
        if old.get("ScriptBytecode"):
            assert clean_mission[name]["ScriptBytecode"] == old["ScriptBytecode"], name
            assert (
                clean_mission[name]["ScriptBytecodeSize"] == old["ScriptBytecodeSize"]
            ), name
        if old.get("Data"):
            assert clean_mission[name]["Data"] == old["Data"], name
    # Native inward slide begins at zero offset and finishes within its own
    # 0.26s timeline. Stopping and setting its time to zero also clears its cache.
    timeline = ps(es(original)["MissionLogSlide_Template"])
    assert float(timeline["TimelineLength"]["Value"]) < 0.5
    tracks = timeline["FloatTracks"]["Value"]
    inward = next(
        t
        for t in tracks
        if any(
            p["Name"] == "TrackName" and p["Value"] == "SlideInProgress"
            for p in t["Value"]
        )
    )
    curve_id = next(p["Value"] for p in inward["Value"] if p["Name"] == "CurveFloat")
    curve = original["Exports"][curve_id - 1]
    keys = next(p for p in ps(curve)["FloatCurve"]["Value"] if p["Name"] == "Keys")[
        "Value"
    ]
    assert float(keys[0]["Value"][0]["Value"]["Time"]) == 0
    assert float(keys[0]["Value"][0]["Value"]["Value"]) == 0

    actor = {
        "BPM_CatalogPosePending": False,
        "BPM_CatalogPoseStarted": False,
        "ExtendTop": True,
        "ExtendPanel": False,
        "rendered": True,
        "SkeletalMesh": {
            "bNoSkeletonUpdate": True,
            "visible": True,
            "tick_enabled": False,
            "VisibilityBasedAnimTickOption": 3,
        },
        "CrackableActorComponent": {"fully_closed": True, "cracked": False},
        "SpindleTransition": {"playing": True, "calls": []},
    }
    vm = PanelVM(catalog, actor)
    for cycle in range(20):
        actor["CrackableActorComponent"]["fully_closed"] = False
        vm.run("BPM_ReleaseCatalogClosedPoseIfOpened", [True])
        vm.run(PREFIX + "CatalogClosed", [True])
        assert not vm.timers
        # An early close signal schedules one attempt. A later native full-close
        # event starts pose settling, without repeating checks in between.
        actor["SkeletalMesh"]["bNoSkeletonUpdate"] = True
        vm.run(PREFIX + "CatalogClosed", [False])
        assert actor["BPM_CatalogPosePending"]
        assert not actor["BPM_CatalogPoseStarted"]
        assert actor["SkeletalMesh"]["bNoSkeletonUpdate"]
        assert not vm.timers["BPM_TrySetCatalogClosedPose"]["loop"]
        vm.timers.pop("BPM_TrySetCatalogClosedPose")
        vm.run("BPM_TrySetCatalogClosedPose")
        assert not actor["BPM_CatalogPoseStarted"] and not vm.timers
        actor["CrackableActorComponent"]["fully_closed"] = True
        actor["ExtendTop"] = True
        actor["SkeletalMesh"]["bNoSkeletonUpdate"] = True
        vm.run(PREFIX + "CatalogClosed", [False])
        vm.run("BPM_TrySetCatalogClosedPose")
        assert actor["BPM_CatalogPosePending"] and actor["ExtendTop"] is True
        assert not actor["SkeletalMesh"]["bNoSkeletonUpdate"]
        assert actor["ExtendPanel"] is False
        timers = copy.deepcopy(vm.timers)
        # A second native close notification can restore its own frozen,
        # extended state. The post-hook must preserve the pending correction.
        actor["ExtendTop"] = True
        actor["SkeletalMesh"]["bNoSkeletonUpdate"] = True
        vm.run(PREFIX + "CatalogClosed", [False])
        assert actor["ExtendTop"] is True and actor["ExtendPanel"] is False
        assert not actor["SkeletalMesh"]["bNoSkeletonUpdate"]
        assert (
            vm.timers == timers
        )  # duplicate notifications reuse the same one-shot callback
        if cycle % 3 == 0:
            actor["CrackableActorComponent"]["fully_closed"] = False
            vm.run("BPM_ReleaseCatalogClosedPoseIfOpened", [True])
            assert not vm.timers and not actor["BPM_CatalogPosePending"]
            actor["CrackableActorComponent"]["fully_closed"] = True
            vm.run(PREFIX + "CatalogClosed", [False])
        vm.timers.pop("BPM_FreezeCatalogClosedPose")
        vm.run("BPM_FreezeCatalogClosedPose")
        assert actor["SkeletalMesh"]["bNoSkeletonUpdate"] and actor["ExtendTop"] is True
        assert not vm.timers and not actor["BPM_CatalogPosePending"]

    # Both native notifications must run our helper after their original
    # handlers, so an early fully-closed check cannot lose the close event.
    from panel_retraction import FULL_EVENT, STATE_EVENT

    helper = catalog["Exports"].index(es(catalog)[PREFIX + "CatalogClosed"]) + 1
    for event in [STATE_EVENT, FULL_EVENT]:
        code = es(catalog)[event]["ScriptBytecode"]
        calls = [x for x in code if x.get("StackNode") == helper]
        assert len(calls) == 1
        hook_index = code.index(calls[0])
        native_index = next(
            i
            for i, x in enumerate(code)
            if op_type(x) == "EX_LocalFinalFunction"
            and x.get("StackNode", 0) > 0
            and catalog["Exports"][x["StackNode"] - 1]["ObjectName"]
            == "ExecuteUbergraph_BackpackCatalog"
        )
        assert native_index < hook_index

    rotation, scale = (7.0, 19.0, -4.0), (1.2, 0.8, 1.1)
    actor = {
        "SlideOut": True,
        "SkeletalMesh": {"location": (0.0, -16.0, 0.0)},
        "CrackableActorComponent": {
            "fully_closed": False,
            "closed_transform": {
                "location": (0.0, -16.0, 0.0),
                "rotation": rotation,
                "scale": scale,
            },
        },
        "MissionLogSlide": {"playing": True, "position": 0.26, "calls": []},
    }
    vm = PanelVM(mission, actor)
    for cycle in range(20):
        component = actor["CrackableActorComponent"]
        actor["SkeletalMesh"]["location"] = (0.0, -16.0 + cycle / 20, 0.0)
        original_location = actor["SkeletalMesh"]["location"]
        component["closed_transform"]["location"] = original_location
        component["fully_closed"] = False
        calls = len(actor["MissionLogSlide"]["calls"])
        vm.run(PREFIX + "MissionClosing", [False])
        assert component["closed_transform"] == {
            "location": (0.0, 0.0, 0.0),
            "rotation": rotation,
            "scale": scale,
        }
        assert actor["SkeletalMesh"]["location"] == original_location
        vm.run(PREFIX + "MissionClosed", [False])
        vm.run(PREFIX + "MissionClosed", [True])
        assert len(actor["MissionLogSlide"]["calls"]) == calls
        component["fully_closed"] = True
        vm.run(PREFIX + "MissionClosed", [False])
        assert actor["SkeletalMesh"]["location"] == (0.0, 0.0, 0.0)
        assert not actor["SlideOut"] and not actor["MissionLogSlide"]["playing"]
        assert component["closed_transform"]["rotation"] == rotation
        assert component["closed_transform"]["scale"] == scale
        vm.run(PREFIX + "MissionClosed", [False])
        assert actor["SkeletalMesh"]["location"] == (0.0, 0.0, 0.0)
        assert not vm.timers
    actor["MissionLogSlide"] = None
    vm.run(PREFIX + "MissionClosed", [False])
    actor["CrackableActorComponent"] = None
    vm.run(PREFIX + "MissionClosed", [False])
    return [
        "catalog uses the native closed pose; opening timeline stopped on close and stale pose events ignored through rapid close and reopen cases",
        "mission log closing target preserves rotation/scale and native timeline update reaches zero offset through 20 cycles",
        "original catalog and mission-log bytecode preserved outside declared hooks; no animation-class or mesh replacements",
        "optional workaround isolated behind PANEL_RETRACTION_FIX; installed native asset and executable fingerprints checked before build",
    ]

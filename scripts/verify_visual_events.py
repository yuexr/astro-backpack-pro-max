"""check appearance events, cleanup and bounded catalog readiness"""

import copy
import json

from asset_io import HERE, es
from catalog import (
    COMPLETE,
    DEFER,
    FINISH,
    QUEUE_FINISH,
    QUEUE_READY,
    READY_REQUEST,
    START,
    STOP,
    TRY,
    WAIT_SECONDS,
)
from kismet import kismet_size, op_type
from settings import PANEL_RETRACTION_FIX
from verify_behaviors import VM
from verify_catalog_events import TimedVM, new_actor
from visual_events import BIND, CHARACTER, MODE, STATE, UNBIND


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


class EventVM(VM):
    def __init__(self, document, actor, pack_vm=None):
        super().__init__(document, actor)
        actor.setdefault(STATE, None)
        actor.setdefault("Catalog", None)
        actor.setdefault("catalogCreative", None)
        actor.setdefault("creative", False)
        actor.setdefault("backpack_mk2", None)
        self.pack_vm = pack_vm

    def eval(self, expr, obj, local):
        kind = op_type(expr)
        if kind == "EX_NoObject":
            return None
        if kind == "EX_LetObj":
            self.set(
                expr["VariableExpression"],
                self.eval(expr["AssignmentExpression"], obj, local),
                obj,
                local,
            )
            return
        if kind == "EX_InstanceDelegate":
            return (self, expr["FunctionName"])
        if kind == "EX_AddMulticastDelegate":
            delegates = self.eval(expr["Delegate"], obj, local)
            delegates.append(self.eval(expr["DelegateToAdd"], obj, local))
            return
        if kind == "EX_RemoveMulticastDelegate":
            delegates = self.eval(expr["Delegate"], obj, local)
            target = self.eval(expr["DelegateToAdd"], obj, local)
            delegates[:] = [entry for entry in delegates if entry != target]
            return
        if kind == "EX_VirtualFunction":
            if expr["VirtualFunctionName"] == READY_REQUEST:
                return obj["vm"].run(READY_REQUEST)
            if expr["VirtualFunctionName"] == QUEUE_READY and obj is self.actor:
                return self.run(QUEUE_READY)
            assert self.pack_vm is not None and obj is self.pack_vm.actor
            assert not expr["Parameters"]
            return self.pack_vm.run(expr["VirtualFunctionName"])
        if kind == "EX_LocalFinalFunction":
            name = self.d["Exports"][expr["StackNode"] - 1]["ObjectName"]
            if name == "Get Backpack":
                assert len(expr["Parameters"]) == 1
                self.set(expr["Parameters"][0], self.actor["backpack"], obj, local)
                return
        if kind in ["EX_FinalFunction", "EX_CallMath"] and expr["StackNode"] < 0:
            name = self.d["Imports"][-expr["StackNode"] - 1]["ObjectName"]
            if name == "GetGameState":
                assert len(expr["Parameters"]) == 1
                return self.actor["state"]
            if name == "NotEqual_ObjectObject":
                a, b = [self.eval(p, obj, local) for p in expr["Parameters"]]
                return a is not b
            if name == "IsValid":
                target = self.eval(expr["Parameters"][0], obj, local)
                return target is not None and not (
                    isinstance(target, dict) and target.get("invalid", False)
                )
        return super().eval(expr, obj, local)


def check_visual_events(assets, geometry):
    from verify_catalog_palette import check_material_bindings

    check_material_bindings(assets["BackpackRail"])
    # Every original character instruction is retained, including async loading
    # and its continuation. Only the final material setter gains a post-hook.
    character = assets["DesignAstro"]
    original = json.loads((HERE / "vanilla" / (CHARACTER + ".json")).read_text())
    actual = es(character)
    for old in original["Exports"]:
        name = old["ObjectName"]
        current = actual[name]
        if old.get("ScriptBytecode"):
            code = copy.deepcopy(current["ScriptBytecode"])
            delta = 0
            if name == "SetCustomizationMaterials":
                index = next(
                    i for i, expr in enumerate(code) if op_type(expr) == "EX_Return"
                )
                call = code.pop(index - 1)
                assert (
                    character["Exports"][call["StackNode"] - 1]["ObjectName"]
                    == "BPM_RefreshBackpackMaterial"
                )
                delta = 10
                old_return = sum(map(kismet_size, old["ScriptBytecode"][:-2]))
                targets = [
                    child
                    for node in walk(old["ScriptBytecode"])
                    for key, child in node.items()
                    if key in ["CodeOffset", "PushingAddress"]
                ]
                assert all(target <= old_return for target in targets), (
                    "Retarget a branch past the post-hook"
                )
            assert code == old["ScriptBytecode"], name
            assert current["ScriptBytecodeSize"] == old["ScriptBytecodeSize"] + delta
        if old.get("Data"):
            assert current["Data"] == old["Data"], name
    for label, path in [
        ("BackpackRail", "Items/BackpackRail"),
        ("AstroCorpse", "Character/AstroCorpse"),
    ]:
        native = json.loads(
            (HERE / "vanilla/Astro/Content" / (path + ".json")).read_text()
        )
        assert (
            es(assets[label])["ReceiveTick"]["ScriptBytecode"]
            == es(native)["ReceiveTick"]["ScriptBytecode"]
        )

    state = {"OnCreativeModeEnabledChanged": []}
    pack = {"state": state, "creative": False, "backpack_mk2": {"material": object()}}
    components = (
        [f"NativeBackpackSocket{i}" for i in range(1, 17)]
        + [
            "Compact_" + name
            for name in geometry["front_components"]
            if not geometry["assets"][name].get("fixed_material")
        ]
        + ["NativeDroneSocket"]
    )
    for name in components:
        pack[name] = {"visible": False, "material": None}
    fixed_components = [
        "Compact_" + name
        for name in geometry["front_components"]
        if geometry["assets"][name].get("fixed_material")
    ]
    fixed_gold = object()
    for name in fixed_components:
        pack[name] = {"visible": True, "material": fixed_gold}
    pack_vm = EventVM(assets["BackpackRail"], pack)
    char_vm = EventVM(character, {"backpack": None}, pack_vm)
    char_vm.run("BPM_RefreshBackpackMaterial")
    assert not state["OnCreativeModeEnabledChanged"]
    # Appearance/mode events select only the active catalog. The catalog owns
    # its finite readiness window; no backpack-side fixed-delay timer is needed.
    ready_pack = {
        "Catalog": None,
        "catalogCreative": None,
        "creative": False,
        "NativeDroneSocket": {"visible": False},
    }
    ready_vm = EventVM(assets["BackpackRail"], ready_pack)
    ready_vm.run(QUEUE_READY)
    assert not ready_vm.timers
    if PANEL_RETRACTION_FIX:
        catalogs = [new_actor(visible=False, rendered=False) for _ in range(2)]
        for actor in catalogs:
            actor["vm"] = TimedVM(assets["BackpackCatalog"], actor)
        ready_pack["Catalog"] = {"ChildActor": catalogs[0]}
        ready_pack["catalogCreative"] = {"ChildActor": catalogs[1]}
        for _ in range(20):
            ready_vm.run(QUEUE_READY)
        assert not ready_vm.timers
        assert set(catalogs[0]["vm"].timers) == ({DEFER, STOP})
        assert not catalogs[1]["vm"].timers
        catalogs[0]["rendered"] = True
        catalogs[0]["SkeletalMesh"]["visible"] = True
        catalogs[0]["vm"].advance(0.02)
        catalogs[0]["vm"].run(COMPLETE)
        catalogs[0]["vm"].advance(0.02)
        assert not catalogs[0]["vm"].timers
        # A mode change can initialize the previously hidden creative catalog.
        ready_pack["creative"] = True
        catalogs[1]["CrackableActorComponent"]["fully_closed"] = False
        ready_vm.run(MODE, [True])
        assert not catalogs[1]["vm"].timers, "Do not correct an open panel"
        catalogs[1]["CrackableActorComponent"]["fully_closed"] = True
        ready_vm.run(MODE, [True])
        assert set(catalogs[1]["vm"].timers) == ({DEFER, STOP})
        catalogs[1]["rendered"] = True
        catalogs[1]["SkeletalMesh"]["visible"] = True
        catalogs[1]["vm"].advance(0.02)
        catalogs[1]["vm"].run(COMPLETE)
        catalogs[1]["vm"].advance(0.02)
        for _ in range(20):
            ready_vm.run(QUEUE_READY)
        assert not ready_vm.timers
        assert all(not actor["vm"].timers for actor in catalogs)

        # Appearance may finish before a catalog is created. Its deferred startup
        # must pick up the existing applied material without a new palette change.
        palette = object()
        ready_pack["creative"] = False
        ready_pack["backpack_mk2"] = {"material": palette}
        late = new_actor(rendered=False)
        late["parent"] = ready_pack
        ready_pack["vm"] = ready_vm
        late["SkeletalMesh"]["material"] = object()
        late["vm"] = TimedVM(assets["BackpackCatalog"], late)
        ready_pack["Catalog"] = {"ChildActor": late}
        late["vm"].run(READY_REQUEST)
        late["vm"].advance(0.02)
        assert late["SkeletalMesh"]["material"] is palette
        updated = object()
        ready_pack["backpack_mk2"]["material"] = updated
        ready_vm.run(QUEUE_READY)
        assert late["SkeletalMesh"]["material"] is updated
        late["vm"].run(COMPLETE)
        late["vm"].advance(0.02)
        assert not late["vm"].timers and not ready_vm.timers
    char_vm.actor["backpack"] = pack
    for _ in range(20):
        # Model the native assignment immediately followed by our actual helper.
        new_material = object()
        pack["backpack_mk2"]["material"] = new_material
        char_vm.run("BPM_RefreshBackpackMaterial")
        assert all(pack[name]["material"] is new_material for name in components)
        assert all(pack[name]["material"] is fixed_gold for name in fixed_components)
        for name, specification in geometry["assets"].items():
            if specification.get("follows_shoulder_pose"):
                assert pack["Compact_" + name]["master_pose"] is pack["backpack_mk2"]
        assert len(state["OnCreativeModeEnabledChanged"]) == 1
        assert pack[STATE] is state
        assert not pack_vm.timers and not char_vm.timers
    for creative in [True, False, True, False]:
        pack["creative"] = creative
        for target, callback in state["OnCreativeModeEnabledChanged"]:
            assert callback == MODE
            target.run(callback, [creative])
        assert pack["NativeDroneSocket"]["visible"] == creative
    # A missed initial bind can be completed by the later material callback.
    other = copy.copy(pack)
    other["state"] = None
    other[STATE] = None
    other_vm = EventVM(assets["BackpackRail"], other)
    other_vm.run(BIND)
    assert other[STATE] is None and not other_vm.timers
    other["state"] = {"OnCreativeModeEnabledChanged": []}
    other_vm.run(BIND)
    other_vm.run(BIND)
    assert len(other["state"]["OnCreativeModeEnabledChanged"]) == 1

    # two off-screen players must keep their own materials
    def new_pack(game_state):
        actor = {
            "state": game_state,
            "creative": True,
            "backpack_mk2": {"material": object()},
            "rendered": False,
        }
        actor.update(
            {name: {"visible": False, "material": None} for name in components}
        )
        actor.update(
            {
                name: {"visible": True, "material": fixed_gold}
                for name in fixed_components
            }
        )
        return actor, EventVM(assets["BackpackRail"], actor)

    remote, remote_vm = new_pack(state)
    remote_char = EventVM(character, {"backpack": remote}, remote_vm)
    remote_char.run("BPM_RefreshBackpackMaterial")
    assert len(state["OnCreativeModeEnabledChanged"]) == 2
    assert all(
        remote[name]["material"] is remote["backpack_mk2"]["material"]
        for name in components
    )
    assert all(
        pack[name]["material"] is pack["backpack_mk2"]["material"]
        for name in components
    )
    assert remote["NativeDroneSocket"]["visible"]
    for name, specification in geometry["assets"].items():
        if specification.get("follows_shoulder_pose"):
            assert remote["Compact_" + name]["master_pose"] is remote["backpack_mk2"]
    assert all(remote[name]["material"] is fixed_gold for name in fixed_components)

    # removing one backpack must leave the other player's callback alone
    # its replacement should pick up the current mode immediately
    pack_vm.run("ReceiveEndPlay", [0])
    pack_vm.run("ReceiveEndPlay", [0])
    assert pack[STATE] is None
    assert state["OnCreativeModeEnabledChanged"] == [(remote_vm, MODE)]
    replacement, replacement_vm = new_pack(state)
    char_vm.pack_vm = replacement_vm
    char_vm.actor["backpack"] = replacement
    char_vm.run("BPM_RefreshBackpackMaterial")
    assert len(state["OnCreativeModeEnabledChanged"]) == 2
    assert replacement["NativeDroneSocket"]["visible"]

    # changing GameState must detach the old callback before binding the new one
    new_state = {"OnCreativeModeEnabledChanged": []}
    replacement["state"] = new_state
    replacement_vm.run(BIND)
    replacement_vm.run(BIND)
    assert state["OnCreativeModeEnabledChanged"] == [(remote_vm, MODE)]
    assert new_state["OnCreativeModeEnabledChanged"] == [(replacement_vm, MODE)]
    replacement["state"] = None
    replacement_vm.run(BIND)
    assert not new_state["OnCreativeModeEnabledChanged"] and replacement[STATE] is None
    replacement_vm.run(UNBIND)

    # separate clients must keep separate callbacks
    client_state = {"OnCreativeModeEnabledChanged": []}
    client, client_vm = new_pack(client_state)
    client_vm.run(BIND)
    remote_vm.run("ReceiveEndPlay", [0])
    assert not state["OnCreativeModeEnabledChanged"]
    assert client_state["OnCreativeModeEnabledChanged"] == [(client_vm, MODE)]
    client_state["invalid"] = True
    client_vm.run("ReceiveEndPlay", [0])
    assert client[STATE] is None

    pack_class = next(
        e for e in assets["BackpackRail"]["Exports"] if "ClassExport" in e["$type"]
    )
    field = next(p for p in pack_class["LoadedProperties"] if p["Name"] == STATE)
    assert field["PropertyFlags"] == "CPF_Transient"
    end = es(assets["BackpackRail"])["ReceiveEndPlay"]
    assert end["FunctionFlags"] == es(original)["ReceiveEndPlay"]["FunctionFlags"]
    assert end["LoadedProperties"][0]["Name"] == "EndPlayReason"
    assert not any(vm.timers for vm in [pack_vm, remote_vm, replacement_vm, client_vm])

    forbidden = {
        "GetAllActorsOfClass",
        "GetAllActorsWithInterface",
        "GetAllActorsWithTag",
        "GetAllObjectsOfClass",
        "GetAllWidgetsOfClass",
        "FindAllOf",
    }
    timers = []
    for label, document in assets.items():
        for fn in document["Exports"]:
            if not fn["ObjectName"].startswith(("CB_", "BPM_")) or not fn.get(
                "ScriptBytecode"
            ):
                continue
            for expr in walk(fn["ScriptBytecode"]):
                node = expr.get("StackNode", 0)
                if node >= 0:
                    continue
                call = document["Imports"][-node - 1]["ObjectName"]
                assert call not in forbidden, (label, fn["ObjectName"], call)
                if call in ["K2_SetTimer", "K2_SetTimerDelegate"]:
                    params = expr["Parameters"]
                    assert op_type(params[3]) == "EX_False", "Repeating mod timer"
                    callback = params[1]["Value"]
                    assert label == "BackpackCatalog"
                    assert callback != fn["ObjectName"] or callback == TRY
                    if callback == STOP:
                        assert fn["ObjectName"] == "BPM_StartCatalogClosedPose"
                        assert params[2]["Value"] == WAIT_SECONDS
                    timers.append((fn["ObjectName"], callback))
    expected_timers = (
        [(START, STOP), (START, DEFER), (TRY, TRY), (QUEUE_FINISH, FINISH)]
        if PANEL_RETRACTION_FIX
        else []
    )
    assert sorted(timers) == sorted(expected_timers)
    return [
        "native material-function owners verified; appearance/load bytecode retained and material copied after the final setter",
        "startup, late-backpack and replacement refreshes pass; simulated off-screen players keep separate materials",
        "Creative bindings remain unique, follow GameState replacements and detach on EndPlay; simulated clients stay independent",
        "no added tick hooks or world scans; catalog readiness retries have a ten-second deadline and cancel on opening",
    ]

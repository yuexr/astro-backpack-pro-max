"""Check late animation completion without pretending to simulate rendering."""

import copy
import json

from asset_io import HERE, es, ps
from catalog import COMPLETE, DEFER, INITIALIZED, OPENED, OVERRIDE, PENDING, START
from catalog_animation import ANIMATIONS, CREATIVE_ANIM, NOTIFY, SEQUENCE
from kismet import op_type
from settings import PANEL_RETRACTION_FIX
from verify_behaviors import VM
from verify_catalog_events import TimedVM, new_actor, start
from verify_panel_retraction import canonical


class NotifyVM(VM):
    def __init__(self, document, catalog_vm):
        super().__init__(document, {})
        self.catalog_vm = catalog_vm

    def eval(self, expr, obj, local):
        if op_type(expr) == "EX_VirtualFunction":
            assert expr["VirtualFunctionName"] == COMPLETE
            assert obj is self.catalog_vm.actor
            return self.catalog_vm.run(COMPLETE)
        node = expr.get("StackNode", 0)
        if node < 0 and self.d["Imports"][-node - 1]["ObjectName"] == "GetOwningActor":
            return self.catalog_vm.actor
        return super().eval(expr, obj, local)


def check_completion(assets):
    labels = [path.rsplit("/", 1)[-1] for path in [*ANIMATIONS, SEQUENCE]]
    if not PANEL_RETRACTION_FIX:
        assert not any(label in assets for label in labels)
        assert "BackpackCatalog" not in assets
        return []
    animations = [assets[path.rsplit("/", 1)[-1]] for path in ANIMATIONS]
    creative = json.loads((HERE / "vanilla" / (CREATIVE_ANIM + ".json")).read_text())
    creative_class = next(e for e in creative["Exports"] if "ClassExport" in e["$type"])
    assert (
        creative["Imports"][-creative_class["SuperStruct"] - 1]["ObjectName"]
        == "BackpackCatalog_AnimBP_C"
    )
    animation = animations[0]
    sequence = assets[SEQUENCE.rsplit("/", 1)[-1]]
    handler = "AnimNotify_" + NOTIFY
    for path, document in zip(ANIMATIONS, animations):
        native_anim = json.loads((HERE / "vanilla" / (path + ".json")).read_text())
        for name, old in es(native_anim).items():
            actual = es(document)[name]
            for key in ["ScriptBytecode", "Data", "LoadedProperties"]:
                if old.get(key):
                    assert actual[key] == old[key], (path, name, key)
        assert len(document["Exports"]) == len(native_anim["Exports"]) + 1
        assert handler in es(document)
    native_seq = json.loads((HERE / "vanilla" / (SEQUENCE + ".json")).read_text())
    name = labels[-1]
    actual = copy.deepcopy(es(sequence)[name])
    original = es(native_seq)[name]
    notify = ps(actual)["Notifies"]
    actual["Data"].remove(notify)
    assert canonical(actual["Data"]) == canonical(original["Data"])
    assert actual["Extras"] == original["Extras"], "Compressed bone motion changed"
    assert len(notify["Value"]) == 1
    event = {entry["Name"]: entry for entry in notify["Value"][0]["Value"]}
    assert event["NotifyName"]["Value"] == NOTIFY
    assert event["Notify"]["Value"] == event["NotifyStateClass"]["Value"] == 0
    assert event["LinkedSequence"]["Value"] == 1
    assert event["LinkValue"]["Value"] == event["SegmentLength"]["Value"] == 0.5
    assert abs(event["TriggerTimeOffset"]["Value"] + 0.0001) < 1e-9
    assert event["bTriggerOnDedicatedServer"]["Value"] is False

    catalog = assets["BackpackCatalog"]
    for animation in animations:
        actor = new_actor(rendered=False)
        vm = TimedVM(catalog, actor)
        vm.run(START)
        assert DEFER in vm.timers and not actor[OVERRIDE]
        actor["SkeletalMesh"]["tick_enabled"] = False
        vm.advance(0.02)
        assert actor[PENDING] and actor["SkeletalMesh"]["tick_enabled"]
        NotifyVM(animation, vm).run(handler)
        vm.advance(0.02)
        assert actor[INITIALIZED] and not vm.timers

    # Each new catalog starts independently, including late join/rejoin. Already
    # initialized players stay idle when another player's catalog is created.
    settled = new_actor()
    old_vm = TimedVM(catalog, settled)
    start(old_vm)
    NotifyVM(animations[0], old_vm).run(handler)
    old_vm.advance(0.02)
    snapshot = copy.deepcopy(settled)
    old_vm.advance(300)
    for delay in [0.1, 5.0]:
        joined = new_actor(rendered=False)
        vm = TimedVM(catalog, joined)
        start(vm)
        vm.advance(delay)
        assert joined[PENDING] and not joined[INITIALIZED]
        NotifyVM(animations[0], vm).run(handler)
        vm.advance(0.02)
        assert joined[INITIALIZED] and not vm.timers
        assert settled == snapshot and not old_vm.timers
        joined["CrackableActorComponent"]["fully_closed"] = False
        vm.run(OPENED, [True])
        NotifyVM(animations[0], vm).run(handler)
        assert not vm.timers
    for document in [*animations, catalog]:
        for function in document["Exports"]:
            if function["ObjectName"].startswith(("BPM_", "AnimNotify_")):
                assert "SetActorHiddenInGame" not in str(
                    function.get("ScriptBytecode", [])
                )
    return [
        "native animation graphs and compressed bone motion retained; completion notify survives native startup tick cancellation",
        "independent late-join/replacement catalogs checked; existing catalogs stay idle and only native completion certifies success",
    ]

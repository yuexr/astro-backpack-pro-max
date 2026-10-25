"""Check readiness, finite retries, opening cancellation and tick restoration."""

import copy
import json

from asset_io import HERE, es
from catalog import (
    CLOSED,
    COMPLETE,
    DEFER,
    EVALUATED,
    FINISH,
    INITIALIZED,
    OPEN_EVENTS,
    OPENED,
    OVERRIDE,
    PENDING,
    READY_REQUEST,
    RETRY_SECONDS,
    SAVED,
    START,
    STOP,
    TRY,
    WAIT_SECONDS,
)
from kismet import kismet_size, op_type
from panel_retraction import FULL_EVENT, STATE_EVENT
from verify_behaviors import VM


class TimedVM(VM):
    """Run the serialized callbacks against a deterministic timer clock."""

    def __init__(self, document, actor):
        super().__init__(document, actor)
        self.now = 0.0
        self.deadlines = {}
        self.attempts = 0

    def eval(self, expression, obj, local):
        if op_type(expression) == "EX_VirtualFunction":
            assert expression["VirtualFunctionName"] == "BPM_RequestCatalogStartupPoses"
            return obj["vm"].run(expression["VirtualFunctionName"])
        node = expression.get("StackNode", 0)
        name = self.d["Imports"][-node - 1]["ObjectName"] if node < 0 else ""
        result = super().eval(expression, obj, local)
        if name == "K2_SetTimer":
            callback = expression["Parameters"][1]["Value"]
            self.deadlines[callback] = self.now + self.timers[callback]["seconds"]
        elif name == "K2_ClearTimer":
            self.deadlines.pop(expression["Parameters"][1]["Value"], None)
        return result

    def run(self, name, args=()):
        if name == TRY:
            self.attempts += 1
        return super().run(name, args)

    def advance(self, seconds):
        end = self.now + seconds
        while self.deadlines:
            callback = min(self.deadlines, key=self.deadlines.get)
            due = self.deadlines[callback]
            if due > end:
                break
            self.now = due
            self.deadlines.pop(callback)
            self.timers.pop(callback)
            self.run(callback)
            assert self.attempts < 1000, "Unbounded catalog callback chain"
        self.now = end


def start(vm):
    vm.run(START)
    vm.advance(0.02)


def new_actor(visible=True, rendered=True, option=3, actor_tick=True):
    return {
        "actor_tick_enabled": actor_tick,
        "ExtendTop": False,
        "ExtendPanel": True,
        "rendered": rendered,
        "SkeletalMesh": {
            "bNoSkeletonUpdate": True,
            "visible": visible,
            "tick_enabled": False,
            "VisibilityBasedAnimTickOption": option,
            "anim_instance": {},
        },
        "CrackableActorComponent": {"fully_closed": True},
    }


def assert_idle(vm):
    assert not vm.timers and not vm.deadlines
    assert not vm.actor[PENDING] and not vm.actor[OVERRIDE]


def check_native_catalog(document):
    original = json.loads(
        (HERE / "vanilla/Astro/Content/Items/Catalog/BackpackCatalog.json").read_text()
    )
    hooks = {
        "ReceiveBeginPlay": [(START, "after")],
        STATE_EVENT: [(OPENED, "before"), (CLOSED, "after")],
        FULL_EVENT: [(CLOSED, "after")],
    }
    for name, native in es(original).items():
        actual = es(document)[name]
        if native.get("ScriptBytecode"):
            code = copy.deepcopy(actual["ScriptBytecode"])
            added_size = 0
            for helper, position in hooks.get(name, []):
                at = (
                    0
                    if position == "before"
                    else next(
                        i for i, x in enumerate(code) if op_type(x) == "EX_Return"
                    )
                    - 1
                )
                call = code.pop(at)
                assert op_type(call) == "EX_LocalFinalFunction"
                assert (
                    document["Exports"][call["StackNode"] - 1]["ObjectName"] == helper
                )
                added_size += kismet_size(call)
            if name in OPEN_EVENTS:
                wrapper = code[0]
                helper = document["Exports"][wrapper["StackNode"] - 1]
                assert helper["ObjectName"] == "BPM_Catalog" + name.split("__")[1]
                assert len(helper["ScriptBytecode"]) == 5
                code[0] = copy.deepcopy(helper["ScriptBytecode"][-3])
                added_size += kismet_size(wrapper) - kismet_size(code[0])
            assert code == native["ScriptBytecode"], name
            assert (
                actual["ScriptBytecodeSize"]
                == native["ScriptBytecodeSize"] + added_size
            ), name
        if native.get("Data") and name != "Default__BackpackCatalog_C":
            assert actual["Data"] == native["Data"], name
    # Preserve existing defaults and animation graphs, and reject old helpers.
    old_defaults = es(original)["Default__BackpackCatalog_C"]["Data"]
    assert (
        es(document)["Default__BackpackCatalog_C"]["Data"][: len(old_defaults)]
        == old_defaults
    )
    forbidden = {"PlayAnimation", "SetAnimationMode", "WasRecentlyRendered"}
    assert not any(
        p["ObjectName"] in forbidden
        for p in document["Imports"][len(original["Imports"]) :]
    )
    assert "BPM_CatalogPoseStarted" not in document["NameMap"]
    assert "BPM_CatalogAwaitAnimation" not in document["NameMap"]
    for fn in document["Exports"]:
        if fn["ObjectName"].startswith("BPM_"):
            assert (
                sum(map(kismet_size, fn["ScriptBytecode"])) == fn["ScriptBytecodeSize"]
            )


def check_catalog_once(document):
    check_native_catalog(document)
    # Rendering history cannot certify completion. Restore every original tick
    # combination after the real completion callback, then remain idle.
    for rendered in [False, True]:
        for option in range(4):
            for tick in [False, True]:
                actor = new_actor(rendered=rendered, option=option, actor_tick=tick)
                actor["SkeletalMesh"]["tick_enabled"] = tick
                vm = TimedVM(document, actor)
                vm.run(START)
                assert set(vm.timers) == {DEFER, STOP} and not actor[OVERRIDE]
                # Native BeginPlay returns before the handoff executes.
                vm.advance(0.02)
                assert actor[OVERRIDE] and actor[SAVED] == option
                vm.advance(2.2)
                assert actor[PENDING] and not actor[INITIALIZED]
                assert not actor["SkeletalMesh"]["bNoSkeletonUpdate"]
                assert actor["SkeletalMesh"]["VisibilityBasedAnimTickOption"] == 0
                assert actor["ExtendTop"] and not actor["ExtendPanel"]
                vm.run(COMPLETE)
                assert FINISH in vm.timers and not actor[INITIALIZED]
                vm.advance(0.02)
                assert actor[INITIALIZED] and actor["SkeletalMesh"]["bNoSkeletonUpdate"]
                assert actor[EVALUATED] is actor["SkeletalMesh"]["anim_instance"]
                assert actor["SkeletalMesh"]["VisibilityBasedAnimTickOption"] == option
                assert actor["SkeletalMesh"]["tick_enabled"] == tick
                assert actor["actor_tick_enabled"] == tick
                assert_idle(vm)
                attempts = vm.attempts
                vm.run(READY_REQUEST)
                vm.run(COMPLETE)
                vm.advance(300)
                assert_idle(vm)
                assert vm.attempts == attempts

    actor = new_actor()
    vm = TimedVM(document, actor)
    start(vm)
    deadline = vm.deadlines[STOP]
    for _ in range(20):
        vm.advance(0.1)
        vm.run(READY_REQUEST)
        assert vm.deadlines[STOP] == deadline
    vm.advance(WAIT_SECONDS)
    assert_idle(vm)
    assert not actor[INITIALIZED] and actor["actor_tick_enabled"]
    assert vm.attempts <= int(WAIT_SECONDS / RETRY_SECONDS) + 1
    attempts = vm.attempts
    vm.advance(300)
    assert vm.attempts == attempts
    # A later appearance event can retry with a new finite deadline.
    vm.run(READY_REQUEST)
    vm.advance(0.02)
    vm.run(COMPLETE)
    vm.advance(0.02)
    assert actor[INITIALIZED]
    assert_idle(vm)

    # Completion before the close callback is usable only for that same instance.
    for replace in [False, True]:
        actor = new_actor()
        vm = TimedVM(document, actor)
        vm.run(COMPLETE)
        if replace:
            actor["SkeletalMesh"]["anim_instance"] = {}
        start(vm)
        if replace:
            vm.advance(1)
            assert not actor[INITIALIZED]
            vm.run(COMPLETE)
        vm.advance(0.02)
        assert actor[INITIALIZED]
        assert_idle(vm)

    # Replacing the AnimInstance after notification invalidates a queued finish.
    actor = new_actor()
    vm = TimedVM(document, actor)
    start(vm)
    vm.run(COMPLETE)
    actor["SkeletalMesh"]["anim_instance"] = {}
    vm.advance(0.02)
    assert not actor[INITIALIZED] and actor[PENDING]
    vm.run(COMPLETE)
    vm.advance(0.02)
    assert actor[INITIALIZED]
    assert_idle(vm)

    # Opening cancels before native setup, during retries, or after a notify.
    for stage in ["deferred", "retry", "finish"]:
        actor = new_actor()
        vm = TimedVM(document, actor)
        vm.run(START)
        if stage != "deferred":
            vm.advance(0.02)
        if stage == "finish":
            vm.run(COMPLETE)
        actor["CrackableActorComponent"]["fully_closed"] = False
        vm.run(OPENED, [True])
        vm.run(COMPLETE)
        vm.advance(11)
        assert actor[EVALUATED] is None and not actor[INITIALIZED]
        assert_idle(vm)

    # Delayed visibility, closed state and AnimInstance creation are readiness
    # conditions, not alternate success paths. Missing objects time out safely.
    for missing in [
        "SkeletalMesh",
        "CrackableActorComponent",
        "anim_instance",
        "visible",
        "fully_closed",
    ]:
        actor = new_actor()
        target = (
            actor
            if missing in actor
            else actor["CrackableActorComponent"]
            if missing == "fully_closed"
            else actor["SkeletalMesh"]
        )
        previous = target[missing]
        target[missing] = False if isinstance(previous, bool) else None
        vm = TimedVM(document, actor)
        start(vm)
        vm.advance(3)
        assert not actor[OVERRIDE] and not actor[INITIALIZED]
        target[missing] = previous
        vm.advance(RETRY_SECONDS + 0.01)
        assert actor[OVERRIDE]
        vm.run(COMPLETE)
        vm.advance(0.02)
        assert actor[INITIALIZED]
        assert_idle(vm)

        actor = new_actor()
        if missing in actor:
            actor[missing] = None
        elif missing == "fully_closed":
            actor["CrackableActorComponent"][missing] = False
        else:
            actor["SkeletalMesh"][missing] = False if missing == "visible" else None
        vm = TimedVM(document, actor)
        start(vm)
        vm.advance(11)
        assert not actor[INITIALIZED]
        assert_idle(vm)

    # Duplicate native closing callbacks cannot freeze a pending correction or
    # extend its deadline; native opening is still free to animate afterward.
    actor = new_actor()
    actor["SpindleTransition"] = {"playing": True, "calls": []}
    from verify_panel_retraction import PanelVM

    vm = PanelVM(document, actor)
    vm.run(CLOSED, [False])
    vm.run(DEFER)
    timers = copy.deepcopy(vm.timers)
    actor["SkeletalMesh"]["bNoSkeletonUpdate"] = True
    vm.run(CLOSED, [False])
    assert not actor["SkeletalMesh"]["bNoSkeletonUpdate"]
    assert vm.timers == timers
    vm.run(OPENED, [True])
    assert not vm.timers and not actor[OVERRIDE]

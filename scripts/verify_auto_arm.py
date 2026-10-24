"""offline checks for the auto-arm blocker"""

import copy
import json

from asset_io import HERE, es, ps
from auto_arm import ALLOW, BIND, EVENTS, PREFIX, REFRESH, SNAIL, TOOL
from kismet import kismet_size, op_type
from settings import AUTO_ARM_BLOCKER


class Ref:
    def __init__(self, container, key):
        self.container, self.key = container, key

    def get(self):
        return self.container[self.key]

    def set(self, value):
        self.container[self.key] = value


def value(item):
    return item.get() if isinstance(item, Ref) else item


class VM:
    def __init__(self, document, actor):
        self.d, self.actor = document, actor
        self.context, self.locals = actor, {}
        self.writes = []

    def eval(self, expr):
        kind = op_type(expr)
        if kind in ("EX_True", "EX_False"):
            return kind == "EX_True"
        if kind in ("EX_NameConst", "EX_IntConst"):
            return expr["Value"]
        if kind == "EX_IntZero":
            return 0
        if kind in ("EX_LocalVariable", "EX_InstanceVariable"):
            return Ref(
                self.locals if kind == "EX_LocalVariable" else self.context,
                expr["Variable"]["New"]["Path"][0],
            )
        if kind == "EX_Context":
            obj = value(self.eval(expr["ObjectExpression"]))
            assert obj is not None, "Unguarded object access"
            prior, self.context = self.context, obj
            try:
                return self.eval(expr["ContextExpression"])
            finally:
                self.context = prior
        if kind == "EX_DynamicCast":
            obj = value(self.eval(expr["Target"]))
            class_name = self.d["Imports"][-expr["ClassPtr"] - 1]["ObjectName"]
            return obj if obj and class_name in obj.get("classes", []) else None
        if kind == "EX_StructMemberContext":
            return Ref(
                value(self.eval(expr["StructExpression"])),
                expr["StructMemberExpression"]["New"]["Path"][0],
            )
        if kind == "EX_ArrayGetByRef":
            array = value(self.eval(expr["ArrayVariable"]))
            index = value(self.eval(expr["ArrayIndex"]))
            assert 0 <= index < len(array), "Unguarded slot access"
            return Ref(array, index)
        if kind in ("EX_LetObj", "EX_LetBool"):
            target = self.eval(expr["VariableExpression"])
            new_value = value(self.eval(expr["AssignmentExpression"]))
            target.set(new_value)
            if kind == "EX_LetBool":
                self.writes.append(target.key)
            return None
        if kind in ("EX_FinalFunction", "EX_LocalFinalFunction"):
            node = expr["StackNode"]
            args = [value(self.eval(p)) for p in expr["Parameters"]]
            if node > 0:
                assert not args
                return self.run(self.d["Exports"][node - 1]["ObjectName"])
            name = self.d["Imports"][-node - 1]["ObjectName"]
            if name == "GetParentActor":
                return self.context.get("parent")
            if name == "GetOwner":
                return self.context["owner"]
            if name == "IsValid":
                return args[0] is not None and not args[0].get("invalid", False)
            if name == "Array_Length":
                return len(args[0])
            if name == "Greater_IntInt":
                return args[0] > args[1]
            if name == "EqualEqual_NameName":
                return args[0] == args[1]
            raise AssertionError(name)
        if kind == "EX_InstanceDelegate":
            return expr["FunctionName"]
        if kind == "EX_AddMulticastDelegate":
            value(self.eval(expr["Delegate"])).append(self.eval(expr["DelegateToAdd"]))
            return None
        raise AssertionError(kind)

    def run(self, name):
        function = es(self.d)[name]
        prior_locals, prior_context = self.locals, self.context
        self.locals = {p["Name"]: None for p in function["LoadedProperties"]}
        self.context = self.actor
        assert (
            sum(map(kismet_size, function["ScriptBytecode"]))
            == function["ScriptBytecodeSize"]
        )
        try:
            for expr in function["ScriptBytecode"]:
                if op_type(expr) == "EX_Return":
                    return
                if op_type(expr) == "EX_JumpIfNot":
                    assert expr["CodeOffset"] == function["ScriptBytecodeSize"] - 3
                    if not value(self.eval(expr["BooleanExpression"])):
                        return
                else:
                    self.eval(expr)
        finally:
            self.locals, self.context = prior_locals, prior_context


def check_auto_arm(assets):
    if not AUTO_ARM_BLOCKER:
        assert (
            "SmallDeform" not in assets
            and "TerrariumSnail_CrackableActor" not in assets
        )
        assert not any(
            e["ObjectName"].startswith(PREFIX)
            for d in assets.values()
            for e in d["Exports"]
        )
        return []
    backpack = es(assets["BackpackRail"])
    for i in range(1, 17):
        assert (
            ps(backpack[f"Item Slot {i}_GEN_VARIABLE"])["AcceptInputItems"]["Value"]
            is False
        )
    for slot in ps(backpack["Slots_GEN_VARIABLE"])["Slots"]["Value"]:
        fields = ps({"Data": slot["Value"]})
        assert fields["bAcceptsInputItems"]["Value"] is False
        assert fields["bCanHoldItem"]["Value"] is True
        assert fields["bUnclickable"]["Value"] is False
    # The corpse keeps its original automatic-input settings.
    for e in assets["AstroCorpse"]["Exports"]:
        assert "AcceptInputItems" not in ps(e)

    for label, asset in [
        ("SmallDeform", TOOL),
        ("TerrariumSnail_CrackableActor", SNAIL),
    ]:
        original = json.loads((HERE / "vanilla" / (asset + ".json")).read_text())
        actual = es(assets[label])
        for old in original["Exports"]:
            current = actual[old["ObjectName"]]
            if label == "SmallDeform":
                data = copy.deepcopy(current.get("Data", []))
                if old["ObjectName"] in [
                    f"AugmentSlot{i}_GEN_VARIABLE" for i in range(1, 4)
                ]:
                    assert ps(current)["AcceptInputItems"]["Value"] is False
                    data = [p for p in data if p["Name"] != "AcceptInputItems"]
                assert data == old.get("Data", [])
            code = copy.deepcopy(current.get("ScriptBytecode"))
            if (
                label == "TerrariumSnail_CrackableActor"
                and old["ObjectName"] == "ReceiveBeginPlay"
            ):
                call = code.pop(-3)
                assert actual[BIND] is assets[label]["Exports"][call["StackNode"] - 1]
            assert code == old.get("ScriptBytecode"), (label, old["ObjectName"])

    document = assets["TerrariumSnail_CrackableActor"]
    food_template = {
        "Name": "FoodSlot",
        "bAcceptsInputItems": True,
        "bCanHoldItem": True,
        "bUnclickable": False,
        "seed": "existing seed",
        "timer": 1234,
    }

    def carrying(owner):
        return {"owner": {"classes": [owner]}} if owner else None

    for owner in [
        "BackpackRail_C",
        "Storage_Medium_C",
        "PlatformSmall_C",
        "AstroCorpse_C",
        None,
    ]:
        for initial in [True, False]:
            food = dict(food_template, bAcceptsInputItems=initial)
            parent = {
                "classes": ["PhysicalItem"],
                "CurrentSlot": {"Component": carrying(owner)},
                **{event: [] for event in EVENTS},
            }
            actor = {"parent": parent, "Slots": {"Slots": [food]}}
            vm = VM(document, actor)
            vm.run(BIND)
            assert food["bAcceptsInputItems"] is (owner != "BackpackRail_C")
            assert all(parent[event] == [handler] for event, handler in EVENTS.items())
            for next_owner in [
                "BackpackRail_C",
                None,
                "Storage_Medium_C",
                "BackpackRail_C",
                "AstroCorpse_C",
            ]:
                parent["CurrentSlot"]["Component"] = carrying(next_owner)
                for event in ["OnPlacedInSlot", "OnSpawnedInSlot"]:
                    vm.run(parent[event][0])
                    assert food["bAcceptsInputItems"] is (
                        next_owner != "BackpackRail_C"
                    )
            parent["CurrentSlot"]["Component"] = carrying("BackpackRail_C")
            vm.run(REFRESH)
            assert food["bAcceptsInputItems"] is False
            vm.run(parent["OnReleasedFromSlotClientSafe"][0])
            assert food["bAcceptsInputItems"] is True, (
                "Release can precede CurrentSlot clearing"
            )
            assert {k: v for k, v in food.items() if k != "bAcceptsInputItems"} == {
                k: v for k, v in food_template.items() if k != "bAcceptsInputItems"
            }
            assert set(vm.writes) == {"bAcceptsInputItems"}
    for slots in [None, {"Slots": []}, {"Slots": [{"Name": "OtherSlot"}]}]:
        vm = VM(document, {"parent": None, "Slots": slots})
        vm.run(BIND)
        vm.run(REFRESH)
        vm.run(ALLOW)
        assert not vm.writes
    imports = {i["ObjectName"] for i in document["Imports"]}
    assert not imports & {
        "GetAllActorsOfClass",
        "K2_SetTimer",
        "K2_SetTimerDelegate",
        "SetSlotAcceptsItems",
    }
    for function in document["Exports"]:
        if function["ObjectName"].startswith(PREFIX):
            assert not any(
                p.get("PropertyFlags") == "CPF_SaveGame"
                for p in function.get("LoadedProperties", [])
            )
    return [
        "auto arms blocked in sixteen main, two auxiliary and three terrain-tool slots; corpse settings retained",
        "terrain-tool and galastropod native gameplay bytecode preserved except the declared initialization hook",
        "carried-snail startup, transfer, spawn and release cases pass; manual feeding fields and existing seeds retained",
        "auto-arm blocker is event driven, without timers or world searches; base build omits both added overrides",
    ]

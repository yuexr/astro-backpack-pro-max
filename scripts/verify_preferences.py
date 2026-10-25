"""Offline save/load checks; the real disk API still needs an in-game test."""

import copy
import fnmatch
import json

from asset_io import es, ps
from kismet import op_type
from printer_preferences import ASSET, EXTENSION, FIELD, LOAD, LOADED, SAVE, SLOT
from printer_tooltip import GET_HIDDEN, HIDDEN, TOGGLE
from verify_behaviors import VM
from verify_printer import PrinterVM


class PreferenceVM(PrinterVM):
    def __init__(self, document, actor, disk):
        super().__init__(document, actor)
        self.disk = disk
        self.reads = 0
        self.writes = 0
        self.fail_write = False
        self.fail_create = False

    def run(self, name, args=()):
        if name in [LOAD, SAVE]:
            return VM.run(self, name, args)
        return super().run(name, args)

    def set(self, target, value, obj, local):
        if op_type(target) == "EX_LocalVariable":
            local[self.name(target["Variable"])] = value
            return
        super().set(target, value, obj, local)

    def eval(self, expr, obj, local):
        kind = op_type(expr)
        if kind == "EX_LocalVariable" and self.name(expr["Variable"]) == "FileSize":
            return local.get("FileSize", 0)
        if kind == "EX_ObjectConst":
            return self.d["Imports"][-expr["Value"] - 1]["ObjectName"]
        if kind == "EX_DynamicCast":
            value = self.eval(expr["Target"], obj, local)
            return (
                value
                if isinstance(value, dict) and value.get("class") == ASSET
                else None
            )
        if kind == "EX_LetObj":
            self.set(
                expr["VariableExpression"],
                self.eval(expr["AssignmentExpression"], obj, local),
                obj,
                local,
            )
            return
        if kind == "EX_CallMath" and expr["StackNode"] < 0:
            name = self.d["Imports"][-expr["StackNode"] - 1]["ObjectName"]
            if name in ["LoadGameFromSlot", "CreateSaveGameObject", "SaveGameToSlot"]:
                args = [self.eval(p, obj, local) for p in expr["Parameters"]]
                if name == "LoadGameFromSlot":
                    assert args == [SLOT, EXTENSION, 0]
                    self.reads += 1
                    try:
                        value = json.loads(self.disk[SLOT + ".sav"])
                        assert isinstance(value.get(FIELD), bool)
                        return value
                    except (KeyError, ValueError, AssertionError, AttributeError):
                        return None
                if name == "CreateSaveGameObject":
                    assert args == [ASSET + "_C"]
                    return None if self.fail_create else {"class": ASSET, FIELD: False}
                assert len(args) == 5 and args[1] == SLOT and args[3:] == [EXTENSION, 0]
                assert op_type(expr["Parameters"][2]) == "EX_LocalVariable"
                if self.fail_write:
                    return (
                        1  # An ignored failure result must not undo the session toggle.
                    )
                value = json.dumps(args[0]).encode()
                self.disk[SLOT + ".sav"] = value
                local["FileSize"] = len(value)
                self.writes += 1
                return 0
        return super().eval(expr, obj, local)


def fresh(local=True):
    return {
        HIDDEN: False,
        LOADED: False,
        "local": local,
        "Printer Output Slot": object(),
        "output": {"state": 2},
        "PrinterVisible": True,
        "REP_ShowPrinterOutputSlotTooltip": True,
        "native_view_calls": 0,
        "state_requests": [],
    }


def check_preferences(assets):
    document = assets["BackpackRail"]
    saved = assets[ASSET]
    cls = es(saved)[ASSET + "_C"]
    assert saved["Imports"][-cls["SuperStruct"] - 1]["ObjectName"] == "SaveGame"
    assert len(saved["Exports"]) == 2 and not cls["FuncMap"] and not cls["Children"]
    assert [p["Name"] for p in cls["LoadedProperties"]] == [FIELD]
    assert ps(es(saved)["Default__" + ASSET + "_C"])[FIELD]["Value"] is False
    runtime_cls = next(e for e in document["Exports"] if "ClassExport" in e["$type"])
    for name in [HIDDEN, LOADED]:
        prop = next(p for p in runtime_cls["LoadedProperties"] if p["Name"] == name)
        assert "CPF_Net" not in prop["PropertyFlags"]
        assert "CPF_SaveGame" not in prop["PropertyFlags"]

    disk = {"existing-world.savegame": b"untouched world data"}
    actor = fresh()
    vm = PreferenceVM(document, actor, disk)
    assert vm.run(GET_HIDDEN) is False
    for _ in range(100):
        vm.native_view()
    assert vm.reads == 1 and vm.writes == 0
    assert actor["state_requests"] == [2] * 100
    vm.run(TOGGLE)
    assert actor[HIDDEN] and actor["output"]["state"] == 0
    assert json.loads(disk[SLOT + ".sav"])[FIELD] is True
    # New backpack instances represent a restart, world switch or respawn.
    for _ in range(3):
        actor = fresh()
        vm = PreferenceVM(document, actor, disk)
        vm.native_view()
        assert actor[HIDDEN] and actor["state_requests"] == [0]
        assert vm.reads == 1 and vm.writes == 0
        for focused in [True, False, True, False]:
            actor["output"]["focus"] = focused
            vm.native_view()
            assert actor["output"]["state"] == (2 if focused else 0)
            assert actor["output"]["VisibilityControl"] == 0
            assert actor[HIDDEN] and vm.reads == 1 and vm.writes == 0
    vm.run(TOGGLE)
    assert not actor[HIDDEN] and json.loads(disk[SLOT + ".sav"])[FIELD] is False
    assert PreferenceVM(document, fresh(), disk).run(GET_HIDDEN) is False
    assert disk["existing-world.savegame"] == b"untouched world data"
    assert [n for n in disk if fnmatch.fnmatch(n, "*.savegame")] == [
        "existing-world.savegame"
    ]

    for content in [
        b"broken data",
        b"{}",
        b'{"class":"OtherSave","TooltipHidden":true}',
    ]:
        actor = fresh()
        vm = PreferenceVM(document, actor, {SLOT + ".sav": content})
        assert vm.run(GET_HIDDEN) is False
        assert actor[LOADED] and vm.reads == 1 and vm.writes == 0
        vm.native_view()
        assert vm.reads == 1
    for failure in ["fail_write", "fail_create"]:
        actor = fresh()
        disk = {}
        vm = PreferenceVM(document, actor, disk)
        setattr(vm, failure, True)
        vm.run(TOGGLE)
        assert actor[HIDDEN] and actor["output"]["state"] == 0 and vm.writes == 0
        assert not disk

    host_disk = {}
    client_disk = {SLOT + ".sav": json.dumps({"class": ASSET, FIELD: True}).encode()}
    host = PreferenceVM(document, fresh(), host_disk)
    client = PreferenceVM(document, fresh(), client_disk)
    assert host.run(GET_HIDDEN) is False and client.run(GET_HIDDEN) is True
    old_client = copy.deepcopy(client_disk)
    host.run(TOGGLE)
    assert host.actor[HIDDEN] and client_disk == old_client
    remote = PreferenceVM(document, fresh(False), host_disk)
    for name in [GET_HIDDEN, TOGGLE, LOAD, SAVE]:
        remote.run(name)
    assert remote.reads == remote.writes == 0 and not remote.actor[LOADED]
    # A backpack can become locally owned after its first callbacks.
    remote.actor["local"] = True
    assert remote.run(GET_HIDDEN) is True and remote.reads == 1
    for _ in range(20):
        host.run(TOGGLE)
    assert host.reads == 1 and host.writes == 21
    assert json.loads(host_disk[SLOT + ".sav"])[FIELD] == host.actor[HIDDEN]
    return [
        "printer preference uses a standalone SaveGame class and explicit generic .sav calls; simulated world files untouched",
        "local preference survives simulated restarts, world changes and fresh backpacks; initial hidden recipe never requests a show animation",
        "missing, malformed or wrong-class data defaults to shown; failed writes or object creation leave the session toggle working",
        "host/client storage kept separate; remote actors never read/write and late local ownership loads correctly",
        "preference reads once per local backpack and writes only on button presses; 20 rapid toggles retain the last choice",
    ]

"""Exercise carried equipment transitions using the cooked Blueprint code."""

import copy
import json

from asset_io import HERE, es, ps
from auto_arm_items import BIND, BLOCK, EVENTS, ITEMS, PREFIX, REFRESH, RESTORE, SAVED
from settings import AUTO_ARM_BLOCKER
from verify_auto_arm import VM


def check_equipment(assets):
    if not AUTO_ARM_BLOCKER:
        assert not {path.rsplit("/", 1)[-1] for path in ITEMS} & assets.keys()
        return []

    for path in ITEMS:
        label = path.rsplit("/", 1)[-1]
        document = assets[label]
        original = json.loads((HERE / "vanilla" / (path + ".json")).read_text())
        actual = es(document)
        for old in original["Exports"]:
            current = actual[old["ObjectName"]]
            code = copy.deepcopy(current.get("ScriptBytecode"))
            if old["ObjectName"] == "ReceiveBeginPlay":
                call = code.pop(-3)
                assert document["Exports"][call["StackNode"] - 1]["ObjectName"] == BIND
            assert code == old.get("ScriptBytecode"), (label, old["ObjectName"])
            data = copy.deepcopy(current.get("Data", []))
            if old["ObjectName"].startswith("Default__"):
                data = [field for field in data if field["Name"] != SAVED]
            assert data == old.get("Data", []), (label, old["ObjectName"])
        cls = next(e for e in document["Exports"] if "ClassExport" in e["$type"])
        saved = next(
            field for field in cls["LoadedProperties"] if field["Name"] == SAVED
        )
        assert saved["PropertyFlags"] == "CPF_Transient"
        assert saved["Inner"]["SerializedType"] == "NameProperty"
        assert ps(actual["Default__" + cls["ObjectName"]])[SAVED]["Value"] == []

        for owner in (
            "BackpackRail_C",
            "SmallDeform_C",
            "PlatformSmall_C",
            "Storage_Medium_C",
            "AstroCorpse_C",
            None,
        ):

            def carrying(name):
                return {"owner": {"classes": [name]}} if name else None

            rows = [
                {
                    "Name": "Fuel",
                    "bAcceptsInputItems": True,
                    "bCanHoldItem": True,
                    "bUnclickable": False,
                    "item": "existing fuel",
                },
                {"Name": "Input 2", "bAcceptsInputItems": True, "item": None},
                {
                    "Name": "Disabled output",
                    "bAcceptsInputItems": False,
                    "item": "output",
                },
            ]
            expected = copy.deepcopy(rows)
            actor = {
                "SlotsComponent": {"Slots": rows},
                "CurrentSlot": {"Component": carrying(owner)},
                SAVED: [],
                **{event: [] for event in EVENTS},
            }
            vm = VM(document, actor)
            vm.run(BIND)
            assert all(actor[event] == [handler] for event, handler in EVENTS.items())
            is_carried = owner in ("BackpackRail_C", "SmallDeform_C")
            assert [r["bAcceptsInputItems"] for r in rows] == (
                [False, False, False] if is_carried else [True, True, False]
            )
            # Repeated placement events must keep the original restore values.
            for _ in range(3):
                vm.run(REFRESH)
            assert actor[SAVED] == (["Fuel", "Input 2"] if is_carried else [])
            for destination in (
                "BackpackRail_C",
                "SmallDeform_C",
                None,
                "Storage_Medium_C",
                "BackpackRail_C",
                "AstroCorpse_C",
            ):
                actor["CurrentSlot"]["Component"] = carrying(destination)
                for event in ("OnPlacedInSlot", "OnSpawnedInSlot"):
                    vm.run(actor[event][0])
                    blocked = destination in ("BackpackRail_C", "SmallDeform_C")
                    assert [r["bAcceptsInputItems"] for r in rows] == (
                        [False, False, False] if blocked else [True, True, False]
                    )
            actor["CurrentSlot"]["Component"] = carrying("BackpackRail_C")
            vm.run(REFRESH)
            # Release still works while the old CurrentSlot is set.
            vm.run(actor["OnReleasedFromSlotClientSafe"][0])
            assert rows == expected and actor[SAVED] == []
            # Slots created/reordered by the native printer are matched by name.
            vm.run(REFRESH)
            rows.reverse()
            vm.run(RESTORE)
            assert rows == list(reversed(expected))
            vm.run(REFRESH)
            rows.append({"Name": "New input", "bAcceptsInputItems": True})
            vm.run(REFRESH)
            assert all(not row["bAcceptsInputItems"] for row in rows)
            vm.run(RESTORE)
            assert rows[-1]["bAcceptsInputItems"] is True
            assert set(vm.writes) == {"bAcceptsInputItems"}

        for component in (None, {"Slots": []}):
            actor = {
                "SlotsComponent": component,
                "CurrentSlot": {"Component": None},
                SAVED: [],
                **{event: [] for event in EVENTS},
            }
            vm = VM(document, actor)
            for function in (BIND, REFRESH, RESTORE, BLOCK):
                vm.run(function)
            assert not vm.writes
        # No new native gameplay hooks besides initialization, and no polling.
        assert not any(
            e["ObjectName"].startswith(PREFIX)
            and any(
                "SaveGame" in p.get("PropertyFlags", "")
                for p in e.get("LoadedProperties", [])
            )
            for e in document["Exports"]
        )

    return [
        "generator, portable smelter, small printer and jetpack input flags follow backpack and terrain-tool placement",
        "equipment startup, transfers, repeated placement and stale-slot release cases pass; normal ground/storage/corpse input restored",
        "only previously enabled slot inputs are restored, matched by name; existing contents and manual-placement flags retained",
        "equipment native gameplay bytecode retained except initialization; restore records are transient and feature overrides are optional",
    ]

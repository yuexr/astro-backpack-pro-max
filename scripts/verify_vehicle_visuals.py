"""check that hiding carried items doesn't also hide the backpack shell"""

import json

import numpy as np
from asset_io import HERE, es, ps, xyz


def check_vehicle_visuals(assets, geometry):
    document = assets["BackpackRail"]
    exports = es(document)
    nodes = {}
    for index, entry in enumerate(document["Exports"], 1):
        fields = ps(entry)
        if "InternalVariableName" in fields:
            nodes[index] = entry
    by_name = {
        ps(entry)["InternalVariableName"]["Value"]: index
        for index, entry in nodes.items()
    }

    def children(index):
        return [
            p["Value"] for p in ps(nodes[index]).get("ChildNodes", {}).get("Value", [])
        ]

    def descendants(index):
        found = set()
        pending = children(index)
        while pending:
            child = pending.pop()
            assert child not in found, "duplicate or cyclic component attachment"
            found.add(child)
            pending.extend(children(child))
        return found

    body = by_name["backpack_mk2"]
    items = by_name["Item Slots"]
    assert items in children(body)
    visuals = [f"NativeBackpackSocket{i}" for i in range(1, 17)] + [
        "Compact_" + part for part in geometry["front_components"]
    ]
    item_branch = descendants(items)
    assert {
        ps(nodes[index])["InternalVariableName"]["Value"] for index in item_branch
    } == {f"Item Slot {i}" for i in range(1, 17)}
    for name in visuals:
        assert by_name[name] in children(body)
        assert by_name[name] not in item_branch

    # The old item branch had only a translation. Moving the visuals up one level
    # needs that translation removed from their local positions, not applied twice.
    native = json.loads(
        (HERE / "vanilla/Astro/Content/Items/BackpackRail.json").read_text()
    )
    original = es(native)
    item_fields = ps(original["Item Slots_GEN_VARIABLE"])
    assert (
        "RelativeRotation" not in item_fields and "RelativeScale3D" not in item_fields
    )
    offset = np.array([float(xyz(item_fields["RelativeLocation"])[k]) for k in "XYZ"])
    for i, name in enumerate(visuals):
        if name.startswith("NativeBackpackSocket"):
            expected = np.array(
                [
                    geometry["socket_centre_native_x"],
                    (-40 if i % 2 == 0 else 40)
                    if i < 8
                    else (-18 if i % 2 == 0 else 18),
                    [47.0, 14.3, -18.1, -51.0][i % 8 // 2],
                ]
            )
        else:
            expected = np.zeros(3)
        actual = np.array(
            [
                float(xyz(ps(exports[name + "_GEN_VARIABLE"])["RelativeLocation"])[k])
                for k in "XYZ"
            ]
        )
        assert np.allclose(actual, expected, atol=1e-6, rtol=0), name
        previous_local = (expected - offset).astype(np.float32).astype(float)
        assert np.allclose(actual, previous_local + offset, atol=8e-6, rtol=0), name

    # Slot transforms and the native item-hiding code keep their existing paths.
    for i in range(1, 17):
        assert by_name[f"Item Slot {i}"] in item_branch
    assert (
        exports["backpack_mk2_GEN_VARIABLE"]["Data"]
        == original["backpack_mk2_GEN_VARIABLE"]["Data"]
    )

    # Corpse backpacks keep their previous attachment hierarchy.
    corpse = assets["AstroCorpse"]
    corpse_exports = es(corpse)
    parent = next(
        e
        for e in corpse["Exports"]
        if ps(e).get("InternalVariableName", {}).get("Value") == "ItemSlots"
    )
    attached = {
        corpse["Exports"][p["Value"] - 1]["ObjectName"]
        for p in ps(parent)["ChildNodes"]["Value"]
    }
    assert all("SCS_Node_" + name in attached for name in visuals)
    for name in visuals:
        assert "SkeletalMesh" in ps(corpse_exports[name + "_GEN_VARIABLE"])
    return [
        "custom shell and sockets sit outside the carried-item visibility branch; all 16 item slots stay inside it",
        "custom visual positions unchanged after reattachment; native body and death-backpack hierarchy unchanged",
    ]

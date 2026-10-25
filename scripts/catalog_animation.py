"""Add a completion notification without changing native bone motion or graphs."""

import copy
import hashlib
import json
import subprocess

from asset_io import HERE, es, name, ps
from blueprint import Blueprint
from catalog import COMPLETE
from game_assets import PAK, REPAK, extract

ANIM = "Astro/Content/Animations/PortableDevices/BackpackCatalog/BackpackCatalog_AnimBP"
CREATIVE_ANIM = "Astro/Content/Animations/PortableDevices/BackpackCatalog/BackpackCatalogCreative_AnimBP"
ANIMATIONS = [ANIM]
SEQUENCE = "Astro/Content/Animations/PortableDevices/BackpackCatalog/BackpackCatalog_PanelDeactivate"
DONOR = "Astro/Content/Animations/PortableDevices/BackpackCatalog/BackpackCatalog_ButtonCaseClose"
NOTIFY = "BPM_CatalogClosedPose"


def verify_sources():
    manifest = json.loads((HERE / "catalog-completion-native.json").read_text())
    for member, expected in manifest.items():
        payload = subprocess.check_output([str(REPAK), "get", str(PAK), member])
        assert hashlib.sha256(payload).hexdigest() == expected, member
        cached = HERE / "vanilla" / member
        assert not cached.exists() or cached.read_bytes() == payload, member


def completion_assets():
    verify_sources()
    animations = [(path, add_completion_handler(extract(path))) for path in ANIMATIONS]
    sequence = add_sequence_notify(extract(SEQUENCE), extract(DONOR))
    return animations + [(SEQUENCE, sequence)]


def add_completion_handler(animation):
    editor = Blueprint(animation)
    engine = editor.imp("/Script/Engine", kind="Package")
    anim_instance = editor.imp("AnimInstance", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    owner = editor.call(editor.imp("GetOwningActor", anim_instance, "Function"))
    notify_function = editor.function(
        "AnimNotify_" + NOTIFY,
        [
            editor.guard(editor.call(valid, owner)),
            editor.ctx(
                owner,
                editor.ex(
                    "EX_VirtualFunction",
                    VirtualFunctionName=editor.name(COMPLETE),
                    Parameters=[],
                ),
            ),
        ],
    )
    animation["Exports"][notify_function - 1]["FunctionFlags"] = (
        "FUNC_Event, FUNC_Public, FUNC_BlueprintEvent"
    )
    return animation


def add_sequence_notify(sequence, source):
    old = ps(es(source)[DONOR.rsplit("/", 1)[-1]])["Notifies"]
    notify = copy.deepcopy(old)
    assert len(notify["Value"]) == 1
    fields = {field["Name"]: field for field in notify["Value"][0]["Value"]}
    fields["NotifyName"]["Value"] = NOTIFY
    fields["Notify"]["Value"] = 0
    fields["NotifyStateClass"]["Value"] = 0
    fields["TriggerTimeOffset"]["Value"] = -0.0001
    fields["SegmentLength"]["Value"] = 0.5
    fields["LinkValue"]["Value"] = 0.5
    fields["LinkedSequence"]["Value"] = 1
    fields["bTriggerOnDedicatedServer"]["Value"] = False
    # A point notify has an unused, zeroed end link in the native donor.
    assert (
        next(
            field
            for field in fields["EndLink"]["Value"]
            if field["Name"] == "LinkedSequence"
        )["Value"]
        == 0
    )
    source_names = set(source["NameMap"])

    def copy_names(value):
        if isinstance(value, str) and value in source_names:
            name(sequence, value)
        elif isinstance(value, dict):
            # Property tags serialize their type name separately from the JSON
            # class name (for example, BoolPropertyData -> BoolProperty).
            kind = value.get("$type", "").split(",")[0].rsplit(".", 1)[-1]
            if kind.endswith("PropertyData"):
                name(sequence, kind.removesuffix("Data"))
            for child in value.values():
                copy_names(child)
        elif isinstance(value, list):
            for child in value:
                copy_names(child)

    copy_names(notify)
    name(sequence, NOTIFY)
    asset = es(sequence)[SEQUENCE.rsplit("/", 1)[-1]]
    assert "Notifies" not in ps(asset)
    asset["Data"].append(notify)
    return sequence

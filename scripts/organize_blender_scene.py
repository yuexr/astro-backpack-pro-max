"""One-shot collection cleanup for current and future luxe Blender files.

Run in Blender with -- --input SOURCE.blend --output DESTINATION.blend.
Import organize_scene() from a modeling script before its final save.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy

PREVIEW = "Luxe preview cameras and lights"
MODEL = "Backpack model"
REFERENCES = "Vanilla preview references"


def fingerprint(scene):
    """Fingerprint visible content independently of collection membership."""
    objects = {}
    for obj in scene.objects:
        item = {
            "type": obj.type,
            "matrix": [list(r) for r in obj.matrix_world],
            "hide_render": obj.hide_render,
            "properties": dict(obj.items()),
        }
        if obj.type == "MESH":
            item.update(
                vertices=[list(v.co) for v in obj.data.vertices],
                faces=[
                    (list(p.vertices), p.material_index, p.use_smooth)
                    for p in obj.data.polygons
                ],
                materials=[m.name if m else None for m in obj.data.materials],
                uv_layers={
                    u.name: [list(p.uv) for p in u.data] for u in obj.data.uv_layers
                },
                modifiers=[(m.name, m.type) for m in obj.modifiers],
            )
        elif obj.type == "LIGHT":
            item.update(
                kind=obj.data.type,
                energy=obj.data.energy,
                color=list(obj.data.color),
                size=getattr(obj.data, "size", None),
            )
        elif obj.type == "CAMERA":
            item.update(
                kind=obj.data.type,
                lens=obj.data.lens,
                ortho_scale=obj.data.ortho_scale,
                clip_start=obj.data.clip_start,
                clip_end=obj.data.clip_end,
            )
        objects[obj.name] = hashlib.sha256(
            json.dumps(item, sort_keys=True, default=str).encode()
        ).hexdigest()
    materials = {}
    for mat in bpy.data.materials:
        values = {
            "diffuse": list(mat.diffuse_color),
            "metallic": mat.metallic,
            "roughness": mat.roughness,
        }
        if mat.node_tree:
            values["inputs"] = [
                (
                    n.name,
                    s.identifier,
                    str(s.default_value[:])
                    if hasattr(s.default_value, "__len__")
                    else str(s.default_value),
                )
                for n in mat.node_tree.nodes
                for s in n.inputs
                if hasattr(s, "default_value")
            ]
            values["links"] = [
                (
                    l.from_node.name,
                    l.from_socket.identifier,
                    l.to_node.name,
                    l.to_socket.identifier,
                )
                for l in mat.node_tree.links
            ]
        materials[mat.name] = hashlib.sha256(
            json.dumps(values, sort_keys=True).encode()
        ).hexdigest()
    return {
        "objects": objects,
        "materials": materials,
        "camera": scene.camera.name if scene.camera else None,
    }


def category(obj):
    name = obj.name
    if obj.type in ("CAMERA", "LIGHT"):
        return (PREVIEW,)
    if name.startswith("Original"):
        return (REFERENCES, "Native body")
    if name.startswith("NativeSocket"):
        return (REFERENCES, "Socket previews")
    if name.startswith(("BatteryCell_", "BatterySeparator_")) or name == "OxygenGauge":
        return (REFERENCES, "Gauge previews")
    if name.startswith(("Pad_", "PadOutline_", "LuxePadStar_", "LuxePadDiamond_")):
        return (
            MODEL,
            "Pads and decorations",
            "Left pads" if "_-1_" in name else "Right pads",
        )
    if name.startswith(("LuxeElbow", "LuxeShoulder")):
        return (MODEL, "Shoulder details")
    if name.startswith("LuxeOxygen"):
        return (MODEL, "Oxygen details")
    if name.startswith(("Battery", "LowerBattery", "LuxeBattery")):
        return (MODEL, "Battery and power accent")
    if name.startswith(("RoundOuterRail", "Binder")):
        return (MODEL, "Rails and bindings")
    if name.startswith("LuxeYueMorse"):
        return (MODEL, "Morse detail")
    if name.startswith("SmoothFrontBase"):
        return (MODEL, "Body", "Front casing")
    if name.startswith(("LuxeNativeRearShell", "LuxeRear")):
        return (MODEL, "Body", "Rear casing and engraving")
    return (MODEL, "Other model parts")


def organize_scene(scene=None):
    scene = scene or bpy.context.scene
    before = fingerprint(scene)
    existing = set(bpy.data.collections)
    paths = {}
    for obj in list(scene.objects):
        path = category(obj)
        parent = scene.collection
        for depth, name in enumerate(path, 1):
            key = path[:depth]
            if key not in paths:
                collection = bpy.data.collections.get(name) or bpy.data.collections.new(
                    name
                )
                if collection.name not in parent.children:
                    parent.children.link(collection)
                paths[key] = collection
            parent = paths[key]
        for collection in list(obj.users_collection):
            if collection != parent:
                collection.objects.unlink(obj)
        if obj.name not in parent.objects:
            parent.objects.link(obj)
    desired = set(paths.values())
    # Remove empty draft-era collections only; their objects have been relinked.
    removed = []
    for collection in existing - desired:
        if not collection.objects and not collection.children:
            removed.append(collection.name)
            bpy.data.collections.remove(collection)
    preview = paths[(PREVIEW,)]
    preview.hide_viewport = False  # Eye toggle below stays easy to turn back on.
    preview.hide_render = False

    def hide_preview(layer):
        if layer.collection == preview:
            layer.exclude = False
            layer.hide_viewport = True
        for child in layer.children:
            hide_preview(child)

    for layer in scene.view_layers:
        hide_preview(layer.layer_collection)
    assert not scene.collection.objects
    assert all(len(o.users_collection) == 1 for o in scene.objects)
    assert all(o.type in ("CAMERA", "LIGHT") for o in preview.objects)
    assert sum(o.type in ("CAMERA", "LIGHT") for o in scene.objects) == len(
        preview.objects
    )
    after = fingerprint(scene)
    assert before == after, (
        "Geometry, UVs, materials, transforms or render objects changed"
    )
    return {
        "objects": len(scene.objects),
        "meshes": sum(o.type == "MESH" for o in scene.objects),
        "preview_objects": len(preview.objects),
        "preview_hidden_in_viewport": True,
        "preview_enabled_for_render": True,
        "removed_empty_collections": sorted(removed),
        "content_unchanged": True,
        "layout": {" / ".join(k): len(c.objects) for k, c in paths.items()},
    }


def main():
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render-check", action="store_true")
    options = parser.parse_args(args)
    source = options.input.resolve()
    target = options.output.resolve()
    assert source.exists() and source != target and not target.exists()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene = bpy.context.scene
    before = fingerprint(scene)
    settings = (
        scene.render.resolution_x,
        scene.render.resolution_y,
        scene.render.resolution_percentage,
        scene.render.filepath,
        scene.cycles.samples,
    )
    if options.render_check:
        scene.render.resolution_x = 300
        scene.render.resolution_y = 300
        scene.render.resolution_percentage = 100
        scene.cycles.samples = 8
        scene.render.filepath = str(target.parent / "preview-before.png")
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pixels_before = list(image.pixels)
        bpy.data.images.remove(image)
    result = organize_scene(scene)
    if options.render_check:
        scene.render.filepath = str(target.parent / "preview-after.png")
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pixels_after = list(image.pixels)
        bpy.data.images.remove(image)
        assert len(pixels_before) == len(pixels_after) and pixels_before
        difference = max(abs(a - b) for a, b in zip(pixels_before, pixels_after))
        assert difference < 0.002, (
            f"Render changed: maximum channel difference {difference}"
        )
        result["render_max_difference"] = difference
    (
        scene.render.resolution_x,
        scene.render.resolution_y,
        scene.render.resolution_percentage,
        scene.render.filepath,
        scene.cycles.samples,
    ) = settings
    assert fingerprint(scene) == before
    bpy.context.preferences.filepaths.save_version = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(target), compress=True)
    bpy.ops.wm.open_mainfile(filepath=str(target))
    assert fingerprint(bpy.context.scene) == before
    preview = bpy.data.collections[PREVIEW]

    def find(layer):
        if layer.collection == preview:
            return layer
        for child in layer.children:
            found = find(child)
            if found:
                return found

    assert all(
        find(v.layer_collection).hide_viewport for v in bpy.context.scene.view_layers
    )
    result.update(
        input=str(source),
        output=str(target),
        reopen_verified=True,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    )
    target.with_suffix(".organization.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

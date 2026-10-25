"""Check cooked function owners against this game's native registrations."""

import hashlib
import json
import struct

from asset_io import HERE
from game_assets import PAK


def check_material_bindings(document):
    manifest = json.loads((HERE / "catalog-palette-native.json").read_text())
    exe = PAK.parents[2] / "Binaries/Win64/Astro-Win64-Shipping.exe"
    raw = exe.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["exe_sha256"]
    pe = struct.unpack_from("<I", raw, 0x3C)[0]
    count = struct.unpack_from("<H", raw, pe + 6)[0]
    optional_size = struct.unpack_from("<H", raw, pe + 20)[0]
    image_base = struct.unpack_from("<Q", raw, pe + 24 + 24)[0]
    sections = []
    for i in range(count):
        at = pe + 24 + optional_size + 40 * i
        size, rva, _, offset = struct.unpack_from("<IIII", raw, at + 8)
        sections.append((rva, size, offset))

    def offset(rva):
        start, _, at = next(s for s in sections if s[0] <= rva < s[0] + s[1])
        return at + rva - start

    owners = []
    for function, entry in manifest["functions"].items():
        at = offset(int(entry["name_pointer_rva"], 16))
        native_owner = struct.unpack_from("<Q", raw, at - 16)[0] - image_base
        name_rva = struct.unpack_from("<Q", raw, at)[0] - image_base
        end = raw.index(b"\0", offset(name_rva))
        assert raw[offset(name_rva) : end].decode() == function
        assert native_owner == int(entry["owner_getter_rva"], 16)
        imports = [e for e in document["Imports"] if e["ObjectName"] == function]
        assert len(imports) == 1, function
        parent = imports[0]["OuterIndex"]
        assert (
            parent < 0
            and document["Imports"][-parent - 1]["ObjectName"] == entry["owner"]
        ), "Native function imported under wrong class: " + function
        owners.append(native_owner)
    # Both functions are declared by the same native PrimitiveComponent class.
    assert len(set(owners)) == 1

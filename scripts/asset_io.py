"""mesh data and Unreal asset helpers"""

import copy
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def gltf(path):
    d = json.loads(path.read_text())
    blob = path.with_suffix(".bin").read_bytes()

    def ac(i):
        a = d["accessors"][i]
        b = d["bufferViews"][a["bufferView"]]
        n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
        return np.frombuffer(
            blob,
            {5126: "<f4", 5123: "<u2", 5121: "u1"}[a["componentType"]],
            count=a["count"] * n,
            offset=b.get("byteOffset", 0) + a.get("byteOffset", 0),
        ).reshape(-1, n)

    p = d["meshes"][0]["primitives"][0]
    return (
        d,
        {k: ac(i).copy() for k, i in p["attributes"].items()},
        ac(p["indices"]).reshape(-1, 3).copy(),
    )


def ps(e):
    return {p["Name"]: p for p in e.get("Data", [])}


def xyz(p):
    return p["Value"][0]["Value"]


def name(d, n):
    if n not in d["NameMap"]:
        d["NameMap"].append(n)
    return n


def prop(d, t, n, v):
    return {
        "$type": f"UAssetAPI.PropertyTypes.Objects.{t}PropertyData, UAssetAPI",
        "Name": name(d, n),
        "ArrayIndex": 0,
        "PropertyGuid": None,
        "IsZero": False,
        "PropertyTagFlags": "None",
        "PropertyTypeName": None,
        "PropertyTagExtensions": "NoExtension",
        "Value": v,
    }


def setbool(d, e, n, v):
    if n in ps(e):
        ps(e)[n]["Value"] = v
    else:
        e["Data"].append(prop(d, "Bool", n, v))


def location(d, e, values):
    if "RelativeLocation" not in ps(e):
        e["Data"].append(
            copy.deepcopy(
                next(
                    p
                    for x in d["Exports"]
                    for p in x.get("Data", [])
                    if p["Name"] == "RelativeLocation"
                )
            )
        )
    xyz(ps(e)["RelativeLocation"]).update(dict(zip("XYZ", map(float, values))))


def append(d, e):
    d["Exports"].append(e)
    d["DependsMap"].append([])
    return len(d["Exports"])


def es(d):
    return {e["ObjectName"]: e for e in d["Exports"]}

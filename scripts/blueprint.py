"""helpers for editing Blueprints"""

import base64
import copy

from asset_io import append, name, prop
from kismet import kismet_size


class Blueprint:
    def __init__(self, document, function_template=None):
        self.d = document
        self.cls = next(e for e in document["Exports"] if "ClassExport" in e["$type"])
        self.cid = document["Exports"].index(self.cls) + 1
        self.function_template = function_template

    def name(self, value):
        return name(self.d, value)

    def imp(self, value, outer=0, kind="Class", package="/Script/CoreUObject"):
        for i, entry in enumerate(self.d["Imports"]):
            if (entry["ObjectName"], entry["OuterIndex"], entry["ClassName"]) == (
                value,
                outer,
                kind,
            ):
                return -i - 1
        self.d["Imports"].append(
            {
                "$type": "UAssetAPI.Import, UAssetAPI",
                "ObjectName": self.name(value),
                "OuterIndex": outer,
                "ClassPackage": self.name(package),
                "ClassName": self.name(kind),
                "PackageName": None,
                "bImportOptional": False,
            }
        )
        return -len(self.d["Imports"])

    def copy_import(self, source, index):
        assert index < 0
        entry = source["Imports"][-index - 1]
        outer = (
            self.copy_import(source, entry["OuterIndex"]) if entry["OuterIndex"] else 0
        )
        return self.imp(
            entry["ObjectName"], outer, entry["ClassName"], entry["ClassPackage"]
        )

    def copy_names(self, source, value):
        source_names = set(source["NameMap"])

        def walk(item):
            if isinstance(item, str) and item in source_names:
                self.name(item)
            elif isinstance(item, dict):
                for child in item.values():
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)

        walk(value)

    def ex(self, kind, **fields):
        return {
            "$type": "UAssetAPI.Kismet.Bytecode.Expressions." + kind + ", UAssetAPI",
            **fields,
        }

    def ptr(self, field=None, owner=None):
        return {
            "$type": "UAssetAPI.Kismet.Bytecode.KismetPropertyPointer, UAssetAPI",
            "New": {
                "$type": "UAssetAPI.UnrealTypes.FFieldPath, UAssetAPI",
                "Path": [self.name(field)] if field else [],
                "ResolvedOwner": self.cid if owner is None else owner,
            },
        }

    def var(self, field):
        return self.ex("EX_InstanceVariable", Variable=self.ptr(field))

    def call(self, index, *args, local=False, math=False):
        kind = (
            "EX_CallMath"
            if math
            else "EX_LocalFinalFunction"
            if local
            else "EX_FinalFunction"
        )
        return self.ex(kind, StackNode=index, Parameters=list(args))

    def ctx(self, obj, expression):
        return self.ex(
            "EX_Context",
            ObjectExpression=obj,
            Offset=kismet_size(expression),
            PropertyType=0,
            RValuePointer=self.ptr(owner=0),
            ContextExpression=expression,
        )

    def guard(self, condition):
        return self.ex("EX_JumpIfNot", CodeOffset=0, BooleanExpression=condition)

    def assign_bool(self, field, value):
        return self.ex(
            "EX_LetBool", VariableExpression=self.var(field), AssignmentExpression=value
        )

    def function(self, label, body):
        end = sum(map(kismet_size, body))
        for instruction in body:
            if "CodeOffset" in instruction:
                instruction["CodeOffset"] = end
        body += [
            self.ex("EX_Return", ReturnExpression=self.ex("EX_Nothing")),
            self.ex("EX_EndOfScript"),
        ]
        # start with a function from this asset; add parameters separately if needed
        source = self.function_template or next(
            e for e in self.d["Exports"] if "FunctionExport" in e["$type"]
        )
        function = copy.deepcopy(source)
        engine = self.imp("/Script/CoreUObject", kind="Package")
        function.update(
            ObjectName=self.name(label),
            OuterIndex=self.cid,
            ClassIndex=self.imp("Function", engine),
            TemplateIndex=self.imp("Default__Function", engine, "Function"),
            SuperStruct=0,
            SuperIndex=0,
            Children=[],
            LoadedProperties=[],
            Data=[],
            ScriptBytecode=body,
            ScriptBytecodeSize=sum(map(kismet_size, body)),
            ScriptBytecodeRaw=None,
            SerialSize=0,
            SerialOffset=0,
            FunctionFlags="FUNC_Public, FUNC_BlueprintCallable",
            Extras=base64.b64encode(b"\0" * 8).decode(),
        )
        dependencies = {self.cid}

        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if (
                        key in ["StackNode", "ResolvedOwner"]
                        and isinstance(child, int)
                        and child
                    ):
                        dependencies.add(child)
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(body)
        function["CreateBeforeSerializationDependencies"] = sorted(dependencies)
        function["SerializationBeforeSerializationDependencies"] = []
        function["SerializationBeforeCreateDependencies"] = []
        function["CreateBeforeCreateDependencies"] = [self.cid]
        index = append(self.d, function)
        self.cls["FuncMap"].append([self.name(label), index])
        self.cls["Children"].insert(0, index)
        self.cls["CreateBeforeSerializationDependencies"].append(index)
        return index

    def bool_field(self, label, default=False):
        field = copy.deepcopy(
            next(
                p for p in self.cls["LoadedProperties"] if "FBoolProperty" in p["$type"]
            )
        )
        field.update(
            Name=self.name(label),
            PropertyFlags="CPF_None",
            RepNotifyFunc="None",
            RepIndex=0,
        )
        self.cls["LoadedProperties"].append(field)
        cdo = next(
            e
            for e in self.d["Exports"]
            if e["ObjectName"] == "Default__" + self.cls["ObjectName"]
        )
        cdo["Data"].append(prop(self.d, "Bool", label, default))


def replace_instruction(function, index, replacement):
    """Replace an instruction and adjust the jumps after it."""
    code = function["ScriptBytecode"]
    assert sum(map(kismet_size, code)) == function["ScriptBytecodeSize"]
    old_end = sum(map(kismet_size, code[: index + 1]))
    delta = kismet_size(replacement) - kismet_size(code[index])
    code[index] = replacement

    def relocate(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in [
                    "CodeOffset",
                    "PushingAddress",
                    "EndGotoOffset",
                    "NextOffset",
                ]:
                    if child >= old_end:
                        value[key] = child + delta
                else:
                    relocate(child)
        elif isinstance(value, list):
            for child in value:
                relocate(child)

    relocate(code)
    function["ScriptBytecodeSize"] += delta
    assert sum(map(kismet_size, code)) == function["ScriptBytecodeSize"]
    return delta

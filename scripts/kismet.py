"""byte sizes for our Blueprint instructions"""


def op_type(x):
    return x["$type"].split(".")[-1].split(",")[0]


def kismet_size(x):
    t = op_type(x)
    if t in [
        "EX_True",
        "EX_False",
        "EX_Self",
        "EX_IntZero",
        "EX_Nothing",
        "EX_EndOfScript",
        "EX_PopExecutionFlow",
    ]:
        return 1
    if t in ["EX_InstanceVariable", "EX_LocalVariable", "EX_ObjectConst"]:
        return 9
    if t in ["EX_FloatConst", "EX_IntConst"]:
        return 5
    if t in ["EX_VectorConst", "EX_RotationConst"]:
        return 13
    if t == "EX_ByteConst":
        return 2
    if t in ["EX_VirtualFunction", "EX_LocalVirtualFunction"]:
        return 14 + sum(map(kismet_size, x["Parameters"]))
    if t == "EX_StringConst":
        return len(x["Value"].encode("ascii")) + 2
    if t in ["EX_NameConst", "EX_InstanceDelegate"]:
        return 13
    if t == "EX_NoObject":
        return 1
    if t in ["EX_FinalFunction", "EX_LocalFinalFunction", "EX_CallMath"]:
        return 10 + sum(map(kismet_size, x["Parameters"]))
    if t == "EX_Context":
        assert x["Offset"] == kismet_size(x["ContextExpression"])
        return (
            13
            + kismet_size(x["ObjectExpression"])
            + kismet_size(x["ContextExpression"])
        )
    if t == "EX_LetBool":
        return (
            1
            + kismet_size(x["VariableExpression"])
            + kismet_size(x["AssignmentExpression"])
        )
    if t == "EX_JumpIfNot":
        return 5 + kismet_size(x["BooleanExpression"])
    if t == "EX_Return":
        return 1 + kismet_size(x["ReturnExpression"])
    if t in ["EX_Jump", "EX_PushExecutionFlow"]:
        return 5
    if t == "EX_Let":
        return 9 + kismet_size(x["Variable"]) + kismet_size(x["Expression"])
    if t == "EX_LetObj":
        return (
            1
            + kismet_size(x["VariableExpression"])
            + kismet_size(x["AssignmentExpression"])
        )
    if t == "EX_PopExecutionFlowIfNot":
        return 1 + kismet_size(x["BooleanExpression"])
    if t == "EX_StructConst":
        return 14 + sum(map(kismet_size, x["Value"]))
    if t == "EX_StructMemberContext":
        return 9 + kismet_size(x["StructExpression"])
    if t == "EX_ArrayGetByRef":
        return 1 + kismet_size(x["ArrayVariable"]) + kismet_size(x["ArrayIndex"])
    if t in ["EX_AddMulticastDelegate", "EX_RemoveMulticastDelegate"]:
        return 1 + kismet_size(x["Delegate"]) + kismet_size(x["DelegateToAdd"])
    if t == "EX_DynamicCast":
        return 9 + kismet_size(x["Target"])
    if t == "EX_PrimitiveCast":
        return 2 + kismet_size(x["Target"])
    if t == "EX_SwitchValue":
        return (
            7
            + kismet_size(x["IndexTerm"])
            + kismet_size(x["DefaultTerm"])
            + sum(
                kismet_size(c["CaseIndexValueTerm"]) + 4 + kismet_size(c["CaseTerm"])
                for c in x["Cases"]
            )
        )
    raise ValueError(t)

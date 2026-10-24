"""offline checks for catalog startup and closing"""

from asset_io import es
from catalog import FREEZE, OVERRIDE, PENDING, SAVED, STARTED, TRY
from verify_behaviors import VM


def check_catalog_once(document):
    for previous in [0, 1, 2, 3]:
        for visible in [False, True]:
            actor = {
                "ExtendTop": False,
                "ExtendPanel": True,
                "SkeletalMesh": {
                    "bNoSkeletonUpdate": True,
                    "visible": visible,
                    "tick_enabled": False,
                    "VisibilityBasedAnimTickOption": previous,
                },
                "CrackableActorComponent": {"fully_closed": True},
            }
            vm = VM(document, actor)
            vm.run("BPM_StartCatalogClosedPose")
            assert actor[STARTED] and actor[OVERRIDE]
            assert actor[SAVED] == previous
            assert actor["SkeletalMesh"]["VisibilityBasedAnimTickOption"] == 0
            assert not actor["SkeletalMesh"]["bNoSkeletonUpdate"]
            assert actor["ExtendTop"] is True and actor["ExtendPanel"] is False
            assert vm.timers == {FREEZE: {"seconds": 1.0, "loop": False}}
            vm.timers.pop(FREEZE)
            vm.run(FREEZE)
            assert not vm.timers and not actor[PENDING] and not actor[OVERRIDE]
            assert actor["SkeletalMesh"]["VisibilityBasedAnimTickOption"] == previous
            assert actor["SkeletalMesh"]["bNoSkeletonUpdate"]
            assert not actor["SkeletalMesh"]["tick_enabled"]
            # Once settled, the old helper cannot restart work by itself.
            vm.run(TRY)
            assert not vm.timers
            # A long close transition consumes one deferred attempt and then
            # waits for a native event, without scheduling another attempt.
            actor["CrackableActorComponent"]["fully_closed"] = False
            vm.run("BPM_StartCatalogClosedPose")
            assert set(vm.timers) == {TRY} and not vm.timers[TRY]["loop"]
            vm.timers.pop(TRY)
            vm.run(TRY)
            assert not vm.timers and not actor[OVERRIDE]
            actor["CrackableActorComponent"]["fully_closed"] = True
            vm.run("BPM_StartCatalogClosedPose")
            assert actor[OVERRIDE]
            vm.run("BPM_ReleaseCatalogClosedPoseIfOpened", [True])
            assert not vm.timers and not actor[PENDING] and not actor[OVERRIDE]
            assert actor["SkeletalMesh"]["VisibilityBasedAnimTickOption"] == previous
            vm.run(TRY)
            assert not vm.timers
    for mesh, component in [
        (None, {"fully_closed": True}),
        ({"bNoSkeletonUpdate": True}, None),
    ]:
        actor = {"SkeletalMesh": mesh, "CrackableActorComponent": component}
        vm = VM(document, actor)
        vm.run("BPM_StartCatalogClosedPose")
        vm.timers.pop(TRY)
        vm.run(TRY)
        assert not vm.timers
        vm.run(FREEZE)
        assert not vm.timers
    assert "WasRecentlyRendered" not in {
        entry["ObjectName"] for entry in document["Imports"]
    }
    for name, function in es(document).items():
        if name.startswith("BPM_"):
            assert "PlayAnimation" not in str(function.get("ScriptBytecode"))

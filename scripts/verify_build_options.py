"""check model choices and test/release packaging"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

from settings import ROOT


def check_build_options():
    spec = importlib.util.spec_from_file_location(
        "bpm_build_options", ROOT / "build.py"
    )
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    tool = ROOT / "build.py"
    tools = types.SimpleNamespace(GUI=tool, PAK=tool, REPAK=tool, UMODEL=tool)
    settings = sys.modules["settings"]
    cases = [
        (
            True,
            [],
            "1",
            ["prepare_assets.py", "backpack.py", "verify.py", "package.py"],
        ),
        (
            True,
            ["--base"],
            "0",
            ["prepare_assets.py", "backpack.py", "verify.py", "package.py"],
        ),
        (False, [], "0", ["prepare_assets.py", "backpack.py", "verify.py"]),
        (
            False,
            ["--auto-arm-blocker"],
            "1",
            ["prepare_assets.py", "backpack.py", "verify.py"],
        ),
    ]
    cases += [
        (True, ["--model", "luxe"], "1", cases[0][3]),
        (True, ["--model", "luxe", "--base"], "0", cases[0][3]),
    ]
    for development, flags, expected_feature, expected_steps in cases:
        calls = []

        def run(argv, *, check, calls=calls):
            assert check
            calls.append(
                (
                    argv[-1].replace("\\", "/").rsplit("/", 1)[-1],
                    os.environ["BPM_AUTO_ARM_BLOCKER"],
                )
            )

        with (
            patch.object(sys, "argv", [str(tool), "build", *flags]),
            patch.dict(sys.modules, {"game_assets": tools}),
            patch.object(settings, "DEVELOPMENT", development),
            patch.dict(
                os.environ, {"BPM_AUTO_ARM_BLOCKER": "0" if development else "1"}
            ),
            patch.object(build.subprocess, "run", run),
            patch.object(
                settings, "model_paths", return_value=settings.model_paths("base")
            ) as paths,
        ):
            build.main()
            paths.assert_called_once_with("luxe" if "luxe" in flags else "base")
            assert os.environ["BPM_MODEL"] == ("luxe" if "luxe" in flags else "base")
        assert calls == [(step, expected_feature) for step in expected_steps]

    # Missing luxe files must stop the build, not quietly use the base model.
    with (
        tempfile.TemporaryDirectory() as folder,
        patch.object(settings, "ROOT", Path(folder)),
        patch.object(sys, "argv", [str(tool), "build", "--model", "luxe"]),
        patch.object(build.subprocess, "run") as run,
        contextlib.redirect_stderr(io.StringIO()) as error,
    ):
        models = Path(folder) / "models"
        models.mkdir()
        for path in settings.model_paths("base"):
            path.write_bytes(b"base fixture, not a luxe model")
        try:
            build.main()
        except SystemExit as stopped:
            assert stopped.code == 2
        else:
            raise AssertionError("missing luxe files didn't stop the build")
        run.assert_not_called()
        assert "luxe model isn't ready" in error.getvalue()

    # Luxe decorations must not move the functional parts of the backpack.
    import model

    base = json.loads(settings.model_paths("base")[1].read_text())
    with tempfile.TemporaryDirectory() as folder:
        approval = Path(folder) / "luxe.json"
        for key in ["socket_centre_native_x", "battery_back_shift"]:
            changed = dict(base)
            changed[key] += 1
            approval.write_text(json.dumps(changed))
            with (
                patch.object(model, "INFO", approval),
                patch.object(model, "MODEL_STYLE", "luxe"),
            ):
                try:
                    model.load_model()
                except AssertionError as rejected:
                    assert "luxe must keep the base layout" in str(rejected)
                else:
                    raise AssertionError("luxe was allowed to move " + key)

    # Import settings in fresh processes, as the build's child scripts do.
    code = (
        "import json,sys;sys.path.insert(0,sys.argv[1]);"
        "from settings import OUT,PAK_NAME,ARCHIVE_NAME,MODEL_STYLE;"
        "print(json.dumps([str(OUT),PAK_NAME,ARCHIVE_NAME,MODEL_STYLE]))"
    )
    for style in ["base", "luxe"]:
        for blocker in [False, True]:
            env = dict(
                os.environ, BPM_MODEL=style, BPM_AUTO_ARM_BLOCKER=str(int(blocker))
            )
            out, pak, archive, selected = json.loads(
                subprocess.check_output(
                    [sys.executable, "-c", code, str(ROOT / "scripts")],
                    env=env,
                    text=True,
                )
            )
            assert selected == style
            suffix = ("-Luxe" if style == "luxe" else "") + (
                "-AutoArm" if blocker else ""
            )
            assert pak == f"000-BackpackProMax-{settings.VERSION}_P.pak"
            assert archive == f"Backpack-Pro-Max{suffix}-{settings.VERSION}-Vortex.zip"
            assert ("luxe" in Path(out).parts) == (style == "luxe")
            assert (Path(out).name == "auto-arm") == blocker
    return [
        "test builds make one ZIP; model and auto-arm choices stay separate; missing luxe files stop the build"
    ]

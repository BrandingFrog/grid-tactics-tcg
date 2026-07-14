"""Repository-structure contracts for operational entrypoints and docs."""

from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_contains_only_the_deployed_python_entrypoint() -> None:
    assert sorted(path.name for path in ROOT.glob("*.py")) == ["pvp_server.py"]
    assert list(ROOT.glob("*.bat")) == []


def test_operator_tools_and_windows_launchers_are_grouped() -> None:
    expected_scripts = {
        "check_stats.py",
        "cloud_train.py",
        "dashboard.py",
        "manage_pods.py",
        "stats.py",
        "tensor_train.py",
        "watch_game.py",
    }
    expected_launchers = {
        "dashboard.bat",
        "play.bat",
        "stats.bat",
        "tensorboard.bat",
        "train.bat",
        "train_long.bat",
    }

    assert expected_scripts <= {path.name for path in (ROOT / "scripts").glob("*.py")}
    assert expected_launchers == {
        path.name for path in (ROOT / "scripts" / "windows").glob("*.bat")
    }


def test_maintained_docs_have_one_canonical_location() -> None:
    expected = {
        ROOT / "docs" / "README.md",
        ROOT / "docs" / "deployment.md",
        ROOT / "docs" / "design" / "README.md",
        ROOT / "docs" / "design" / "ideas.md",
        ROOT / "docs" / "rules" / "README.md",
        ROOT / "docs" / "rules" / "turn-structure.md",
    }
    obsolete = {
        ROOT / "README_DEPLOY.md",
        ROOT / "data" / "ideas.md",
        ROOT / "data" / "turn_structure_spec.md",
    }

    assert all(path.is_file() for path in expected)
    assert not any(path.exists() for path in obsolete)


def test_railway_still_uses_the_root_server_shim() -> None:
    assert (ROOT / "Procfile").read_text(encoding="utf-8").strip() == (
        "web: python pvp_server.py"
    )
    railway = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    assert railway["deploy"]["startCommand"] == "python pvp_server.py"


def test_runpod_archive_contains_moved_training_entrypoints() -> None:
    module_path = ROOT / "scripts" / "manage_pods.py"
    spec = importlib.util.spec_from_file_location("grid_tactics_manage_pods", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with tarfile.open(fileobj=io.BytesIO(module.create_code_archive()), mode="r:gz") as archive:
        names = {member.name.replace("\\", "/").rstrip("/") for member in archive}

    assert "scripts/cloud_train.py" in names
    assert "scripts/check_stats.py" in names
    assert any(name.startswith("src/grid_tactics/") for name in names)
    assert any(name.startswith("data/cards/") for name in names)


def test_runpod_commands_execute_the_moved_cloud_entrypoint() -> None:
    source = (ROOT / "scripts" / "manage_pods.py").read_text(encoding="utf-8")
    command = "PYTHONPATH=/workspace/src python scripts/cloud_train.py"

    assert source.count(command) == 2
    assert "python cloud_train.py" not in source


def test_windows_launchers_resolve_paths_from_the_repository_root() -> None:
    launcher_targets = {
        "dashboard.bat": r"%ROOT%\scripts\dashboard.py",
        "play.bat": r"%ROOT%\scripts\watch_game.py",
        "stats.bat": r"%ROOT%\scripts\stats.py",
        "tensorboard.bat": r"%ROOT%\data\tb_logs",
        "train.bat": r"%ROOT%\.venv\Scripts\python.exe",
        "train_long.bat": r"%ROOT%\.venv\Scripts\python.exe",
    }

    for filename, target in launcher_targets.items():
        source = (ROOT / "scripts" / "windows" / filename).read_text(encoding="utf-8")
        assert r'set "ROOT=%~dp0..\.."' in source
        assert r'cd /d "%ROOT%"' in source
        assert target in source

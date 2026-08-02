from __future__ import annotations

import os
from pathlib import Path

from nex_runtime.env import load_env_file, merge_pythonpath


def test_load_env_file_ignores_missing_file(tmp_path: Path) -> None:
    load_env_file(tmp_path / "missing.env")


def test_load_env_file_sets_values_without_overwriting_existing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "NEX_EMPTY_IGNORED",
                "NEX_ALPHA='alpha value'",
                'NEX_BRAVO="bravo value"',
                "NEX_EMPTY=",
                "NEX_EXISTING=from-file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEX_EXISTING", "from-env")

    load_env_file(env_file)

    assert os.environ["NEX_ALPHA"] == "alpha value"
    assert os.environ["NEX_BRAVO"] == "bravo value"
    assert os.environ["NEX_EMPTY"] == ""
    assert os.environ["NEX_EXISTING"] == "from-env"


def test_merge_pythonpath_appends_existing(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv("PYTHONPATH", "already-there")

    merged = merge_pythonpath(first, second)

    assert merged.endswith("already-there")
    assert str(first) in merged
    assert str(second) in merged


def test_merge_pythonpath_without_existing(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.delenv("PYTHONPATH", raising=False)

    merged = merge_pythonpath(first, second)

    assert merged == os.pathsep.join([str(first), str(second)])

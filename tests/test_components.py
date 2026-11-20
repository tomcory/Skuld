"""How Skuld runs the other components: their own venv's executable, or the command config.json gives."""

import json

import pytest

from skuld import config, execute
from skuld.cli import component


@pytest.fixture
def configured(monkeypatch, tmp_path):
    def use(data: dict):
        f = tmp_path / "config.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv("SKULD_CONFIG", str(f))
        config.load.cache_clear()

    yield use
    monkeypatch.delenv("SKULD_CONFIG", raising=False)
    config.load.cache_clear()


def test_a_component_runs_from_its_own_venv_not_through_uv(configured, tmp_path):
    configured({})
    loki = tmp_path / "Loki"
    (loki / ".venv" / "bin").mkdir(parents=True)
    (loki / ".venv" / "bin" / "loki").write_text("#!/bin/sh\n")
    assert component("loki", loki) == [str(loki / ".venv" / "bin" / "loki")]
    workspace = tmp_path / "pilots" / "p" / "ws"
    workspace.mkdir(parents=True)
    assert component("loki", loki, relative_to=workspace) == ["../../../Loki/.venv/bin/loki"]


def test_a_component_not_installed_is_refused_with_how_to_install_it(configured, tmp_path):
    configured({})
    with pytest.raises(execute.ExecutionError, match="verdandi is not installed at .*uv sync --all-extras"):
        component("verdandi", tmp_path / "Verdandi")


def test_config_json_may_give_the_command(configured, tmp_path):
    configured({"components": {"loki": ["/opt/loki/bin/loki", "--quiet"]}})
    assert component("loki", tmp_path / "nowhere") == ["/opt/loki/bin/loki", "--quiet"]

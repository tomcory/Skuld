"""The layered catalogue (21 Nov 2026): Skuld's committed catalogue is the base, read only; the families models propose
go into a study's catalogue beside the workspaces, and select reads both."""

import copy

import pytest

from skuld import catalogue, propose, select
from tests.test_propose import FORECAST


def test_new_families_go_into_the_study_catalogue_and_the_base_stays(tmp_path):
    base, study = tmp_path / "base", tmp_path / "study"
    first = catalogue.load(base).add(FORECAST)
    before = sorted(p.name for p in (base / "families").iterdir())

    layered = propose.load_catalogue((base, study))
    assert layered.get(FORECAST["id"]).key == first.key  # the base's families are read
    other = {**copy.deepcopy(FORECAST), "id": "another-forecast"}
    added = layered.add(other)
    assert added.path.parent == study / "families"
    assert sorted(p.name for p in (base / "families").iterdir()) == before
    # a new version of a base family is written into the study's catalogue too, numbered after the base's
    assert layered.add(copy.deepcopy(FORECAST)).key == f"{FORECAST['id']}@2"
    assert (study / "families" / f"{FORECAST['id']}@2.yaml").is_file()

    again = propose.load_catalogue((base, study))
    assert {f.key for f in again.families} == {first.key, added.key, f"{FORECAST['id']}@2"}
    assert propose.load_catalogue(base).get("another-forecast") is None


def test_a_family_in_both_layers_is_refused(tmp_path):
    base, study = tmp_path / "base", tmp_path / "study"
    catalogue.load(base).add(FORECAST)
    catalogue.load(study).add(FORECAST)
    with pytest.raises(catalogue.CatalogueError, match="also in the base catalogue"):
        catalogue.load(study, base=base)


def test_select_observes_the_purposes_of_the_study_catalogue(tmp_path):
    base, study = tmp_path / "base", tmp_path / "study"
    catalogue.load(base)
    assert select.observed_purposes(base) == []
    catalogue.load(study).add(FORECAST)
    found = select.observed_purposes(base, study=study)
    assert found and all(node for node, _ in found)
    assert select.observed_purposes(base, study=tmp_path / "absent") == []

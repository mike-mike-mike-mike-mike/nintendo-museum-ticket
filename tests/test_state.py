import json

import pytest

from src.state import (
    MalformedStateError,
    available,
    load,
    save_available,
    target_months,
)


def write(tmp_path, document):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(document))
    return path


def test_reads_config_and_state(tmp_path):
    path = write(tmp_path, {
        "config": {"target_months": ["2026-12"]},
        "state": {"available": ["2026-12-15"]},
    })
    document = load(path)
    assert target_months(document) == ["2026-12"]
    assert available(document) == {"2026-12-15"}


def test_missing_state_section_reads_as_empty(tmp_path):
    path = write(tmp_path, {"config": {"target_months": ["2026-12"]}})
    assert available(load(path)) == set()


def test_save_preserves_unrelated_config_keys(tmp_path):
    path = write(tmp_path, {
        "config": {"target_months": ["2026-12"], "note": "keep me"},
        "state": {"available": []},
    })
    document = load(path)
    save_available(document, {"2026-12-16", "2026-12-15"}, path)

    written = json.loads(path.read_text())
    assert written["config"] == {"target_months": ["2026-12"], "note": "keep me"}
    assert written["state"]["available"] == ["2026-12-15", "2026-12-16"]


def test_save_never_writes_a_timestamp(tmp_path):
    path = write(tmp_path, {
        "config": {"target_months": ["2026-12"]},
        "state": {"available": []},
    })
    save_available(load(path), set(), path)
    written = json.loads(path.read_text())
    assert set(written["state"].keys()) == {"available"}


def test_repeated_save_of_same_set_is_byte_identical(tmp_path):
    """Guards the 'only commit when it really changed' property."""
    path = write(tmp_path, {
        "config": {"target_months": ["2026-12"]},
        "state": {"available": []},
    })
    save_available(load(path), {"2026-12-15"}, path)
    first = path.read_bytes()
    save_available(load(path), {"2026-12-15"}, path)
    assert path.read_bytes() == first


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    with pytest.raises(MalformedStateError):
        load(path)


def test_missing_target_months_raises(tmp_path):
    path = write(tmp_path, {"config": {}, "state": {"available": []}})
    with pytest.raises(MalformedStateError):
        target_months(load(path))


def test_missing_file_raises(tmp_path):
    path = tmp_path / "state.json"
    with pytest.raises(MalformedStateError):
        load(path)


def test_non_object_top_level_raises(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(["2026-12"]))
    with pytest.raises(MalformedStateError):
        load(path)

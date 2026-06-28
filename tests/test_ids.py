from datetime import timezone

import pytest

from studybuddy import ids


def test_slugify_basic():
    assert ids.slugify("Time Value of Money") == "time-value-of-money"
    assert ids.slugify("  Net Present Value!! ") == "net-present-value"
    assert ids.slugify("CAPM & WACC") == "capm-wacc"
    assert ids.slugify("already-a-slug") == "already-a-slug"


def test_slug_id():
    assert ids.slug_id("concept", "Time Value of Money") == "concept_time-value-of-money"


def test_slug_id_rejects_empty():
    with pytest.raises(ValueError):
        ids.slug_id("concept", "   !!!   ")


def test_ulid_id_prefixed_and_unique():
    a = ids.ulid_id("item")
    b = ids.ulid_id("item")
    assert a.startswith("item_")
    assert a != b


def test_ulids_are_time_sortable():
    # ULIDs created later sort lexicographically after earlier ones.
    seq = [ids.new_ulid() for _ in range(50)]
    assert seq == sorted(seq)


def test_utcnow_is_timezone_aware():
    now = ids.utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(None)

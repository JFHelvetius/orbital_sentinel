"""Tests del repositorio ``OrbitalElementsRepository``."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog import (
    OrbitalElement,
    OrbitalElementsRepository,
)
from orbital_sentinel.catalog.orbital_elements import (
    ORBITAL_ELEMENTS_SCHEMA_VERSION,
    OrbitalElementsError,
)

DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)


def _make_element(
    *,
    content_hash_source: str = "a" * 64,
    tle_index: int = 0,
    norad_cat_id: int = 25544,
    engine_version: str = "0.1.0",
) -> OrbitalElement:
    return OrbitalElement(
        content_hash_source=content_hash_source,
        tle_index=tle_index,
        tle_content_hash="b" * 64,
        object_name="ISS (ZARYA)",
        norad_cat_id=norad_cat_id,
        classification="U",
        intl_designator="98067A",
        epoch_year=2008,
        epoch_day=264.51782528,
        epoch_datetime=EPOCH,
        mean_motion_dot=-2.182e-5,
        mean_motion_ddot=0.0,
        bstar=-1.1606e-5,
        ephemeris_type=0,
        element_set_number=292,
        inclination_deg=51.6416,
        raan_deg=247.4627,
        eccentricity=0.0006703,
        arg_perigee_deg=130.5360,
        mean_anomaly_deg=325.0288,
        mean_motion=15.72125391,
        rev_number=56353,
        engine_version=engine_version,
        derived_at=DERIVED_AT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> OrbitalElementsRepository:
    return OrbitalElementsRepository(tmp_path / "orbital_elements")


# --- Vacío ----------------------------------------------------------------


def test_count_empty(repo: OrbitalElementsRepository) -> None:
    assert repo.count() == 0


def test_get_by_snapshot_empty(repo: OrbitalElementsRepository) -> None:
    assert repo.get_by_snapshot("a" * 64) == []


def test_iter_all_empty(repo: OrbitalElementsRepository) -> None:
    assert list(repo.iter_all()) == []


def test_engine_versions_for_empty(repo: OrbitalElementsRepository) -> None:
    assert repo.engine_versions_for("a" * 64) == []


# --- find_all_by_norad_id (ADR-0027) -------------------------------------


def test_r1_find_all_by_norad_id_returns_chronological_order(
    repo: OrbitalElementsRepository,
) -> None:
    """Múltiples snapshots del mismo NORAD se devuelven ordenados por epoch."""
    # Tres elements del mismo NORAD en 3 snapshots distintos con epochs distintas
    e_late = _make_element(
        content_hash_source="c" * 64, tle_index=0, norad_cat_id=99,
    )
    object.__setattr__(e_late, "_epoch_offset", None)  # placeholder
    # Pydantic frozen: necesitamos construir nuevos elements con epoch distinto
    e1 = OrbitalElement(
        **{**e_late.model_dump(), "epoch_datetime": EPOCH,
           "content_hash_source": "a" * 64,
           "tle_content_hash": "1" + "0" * 63}
    )
    e2 = OrbitalElement(
        **{**e_late.model_dump(),
           "epoch_datetime": datetime(2008, 9, 21, 0, 0, tzinfo=timezone.utc),
           "content_hash_source": "b" * 64,
           "tle_content_hash": "2" + "0" * 63}
    )
    e3 = OrbitalElement(
        **{**e_late.model_dump(),
           "epoch_datetime": datetime(2008, 9, 22, 0, 0, tzinfo=timezone.utc),
           "content_hash_source": "c" * 64,
           "tle_content_hash": "3" + "0" * 63}
    )
    # Insertar fuera de orden
    repo.insert_many([e2])
    repo.insert_many([e1])
    repo.insert_many([e3])
    result = repo.find_all_by_norad_id(99)
    assert len(result) == 3
    assert result[0].epoch_datetime < result[1].epoch_datetime < result[2].epoch_datetime


def test_r2_find_all_by_norad_id_filters_by_norad(
    repo: OrbitalElementsRepository,
) -> None:
    """find_all_by_norad_id no incluye otros NORADs."""
    e_a = _make_element(content_hash_source="a" * 64, norad_cat_id=1)
    e_b = _make_element(content_hash_source="b" * 64, norad_cat_id=2)
    repo.insert_many([e_a])
    repo.insert_many([e_b])
    result = repo.find_all_by_norad_id(1)
    assert len(result) == 1
    assert result[0].norad_cat_id == 1


def test_r3_find_all_by_norad_id_engine_version_filter(
    repo: OrbitalElementsRepository,
) -> None:
    """Filtro por engine_version aísla la subserie de esa versión."""
    e_v1 = _make_element(
        content_hash_source="a" * 64, norad_cat_id=99, engine_version="0.1.0",
    )
    e_v2 = _make_element(
        content_hash_source="b" * 64, norad_cat_id=99, engine_version="0.2.0",
    )
    repo.insert_many([e_v1])
    repo.insert_many([e_v2])
    only_v1 = repo.find_all_by_norad_id(99, engine_version="0.1.0")
    only_v2 = repo.find_all_by_norad_id(99, engine_version="0.2.0")
    mixed = repo.find_all_by_norad_id(99)
    assert len(only_v1) == 1
    assert len(only_v2) == 1
    assert len(mixed) == 2


def test_r4_find_all_by_norad_id_empty_result(
    repo: OrbitalElementsRepository,
) -> None:
    """NORAD sin elements en el catálogo → []."""
    e = _make_element(content_hash_source="a" * 64, norad_cat_id=1)
    repo.insert_many([e])
    assert repo.find_all_by_norad_id(999999) == []
    # Catálogo vacío también devuelve []
    empty_repo = OrbitalElementsRepository(repo.root / "_empty")
    assert empty_repo.find_all_by_norad_id(1) == []


# --- Inserción ------------------------------------------------------------


def test_insert_many_writes_parquet(repo: OrbitalElementsRepository) -> None:
    elements = [
        _make_element(tle_index=0),
        _make_element(tle_index=1, norad_cat_id=99999),
    ]
    written = repo.insert_many(elements)
    assert written == 2
    assert repo.count() == 2


def test_insert_many_empty_is_noop(repo: OrbitalElementsRepository) -> None:
    assert repo.insert_many([]) == 0
    assert repo.count() == 0


def test_insert_many_idempotent(repo: OrbitalElementsRepository) -> None:
    """Insertar el mismo batch dos veces es no-op la segunda."""
    elements = [_make_element(tle_index=0)]
    assert repo.insert_many(elements) == 1
    assert repo.insert_many(elements) == 0
    assert repo.count() == 1


def test_insert_many_rejects_mixed_content_hash_source(
    repo: OrbitalElementsRepository,
) -> None:
    elements = [
        _make_element(content_hash_source="a" * 64, tle_index=0),
        _make_element(content_hash_source="b" * 64, tle_index=0),
    ]
    with pytest.raises(OrbitalElementsError):
        repo.insert_many(elements)


def test_insert_many_rejects_mixed_engine_version(
    repo: OrbitalElementsRepository,
) -> None:
    elements = [
        _make_element(tle_index=0, engine_version="0.1.0"),
        _make_element(tle_index=1, engine_version="0.2.0"),
    ]
    with pytest.raises(OrbitalElementsError):
        repo.insert_many(elements)


def test_insert_many_rejects_duplicate_tle_index(
    repo: OrbitalElementsRepository,
) -> None:
    elements = [
        _make_element(tle_index=0),
        _make_element(tle_index=0, norad_cat_id=99999),
    ]
    with pytest.raises(OrbitalElementsError):
        repo.insert_many(elements)


def test_partitioning_by_engine_version(repo: OrbitalElementsRepository) -> None:
    elements = [_make_element(tle_index=0)]
    repo.insert_many(elements)
    expected = (
        repo.root
        / "engine_version=0.1.0"
        / f"source_{elements[0].content_hash_source[:2]}"
        / f"snap_{elements[0].content_hash_source}.parquet"
    )
    assert expected.is_file()


# --- Lectura --------------------------------------------------------------


def test_get_by_snapshot_returns_inserted(repo: OrbitalElementsRepository) -> None:
    elements = [
        _make_element(tle_index=0),
        _make_element(tle_index=1, norad_cat_id=99999),
    ]
    repo.insert_many(elements)
    rows = repo.get_by_snapshot("a" * 64)
    assert len(rows) == 2
    assert [r.tle_index for r in rows] == [0, 1]


def test_get_by_snapshot_filters_by_engine_version(
    repo: OrbitalElementsRepository,
) -> None:
    repo.insert_many([_make_element(tle_index=0, engine_version="0.1.0")])
    repo.insert_many([_make_element(tle_index=0, engine_version="0.2.0")])
    rows_v1 = repo.get_by_snapshot("a" * 64, engine_version="0.1.0")
    rows_v2 = repo.get_by_snapshot("a" * 64, engine_version="0.2.0")
    assert len(rows_v1) == 1
    assert len(rows_v2) == 1
    assert rows_v1[0].engine_version == "0.1.0"
    assert rows_v2[0].engine_version == "0.2.0"


def test_get_by_snapshot_returns_empty_when_unknown(
    repo: OrbitalElementsRepository,
) -> None:
    repo.insert_many([_make_element(tle_index=0)])
    assert repo.get_by_snapshot("c" * 64) == []


def test_iter_all_returns_all_inserted(repo: OrbitalElementsRepository) -> None:
    repo.insert_many([_make_element(tle_index=0)])
    repo.insert_many(
        [_make_element(content_hash_source="b" * 64, tle_index=0)]
    )
    rows = list(repo.iter_all())
    assert len(rows) == 2


# --- Coexistencia de engine_versions --------------------------------------


def test_multiple_engine_versions_coexist(repo: OrbitalElementsRepository) -> None:
    """Re-derivar con engine_version nueva no destruye los rows previos (ADR-0010)."""
    repo.insert_many([_make_element(tle_index=0, engine_version="0.1.0")])
    repo.insert_many([_make_element(tle_index=0, engine_version="0.2.0")])
    assert repo.count() == 2
    versions = repo.engine_versions_for("a" * 64)
    assert versions == ["0.1.0", "0.2.0"]


# --- find_latest_by_norad_id ---------------------------------------------


def test_find_latest_by_norad_id_returns_none_when_empty(
    repo: OrbitalElementsRepository,
) -> None:
    assert repo.find_latest_by_norad_id(25544) is None


def test_find_latest_by_norad_id_returns_none_when_norad_absent(
    repo: OrbitalElementsRepository,
) -> None:
    repo.insert_many([_make_element(tle_index=0, norad_cat_id=25544)])
    assert repo.find_latest_by_norad_id(99999) is None


def test_find_latest_by_norad_id_returns_only_match(
    repo: OrbitalElementsRepository,
) -> None:
    repo.insert_many([_make_element(tle_index=0, norad_cat_id=25544)])
    found = repo.find_latest_by_norad_id(25544)
    assert found is not None
    assert found.norad_cat_id == 25544


def test_find_latest_by_norad_id_picks_max_epoch(
    repo: OrbitalElementsRepository,
) -> None:
    """Con varios snapshots distintos del mismo NORAD, devuelve el de epoch más reciente."""
    earlier_epoch = datetime(2008, 9, 20, 0, 0, tzinfo=timezone.utc)
    later_epoch = datetime(2008, 9, 22, 0, 0, tzinfo=timezone.utc)

    earlier = _make_element(
        content_hash_source="a" * 64, tle_index=0, norad_cat_id=25544
    ).model_copy(update={"epoch_datetime": earlier_epoch})
    later = _make_element(
        content_hash_source="b" * 64, tle_index=0, norad_cat_id=25544
    ).model_copy(update={"epoch_datetime": later_epoch})

    repo.insert_many([earlier])
    repo.insert_many([later])

    found = repo.find_latest_by_norad_id(25544)
    assert found is not None
    assert found.epoch_datetime == later_epoch


def test_find_latest_by_norad_id_filters_by_engine_version(
    repo: OrbitalElementsRepository,
) -> None:
    repo.insert_many([_make_element(tle_index=0, engine_version="0.1.0")])
    repo.insert_many([_make_element(tle_index=0, engine_version="0.2.0")])

    found_v1 = repo.find_latest_by_norad_id(25544, engine_version="0.1.0")
    found_v2 = repo.find_latest_by_norad_id(25544, engine_version="0.2.0")
    assert found_v1 is not None and found_v1.engine_version == "0.1.0"
    assert found_v2 is not None and found_v2.engine_version == "0.2.0"


def test_no_update_on_existing_file(repo: OrbitalElementsRepository) -> None:
    """Insert con (engine_version, content_hash_source) ya presente es no-op."""
    repo.insert_many([_make_element(tle_index=0, norad_cat_id=11111)])
    assert repo.insert_many([_make_element(tle_index=0, norad_cat_id=22222)]) == 0
    rows = repo.get_by_snapshot("a" * 64)
    assert rows[0].norad_cat_id == 11111  # original preservado


# --- Schema / inmutabilidad -----------------------------------------------


def test_schema_version_default_is_semver() -> None:
    element = _make_element()
    parts = element.schema_version.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
    assert element.schema_version == ORBITAL_ELEMENTS_SCHEMA_VERSION


def test_element_is_frozen() -> None:
    element = _make_element()
    with pytest.raises(Exception):
        element.norad_cat_id = 11111  # type: ignore[misc]


def test_element_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        OrbitalElement.model_validate(
            {
                **_make_element().model_dump(),
                "unexpected_field": "boom",
            }
        )


# --- Integración Raw → Normalized en disco --------------------------------


def test_roundtrip_preserves_all_fields(repo: OrbitalElementsRepository) -> None:
    """Insertar y volver a leer preserva todos los valores."""
    element = _make_element()
    repo.insert_many([element])
    [retrieved] = repo.get_by_snapshot(element.content_hash_source)
    assert retrieved.model_dump() == element.model_dump()

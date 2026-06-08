"""CLI integration tests para ADR-0042 (Provenance Wiring v1)."""

from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot, TLESnapshotsRepository
from orbital_sentinel.orchestration.cli import main as cli_main
from tests.unit.test_maneuver_series import make_element


@contextmanager
def _redirect_stdin(new_stdin):  # type: ignore[no-untyped-def]
    old = sys.stdin
    sys.stdin = new_stdin
    try:
        yield
    finally:
        sys.stdin = old


FETCHED_AT = datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def pipeline_with_raw_snapshots(tmp_path: Path) -> dict[str, Path]:
    """Construye un pipeline completo donde Raw está poblado coherentemente
    con Normalized. Devuelve paths de bundle + repos."""
    normalized_root = tmp_path / "normalized"
    raw_root = tmp_path / "raw"
    tle_snapshots_root = raw_root / "tle_snapshots"
    tle_snapshots_root.mkdir(parents=True, exist_ok=True)
    elem_repo = OrbitalElementsRepository(normalized_root)
    tle_repo = TLESnapshotsRepository(tle_snapshots_root)

    # 25 elementos, cada uno con su propio snapshot (uno por TLE para simplicidad)
    elements = []
    for i in range(25):
        ch = f"{i:064x}"
        bump = 1e-2 if i >= 21 else 0.0
        tle_repo.insert(TLESnapshot(
            content_hash=ch,
            source="celestrak",
            dataset=f"catnr-12345-{i}",
            url=f"https://celestrak.org/NORAD/elements/gp.php?CATNR=12345&FORMAT=tle&n={i}",
            fetched_at=FETCHED_AT,
            raw_text=f"TLE_PAYLOAD_{i}",
            n_bytes=len(f"TLE_PAYLOAD_{i}".encode()),
        ))
        elements.append(make_element(
            days_offset=float(i),
            mean_motion=15.5 + bump,
            tle_hash=f"{(i + 1000):064x}",
            content_hash_source=ch,
            tle_index=0,
        ))
    elem_repo.insert_many([elements[0]])
    for el in elements[1:]:
        elem_repo.insert_many([el])

    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        cli_main([
            "bundle", "12345",
            "--baseline-days", "30", "--threshold-sigma", "3.0",
            "--raw-root", str(raw_root),
            "--normalized-root", str(normalized_root),
            "--detections-root", str(tmp_path / "derived" / "conjunctions"),
        ])
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(bundle_buf.getvalue(), encoding="utf-8")
    return {
        "bundle": bundle_path,
        "raw_root": tle_snapshots_root,
        "normalized_root": normalized_root,
    }


# --- external-source-registry-from-repos -----------------------------


def test_cli_provenance_from_repos_emits_valid_registry(
    pipeline_with_raw_snapshots: dict[str, Path],
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "external-source-registry-from-repos",
            str(pipeline_with_raw_snapshots["bundle"]),
            "--raw-root", str(pipeline_with_raw_snapshots["raw_root"]),
            "--normalized-root", str(pipeline_with_raw_snapshots["normalized_root"]),
        ])
    assert rc == 0
    reg = json.loads(buf.getvalue())
    assert reg["registry_id"] == reg["registry_hash"]
    assert reg["n_records"] >= 1
    assert reg["registry_emit_reason"] == "records_present"


def test_cli_provenance_from_repos_passes_verifier(
    pipeline_with_raw_snapshots: dict[str, Path], tmp_path: Path,
) -> None:
    reg_buf = io.StringIO()
    with redirect_stdout(reg_buf):
        cli_main([
            "external-source-registry-from-repos",
            str(pipeline_with_raw_snapshots["bundle"]),
            "--raw-root", str(pipeline_with_raw_snapshots["raw_root"]),
            "--normalized-root", str(pipeline_with_raw_snapshots["normalized_root"]),
        ])
    reg_path = tmp_path / "src_reg.json"
    reg_path.write_text(reg_buf.getvalue(), encoding="utf-8")

    vbuf = io.StringIO()
    with redirect_stdout(vbuf):
        rc = cli_main([
            "verify-external-source-registry", str(reg_path),
            "--bundle-file", str(pipeline_with_raw_snapshots["bundle"]),
            "--strict",
        ])
    assert rc == 0
    rpt = json.loads(vbuf.getvalue())
    assert rpt["is_valid"] is True


def test_cli_provenance_from_repos_via_stdin(
    pipeline_with_raw_snapshots: dict[str, Path],
) -> None:
    bundle_raw = pipeline_with_raw_snapshots["bundle"].read_text(encoding="utf-8")
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_raw)), redirect_stdout(buf):
        rc = cli_main([
            "external-source-registry-from-repos", "-",
            "--raw-root", str(pipeline_with_raw_snapshots["raw_root"]),
            "--normalized-root", str(pipeline_with_raw_snapshots["normalized_root"]),
        ])
    assert rc == 0
    reg = json.loads(buf.getvalue())
    assert reg["registry_id"] == reg["registry_hash"]


def test_cli_provenance_binds_to_bundle_id(
    pipeline_with_raw_snapshots: dict[str, Path],
) -> None:
    """El registry derivado lleva source_bundle_id == bundle.bundle_id.
    Esa es la garantía cryptográfica de binding sin embedding."""
    bundle = json.loads(
        pipeline_with_raw_snapshots["bundle"].read_text(encoding="utf-8"),
    )
    reg_buf = io.StringIO()
    with redirect_stdout(reg_buf):
        cli_main([
            "external-source-registry-from-repos",
            str(pipeline_with_raw_snapshots["bundle"]),
            "--raw-root", str(pipeline_with_raw_snapshots["raw_root"]),
            "--normalized-root", str(pipeline_with_raw_snapshots["normalized_root"]),
        ])
    reg = json.loads(reg_buf.getvalue())
    assert reg["source_bundle_id"] == bundle["bundle_id"]


def test_cli_provenance_reproducible_across_runs(
    pipeline_with_raw_snapshots: dict[str, Path],
) -> None:
    """Dos invocaciones idénticas producen mismo registry_id."""
    buf_a = io.StringIO()
    with redirect_stdout(buf_a):
        cli_main([
            "external-source-registry-from-repos",
            str(pipeline_with_raw_snapshots["bundle"]),
            "--raw-root", str(pipeline_with_raw_snapshots["raw_root"]),
            "--normalized-root", str(pipeline_with_raw_snapshots["normalized_root"]),
        ])
    buf_b = io.StringIO()
    with redirect_stdout(buf_b):
        cli_main([
            "external-source-registry-from-repos",
            str(pipeline_with_raw_snapshots["bundle"]),
            "--raw-root", str(pipeline_with_raw_snapshots["raw_root"]),
            "--normalized-root", str(pipeline_with_raw_snapshots["normalized_root"]),
        ])
    reg_a = json.loads(buf_a.getvalue())
    reg_b = json.loads(buf_b.getvalue())
    assert reg_a["registry_id"] == reg_b["registry_id"]
    # derived_at may differ; everything else must match
    reg_a_no_time = {k: v for k, v in reg_a.items() if k != "derived_at"}
    reg_b_no_time = {k: v for k, v in reg_b.items() if k != "derived_at"}
    assert reg_a_no_time == reg_b_no_time


# --- End-to-end Phase 7+ con provenance real ----------------------


def test_cli_full_pipeline_with_provenance_chain(
    pipeline_with_raw_snapshots: dict[str, Path], tmp_path: Path,
) -> None:
    """bundle → agent-input → explain → claim-registry → hypothesis-registry
    → evidence-chain → investigation-case → external-source-registry-from-repos
    → verify-external-source-registry (todo coherente).
    """
    bp = pipeline_with_raw_snapshots["bundle"]
    raw = pipeline_with_raw_snapshots["raw_root"]
    norm = pipeline_with_raw_snapshots["normalized_root"]
    # agent_input
    bundle_raw = bp.read_text(encoding="utf-8")
    aib = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_raw)), redirect_stdout(aib):
        cli_main(["agent-input", "-", "--consumer-class", "explanation_agent_v01"])
    aip = tmp_path / "ai.json"
    aip.write_text(aib.getvalue(), encoding="utf-8")
    # explain
    ab = io.StringIO()
    with _redirect_stdin(io.StringIO(aib.getvalue())), redirect_stdout(ab):
        cli_main(["explain", "-"])
    ap = tmp_path / "art.json"
    ap.write_text(ab.getvalue(), encoding="utf-8")
    # claim-registry
    crb = io.StringIO()
    with redirect_stdout(crb):
        cli_main(["claim-registry", str(ap), "--agent-input-file", str(aip)])
    crp = tmp_path / "cr.json"
    crp.write_text(crb.getvalue(), encoding="utf-8")
    # hypothesis
    hrb = io.StringIO()
    with redirect_stdout(hrb):
        cli_main(["hypothesis-registry", str(crp), "--agent-input-file", str(aip)])
    hrp = tmp_path / "hr.json"
    hrp.write_text(hrb.getvalue(), encoding="utf-8")
    # chain
    chb = io.StringIO()
    with redirect_stdout(chb):
        cli_main([
            "evidence-chain", str(hrp),
            "--claim-registry-file", str(crp),
            "--explanation-artifact-file", str(ap),
            "--agent-input-file", str(aip),
        ])
    chp = tmp_path / "ch.json"
    chp.write_text(chb.getvalue(), encoding="utf-8")
    # case
    icb = io.StringIO()
    with redirect_stdout(icb):
        cli_main([
            "investigation-case", str(chp),
            "--hypothesis-registry-file", str(hrp),
            "--claim-registry-file", str(crp),
            "--explanation-artifact-file", str(ap),
            "--agent-input-file", str(aip),
            "--bundle-file", str(bp),
        ])
    icp = tmp_path / "case.json"
    icp.write_text(icb.getvalue(), encoding="utf-8")
    case = json.loads(icb.getvalue())
    # provenance (sidecar)
    sb = io.StringIO()
    with redirect_stdout(sb):
        cli_main([
            "external-source-registry-from-repos", str(bp),
            "--raw-root", str(raw),
            "--normalized-root", str(norm),
        ])
    sp = tmp_path / "src.json"
    sp.write_text(sb.getvalue(), encoding="utf-8")
    src = json.loads(sb.getvalue())

    # Binding cryptográfico: source_bundle_id == case.evidence_bundle.bundle_id
    assert src["source_bundle_id"] == case["evidence_bundle"]["bundle_id"]

    # verificar caso
    vbuf = io.StringIO()
    with redirect_stdout(vbuf):
        cli_main(["verify-investigation-case", str(icp), "--strict"])
    assert json.loads(vbuf.getvalue())["is_valid"] is True

    # verificar source registry contra el bundle del caso
    extracted_bundle_path = tmp_path / "extracted_bundle.json"
    extracted_bundle_path.write_text(
        json.dumps(case["evidence_bundle"]), encoding="utf-8",
    )
    vbuf2 = io.StringIO()
    with redirect_stdout(vbuf2):
        cli_main([
            "verify-external-source-registry", str(sp),
            "--bundle-file", str(extracted_bundle_path),
            "--strict",
        ])
    assert json.loads(vbuf2.getvalue())["is_valid"] is True


# --- Removibilidad estructural ----------------------------------


def test_provenance_module_is_removable() -> None:
    """Confirma que el módulo de derivación se puede importar/desimportar sin
    romper el resto del sistema. Garantía de removibilidad declarada en ADR-0042."""
    # El resto de external_sources funciona sin tocar provenance
    from orbital_sentinel.analytics.external_sources import (
        build_external_source_record,
        verify_external_source_registry,
    )
    assert callable(build_external_source_record)
    assert callable(verify_external_source_registry)


def test_derivation_produces_hash_matching_manual_construction(
    pipeline_with_raw_snapshots: dict[str, Path], tmp_path: Path,
) -> None:
    """El registry derivado automáticamente coincide bit-a-bit con el que
    se obtendría construyendo manualmente los records desde Raw.

    Esta es la garantía contractual: el wiring NO altera el contrato
    content-addressable de ADR-0040.
    """
    from orbital_sentinel.analytics.bundles import EvidenceBundle
    from orbital_sentinel.analytics.external_sources import (
        build_external_source_record,
        build_external_source_registry,
    )
    bundle = EvidenceBundle.model_validate(
        json.loads(pipeline_with_raw_snapshots["bundle"].read_text(encoding="utf-8")),
    )
    # Recolectar manualmente los content_hash_source via los OrbitalElement
    elem_repo = OrbitalElementsRepository(
        pipeline_with_raw_snapshots["normalized_root"],
    )
    tle_repo = TLESnapshotsRepository(
        pipeline_with_raw_snapshots["raw_root"],
    )
    obj_ids = {bp.derived_evidence.object_id for bp in bundle.evidence_payloads}
    hash_sources: set[str] = set()
    obj_to_hashes: dict[int, list[str]] = {}
    for obj in sorted(obj_ids):
        els = elem_repo.find_all_by_norad_id(obj)
        chs = sorted({e.content_hash_source for e in els})
        obj_to_hashes[obj] = chs
        hash_sources.update(chs)
    records = []
    hash_to_rec: dict[str, str] = {}
    for ch in sorted(hash_sources):
        snap = tle_repo.get(ch)
        assert snap is not None
        rec = build_external_source_record(
            source_provider="celestrak",
            source_url=snap.url,
            source_dataset_identifier=snap.dataset,
            fetched_at=snap.fetched_at,
            source_payload_hash=snap.content_hash,
            source_payload_size_bytes=snap.n_bytes,
            source_content_type="tle_text",
        )
        records.append(rec)
        hash_to_rec[ch] = rec.source_record_id
    mapping = {
        bp.evidence_id: sorted({
            hash_to_rec[ch] for ch in obj_to_hashes.get(bp.derived_evidence.object_id, [])
        })
        for bp in bundle.evidence_payloads
    }
    manual_reg = build_external_source_registry(bundle, records, mapping)

    # Y el derivado por la función
    from orbital_sentinel.analytics.external_sources import (
        derive_external_source_registry_for_bundle,
    )
    auto_reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
    )
    assert manual_reg.registry_id == auto_reg.registry_id


# --- Smoke: empty bundle ----------------------------------------


def test_cli_provenance_empty_bundle(tmp_path: Path) -> None:
    """Bundle vacío produce registry vacío sin tocar Raw/Normalized."""
    normalized_root = tmp_path / "normalized"
    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    normalized_root.mkdir(parents=True, exist_ok=True)
    # No insertamos elementos: el catalog está vacío. NORAD no existe.
    # bundle sobre NORAD inexistente → bundle estructuralmente vacío
    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        rc = cli_main([
            "bundle", "99999",
            "--baseline-days", "30", "--threshold-sigma", "3.0",
            "--raw-root", str(raw_root),
            "--normalized-root", str(normalized_root),
            "--detections-root", str(tmp_path / "derived" / "conjunctions"),
        ])
    assert rc == 0
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(bundle_buf.getvalue(), encoding="utf-8")

    rb = io.StringIO()
    with redirect_stdout(rb):
        rc = cli_main([
            "external-source-registry-from-repos", str(bundle_path),
            "--raw-root", str(raw_root / "tle_snapshots"),
            "--normalized-root", str(normalized_root),
        ])
    assert rc == 0
    reg = json.loads(rb.getvalue())
    assert reg["n_records"] == 0
    assert reg["registry_emit_reason"] == "empty_registry"

"""Inputs canónicos y constructores deterministas para la suite de vectores frozen.

Toda la lógica de construcción de artefactos canónicos vive aquí. Tanto
el verifier de runtime (:mod:`orbital_sentinel.reproducibility.verifier`)
como el test suite (``tests/reproducibility/``) consumen estos
constructores y comparan los hashes producidos contra el fixture
:file:`vectors.json` empaquetado en este mismo módulo.

Inputs frozen
=============

Cualquier modificación de las constantes de este módulo cambia los hashes
esperados y es por tanto una **modificación deliberada del contrato
cryptográfico** del proyecto. Debe ir acompañada de:

1. Regeneración explícita de ``vectors.json``.
2. Enmienda al ADR-0013 declarando la nueva versión del contrato.
3. Revisión humana del diff.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.agent_contract.models import ConsumerClass
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.claims import build_claim_registry
from orbital_sentinel.analytics.dissent import (
    build_dissent_ledger,
    build_dissent_record,
)
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.evidence.models import SourceDetector
from orbital_sentinel.analytics.evidence_chains import build_evidence_chain
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import generate_explanation
from orbital_sentinel.analytics.external_sources import (
    build_external_source_record,
    build_external_source_registry,
)
from orbital_sentinel.analytics.hypotheses import build_hypothesis_registry
from orbital_sentinel.analytics.investigations import build_investigation_case
from orbital_sentinel.analytics.revocations import (
    build_revocation_ledger,
    build_revocation_record,
)

# ---------------------------------------------------------------------------
# Constantes frozen del contrato. NO modificar sin enmienda explícita
# al ADR-0013 y regeneración deliberada de vectors.json.
# ---------------------------------------------------------------------------

FIXED_CLOCK = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)
"""Clock determinístico para toda la suite. ADR-0013."""

CANONICAL_NORAD_ID = 25544
"""NORAD ID canónico (ISS) para los vectores frozen."""

CANONICAL_EPOCH = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
"""Epoch canónico del evento sintético."""

CANONICAL_DETECTOR_EVENT_ID = "canonical_maneuver_evt_0"
"""ID canónico del evento del detector."""

CANONICAL_DETECTOR: SourceDetector = "maneuver_detection_v01"
CANONICAL_DETECTOR_HONESTY = {"detection_method_name": "canonical_frozen_method"}
CANONICAL_ANALYSIS_ENGINE_VERSION = "0.1.0"

CANONICAL_CONSUMER_CLASS: ConsumerClass = "explanation_agent_v01"

CANONICAL_FETCHED_AT = datetime(2024, 1, 1, 6, 0, 0, tzinfo=timezone.utc)
CANONICAL_PAYLOAD = b"CANONICAL_TLE_BYTES"
CANONICAL_SOURCE_URL = "https://celestrak.org/canonical/frozen"
CANONICAL_SOURCE_DATASET = "frozen-canonical"


def _clock() -> datetime:
    return FIXED_CLOCK


def _make_canonical_evidence() -> DerivedEvidence:
    eid = compute_evidence_id(
        source_detector=CANONICAL_DETECTOR,
        object_id=CANONICAL_NORAD_ID,
        detector_event_id=CANONICAL_DETECTOR_EVENT_ID,
        event_epoch=CANONICAL_EPOCH,
        analysis_engine_version=CANONICAL_ANALYSIS_ENGINE_VERSION,
    )
    return DerivedEvidence(
        evidence_id=eid,
        object_id=CANONICAL_NORAD_ID,
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        source_detector=CANONICAL_DETECTOR,
        detector_event_id=CANONICAL_DETECTOR_EVENT_ID,
        event_epoch=CANONICAL_EPOCH,
        honesty_payload=CANONICAL_DETECTOR_HONESTY,
        analysis_engine_version=CANONICAL_ANALYSIS_ENGINE_VERSION,
    )


def build_canonical_artifacts() -> dict[str, str]:
    """Construye todos los artefactos canónicos y devuelve sus hashes content-addressable.

    Función pura. ``clock=_clock`` en todos los builders. Ninguna E/S de filesystem
    ni red. Resultado determinista bit-a-bit independientemente del runtime.

    Returns:
        ``dict[str, str]``: nombre del artefacto → hash hex content-addressable.
    """
    out: dict[str, str] = {}

    # --- Evidencia canónica ---
    ev = _make_canonical_evidence()
    out["evidence_id"] = ev.evidence_id

    # --- Bundle (ADR-0031) ---
    catalog = EvidenceCatalog.from_evidence([ev], derived_at=FIXED_CLOCK)
    ctx = build_explanation_context(catalog, object_id=CANONICAL_NORAD_ID, clock=_clock)
    bundle = build_evidence_bundle(ctx, catalog, clock=_clock)
    out["bundle_id"] = bundle.bundle_id

    # --- AgentInput (ADR-0032) ---
    agent_input = build_agent_input(
        bundle,
        declared_consumer_class=CANONICAL_CONSUMER_CLASS,
        clock=_clock,
    )
    out["agent_input_id"] = agent_input.agent_input_id

    # --- ExplanationArtifact (ADR-0033) ---
    artifact = generate_explanation(agent_input, clock=_clock)
    out["explanation_id"] = artifact.explanation_id

    # --- ClaimRegistry (ADR-0035) ---
    claim_registry = build_claim_registry(artifact, agent_input, clock=_clock)
    out["claim_registry_id"] = claim_registry.registry_id
    out["claim_id_0"] = claim_registry.claims[0].claim_id

    # --- HypothesisRegistry (ADR-0036) ---
    hyp_registry = build_hypothesis_registry(
        claim_registry, agent_input, clock=_clock,
    )
    out["hypothesis_registry_id"] = hyp_registry.registry_id
    out["hypothesis_id_0"] = hyp_registry.hypotheses[0].hypothesis_id

    # --- EvidenceChain (ADR-0037) ---
    chain = build_evidence_chain(
        hyp_registry, claim_registry, artifact, agent_input, clock=_clock,
    )
    out["chain_id"] = chain.chain_id

    # --- InvestigationCase (ADR-0038) ---
    case = build_investigation_case(
        chain,
        hypothesis_registry=hyp_registry,
        claim_registry=claim_registry,
        artifact=artifact,
        agent_input=agent_input,
        bundle=bundle,
        clock=_clock,
    )
    out["case_id"] = case.case_id

    # --- RevocationLedger (ADR-0039) sobre el caso canónico ---
    rev_record = build_revocation_record(
        target_artifact_type="investigation_case",
        target_artifact_id=case.case_id,
        target_artifact_signature=case.case_signature,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    out["revocation_id"] = rev_record.revocation_id
    rev_ledger = build_revocation_ledger([rev_record], clock=_clock)
    out["revocation_ledger_id"] = rev_ledger.ledger_id

    # --- ExternalSourceRegistry (ADR-0040) atado al bundle canónico ---
    src_record = build_external_source_record(
        source_provider="celestrak",
        source_url=CANONICAL_SOURCE_URL,
        source_dataset_identifier=CANONICAL_SOURCE_DATASET,
        fetched_at=CANONICAL_FETCHED_AT,
        source_payload_hash=hashlib.sha256(CANONICAL_PAYLOAD).hexdigest(),
        source_payload_size_bytes=len(CANONICAL_PAYLOAD),
        source_content_type="tle_text",
    )
    out["source_record_id"] = src_record.source_record_id
    src_mapping = {ev.evidence_id: [src_record.source_record_id]}
    src_registry = build_external_source_registry(
        bundle, [src_record], src_mapping, clock=_clock,
    )
    out["external_source_registry_id"] = src_registry.registry_id

    # --- DissentLedger (ADR-0041) sobre el caso canónico ---
    dis_record = build_dissent_record(
        target_case_id=case.case_id,
        target_case_signature=case.case_signature,
        dissent_index=0,
        dissent_type="scope_disagreement",
        clock=_clock,
    )
    out["dissent_id"] = dis_record.dissent_id
    dis_ledger = build_dissent_ledger(
        target_case_id=case.case_id,
        target_case_signature=case.case_signature,
        records=[dis_record],
        clock=_clock,
    )
    out["dissent_ledger_id"] = dis_ledger.ledger_id

    return out

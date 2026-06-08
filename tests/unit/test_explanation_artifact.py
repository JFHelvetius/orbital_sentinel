"""Tests de modelos del Explanation Agent (ADR-0033)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.explanation_agent import (
    EXPLANATION_AGENT_ENGINE_VERSION,
    EXPLANATION_AGENT_SCHEMA_VERSION,
    GENERATION_METHOD_V01,
    MODEL_IDENTIFIER_V01,
    ExplanationArtifact,
    ExplanationAuditRecord,
    ExplanationGenerationMetadata,
    all_templates_canonical,
    compute_explanation_id,
    compute_prompt_hash,
)

DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _make_artifact(*, evidence_ids: list[str] | None = None) -> ExplanationArtifact:
    ev_ids = evidence_ids or []
    prompt_hash = compute_prompt_hash(
        templates_canonical=all_templates_canonical(),
        engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    explanation_id = compute_explanation_id(
        source_agent_input_id="a" * 64,
        source_bundle_id="b" * 64,
        prompt_hash=prompt_hash,
        explanation_engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    return ExplanationArtifact(
        explanation_id=explanation_id,
        source_agent_input_id="a" * 64,
        source_bundle_id="b" * 64,
        referenced_evidence_ids=list(ev_ids),
        explanation_text="Evidence catalog is empty.",
        generation_metadata=ExplanationGenerationMetadata(
            prompt_hash=prompt_hash,
            n_evidence_processed=len(ev_ids),
        ),
        audit_record=ExplanationAuditRecord(
            explanation_id=explanation_id,
            agent_input_id="a" * 64,
            bundle_id="b" * 64,
            evidence_ids_used=list(ev_ids),
            generation_timestamp=DERIVED_AT,
            prompt_hash=prompt_hash,
        ),
        generated_at=DERIVED_AT,
    )


# --- Helpers de hash ----------------------------------------------


def test_compute_explanation_id_deterministic() -> None:
    a = compute_explanation_id(
        source_agent_input_id="x", source_bundle_id="y",
        prompt_hash="p", explanation_engine_version="0.1.0",
    )
    b = compute_explanation_id(
        source_agent_input_id="x", source_bundle_id="y",
        prompt_hash="p", explanation_engine_version="0.1.0",
    )
    assert a == b
    assert len(a) == 64


def test_compute_explanation_id_varies_with_inputs() -> None:
    a = compute_explanation_id(
        source_agent_input_id="x1", source_bundle_id="y",
        prompt_hash="p", explanation_engine_version="0.1.0",
    )
    b = compute_explanation_id(
        source_agent_input_id="x2", source_bundle_id="y",
        prompt_hash="p", explanation_engine_version="0.1.0",
    )
    assert a != b


def test_compute_prompt_hash_deterministic() -> None:
    a = compute_prompt_hash(templates_canonical="T", engine_version="0.1.0")
    b = compute_prompt_hash(templates_canonical="T", engine_version="0.1.0")
    assert a == b
    assert len(a) == 64


def test_all_templates_canonical_includes_all_v01_templates() -> None:
    canonical = all_templates_canonical()
    assert "maneuver_detection_v01" in canonical
    assert "anomaly_detection_v01" in canonical
    assert "conjunction_detection_v01" in canonical


# --- Versioning constants -----------------------------------------


def test_versioning_constants() -> None:
    assert EXPLANATION_AGENT_SCHEMA_VERSION == "0.1.0"
    assert EXPLANATION_AGENT_ENGINE_VERSION == "0.1.0"
    assert MODEL_IDENTIFIER_V01 == "template_explanation_v01"
    assert GENERATION_METHOD_V01 == "deterministic_template_concatenation_v01"


# --- ExplanationGenerationMetadata --------------------------------


def test_metadata_extra_forbid_and_frozen() -> None:
    m = ExplanationGenerationMetadata(prompt_hash="x", n_evidence_processed=0)
    with pytest.raises(Exception):
        ExplanationGenerationMetadata.model_validate(
            {**m.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        m.prompt_hash = "y"  # type: ignore[misc]


def test_metadata_defaults_v01() -> None:
    m = ExplanationGenerationMetadata(prompt_hash="x", n_evidence_processed=3)
    assert m.model_identifier == MODEL_IDENTIFIER_V01
    assert m.generation_method == GENERATION_METHOD_V01


def test_metadata_n_evidence_processed_ge_zero() -> None:
    with pytest.raises(Exception):
        ExplanationGenerationMetadata(prompt_hash="x", n_evidence_processed=-1)


# --- ExplanationAuditRecord --------------------------------------


def test_audit_record_extra_forbid_and_frozen() -> None:
    rec = ExplanationAuditRecord(
        explanation_id="x", agent_input_id="a", bundle_id="b",
        evidence_ids_used=[], generation_timestamp=DERIVED_AT,
        prompt_hash="p",
    )
    with pytest.raises(Exception):
        ExplanationAuditRecord.model_validate(
            {**rec.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        rec.bundle_id = "z"  # type: ignore[misc]


def test_audit_record_default_model_identifier() -> None:
    rec = ExplanationAuditRecord(
        explanation_id="x", agent_input_id="a", bundle_id="b",
        evidence_ids_used=[], generation_timestamp=DERIVED_AT,
        prompt_hash="p",
    )
    assert rec.model_identifier == MODEL_IDENTIFIER_V01


# --- ExplanationArtifact -----------------------------------------


def test_artifact_extra_forbid_and_frozen() -> None:
    art = _make_artifact()
    with pytest.raises(Exception):
        ExplanationArtifact.model_validate(
            {**art.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        art.explanation_text = "MUTATED"  # type: ignore[misc]


def test_artifact_roundtrip() -> None:
    art = _make_artifact(evidence_ids=["ev-1", "ev-2"])
    raw = art.model_dump(mode="json")
    re = ExplanationArtifact.model_validate(raw)
    assert re.model_dump(mode="json") == raw


def test_artifact_invariant_referenced_must_match_audit() -> None:
    """Hard invariant: referenced_evidence_ids debe coincidir con audit."""
    prompt_hash = compute_prompt_hash(
        templates_canonical=all_templates_canonical(),
        engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    explanation_id = compute_explanation_id(
        source_agent_input_id="a", source_bundle_id="b",
        prompt_hash=prompt_hash,
        explanation_engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    with pytest.raises(Exception, match=r"audit_record\.evidence_ids_used"):
        ExplanationArtifact(
            explanation_id=explanation_id,
            source_agent_input_id="a", source_bundle_id="b",
            referenced_evidence_ids=["ev-1"],
            explanation_text="t",
            generation_metadata=ExplanationGenerationMetadata(
                prompt_hash=prompt_hash, n_evidence_processed=0,
            ),
            audit_record=ExplanationAuditRecord(
                explanation_id=explanation_id,
                agent_input_id="a", bundle_id="b",
                evidence_ids_used=[],  # divergencia: referenced tiene 1, audit 0
                generation_timestamp=DERIVED_AT,
                prompt_hash=prompt_hash,
            ),
            generated_at=DERIVED_AT,
        )


def test_artifact_invariant_audit_explanation_id_must_match() -> None:
    """Hard invariant: audit.explanation_id == artifact.explanation_id."""
    prompt_hash = compute_prompt_hash(
        templates_canonical=all_templates_canonical(),
        engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    artifact_id = "a" * 64
    audit_id = "b" * 64  # diverge
    with pytest.raises(Exception, match=r"audit_record\.explanation_id"):
        ExplanationArtifact(
            explanation_id=artifact_id,
            source_agent_input_id="a", source_bundle_id="b",
            referenced_evidence_ids=[],
            explanation_text="t",
            generation_metadata=ExplanationGenerationMetadata(
                prompt_hash=prompt_hash, n_evidence_processed=0,
            ),
            audit_record=ExplanationAuditRecord(
                explanation_id=audit_id,
                agent_input_id="a", bundle_id="b",
                evidence_ids_used=[],
                generation_timestamp=DERIVED_AT,
                prompt_hash=prompt_hash,
            ),
            generated_at=DERIVED_AT,
        )

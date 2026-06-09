# Orbital Sentinel

[![tests](https://github.com/JFHelvetius/orbital_sentinel/actions/workflows/test.yml/badge.svg)](https://github.com/JFHelvetius/orbital_sentinel/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/orbital-sentinel.svg)](https://pypi.org/project/orbital-sentinel/)
[![Python](https://img.shields.io/pypi/pyversions/orbital-sentinel.svg)](https://pypi.org/project/orbital-sentinel/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Verifiable infrastructure for claims about the near-Earth orbital environment.**

Orbital Sentinel is open-source software that lets anyone — without privileged data access, without authority, without trust — *prove* what is happening in orbit around Earth and *audit* anyone else's claim about it.

It is not a satellite tracker, not a visualization tool, not a dashboard. It is a **content-addressable provenance chain** that ties every conclusion back to the original public bytes that produced it.

```bash
pip install orbital-sentinel
orbital-sentinel self-verify --strict
# {"contract_version": "1.0.0", "is_valid": true, "n_hashes_verified": 16, ...}
```

---

## Why this exists

Today, when someone says *"this satellite performed a maneuver"*, *"these two objects approached each other"*, or *"that debris came from that rocket"*, the rest of the world has to choose between **believing** them or **redoing the analysis from scratch**. There is no shared mechanism by which an independent journalist, an academic researcher, a small national space agency, or a curious citizen can verify the claim end-to-end against the original data.

This forces the public discourse about orbital events to be **authority-based**. The few entities with privileged data emit claims; everyone else either believes or stays silent.

Orbital Sentinel is a bet on a different model: claims about the orbital environment can be **cryptographically auditable** by anyone, ingested from public sources, with no AI or scoring in between to launder uncertainty.

## What you actually get

A producer ingests public TLEs from Celestrak, runs the analysis pipeline, and emits a single `InvestigationCase` JSON file containing:

* The original ingestion record (URL, fetch timestamp, payload SHA-256)
* The derived evidence (detector outputs with honesty fields preserved)
* The atomic claims (one verifiable statement per line of the explanation)
* The composite hypothesis they support
* The end-to-end content-addressable chain linking everything

Any third party can then:

```bash
pip install orbital-sentinel
orbital-sentinel self-verify --strict                            # confirms your install matches the canonical contract
orbital-sentinel verify-investigation-case <case.json> --strict  # confirms the case is internally consistent
orbital-sentinel verify-external-source-registry <src.json> \    # confirms the provenance chain back to the original bytes
    --bundle-file <bundle.json> --strict
```

And if the third party disagrees, they can publish a **dissent** with the same cryptographic guarantee:

```bash
orbital-sentinel dissent-record \
    --target-case-id <case_id> --target-case-signature <case_sig> \
    --dissent-type factual_correction \
    --basis-evidence-id <new_evidence>
```

There is no asymmetry between producer and reviewer.

## Two real reference cases

Both built from a real Celestrak ingestion on 2026-06-08:

* [`reference_cases/iss_conjunction_001/`](reference_cases/iss_conjunction_001/) — 9 conjunction events for the **International Space Station** over a 7-day window. One real non-cooperative approach (HMU-SAT2 cubesat at 46.91 km on 2026-06-14).

* [`reference_cases/tiangong_conjunction_002/`](reference_cases/tiangong_conjunction_002/) — 6 conjunction events for the **Chinese Space Station** (CSS TIANHE) over the same window. Two real non-cooperative approaches.

Cross-case finding: the cubesat HMU-SAT2 appears as a real approach to **both** stations in the same window. A correlation only visible because evidence is content-addressable.

A third-party audit demonstration is included in [`reference_cases/external_audit_demo/`](reference_cases/external_audit_demo/), running every verifier from a fresh installation and recomputing the SHA-256 of the original Celestrak bytes against the producer's declared hash.

## What this is *not*

Honesty about scope is part of the contract:

* **No AI, no LLM, no ML, no NLP.** Every explanation is mechanical template-driven text. The system does not *interpret*; it *cites*.
* **No risk scores, no threat classification, no probabilities of intent.** Geometry with declared uncertainty, nothing more.
* **No central authority.** Producers, reviewers, and dissenters have identical cryptographic guarantees.
* **No new external dependencies at runtime.** Stdlib + Pydantic + DuckDB + PyArrow + SGP4.
* **No silent failures.** Every verifier is a pure function that always returns a report; nothing is ever hidden behind "trust me".

If you are looking for *"AI-powered space situational awareness"*, this is not the project.

## What it does well today

* **1053 tests passing** on every commit (matrix Python 3.11 + 3.12, Linux CI).
* **Frozen cryptographic contract v1.0.0** with 16 hashes covering 11 architectural layers. Any change that silently alters hash output is detected by CI.
* **Reproducible end-to-end**: same inputs, same hashes, every install, forever (ADR-0013).
* **Removable layers**: every layer can be deleted without breaking the rest — proof of clean architectural boundaries.

## Documentation

The architecture is fully documented as **43 ADRs** (Architecture Decision Records) in [`docs/adr/`](docs/adr/). They are written in Spanish. If you want to deeply understand the project, that is the only place to start. They are the contract.

Quick reading path:

1. [ADR-0000 — Long-term vision](docs/adr/0000-long-term-vision.md) — what the project is and is not.
2. [ADR-0013 — Reproducibility under declared environment](docs/adr/0013-reproducibility-declared-environment.md) — the core property and its empirical validation.
3. [ADR-0031 — Verifiable Evidence Bundle Layer](docs/adr/0031-verifiable-evidence-bundle-layer-v01.md) — the foundational content-addressable artifact.
4. [ADR-0038 — Investigation Case Layer](docs/adr/0038-investigation-case-layer-v1.md) — the portable end-to-end unit.
5. [ADR-0041 — Dissent Layer](docs/adr/0041-dissent-layer-v1.md) — how independent reviewers participate.

## How to contribute

Three roles, three ways:

* **Producer**: build new `InvestigationCase` files about real orbital events and publish them.
* **Reviewer**: pick any published case, run the verifiers, and publish your audit report (see [`reference_cases/external_audit_demo/AUDIT_REPORT.md`](reference_cases/external_audit_demo/AUDIT_REPORT.md) for the format).
* **Dissenter**: build a `DissentLedger` against any case you believe is incomplete, incorrect, or methodologically flawed.

Issue templates are provided for all three roles. Pull requests welcome but not required — **the artifacts themselves are the contribution**.

## License

[Apache License 2.0](LICENSE). Commercial use allowed. Patent grant included.

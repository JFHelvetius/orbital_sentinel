# Why I Can't Trust What's Happening in Orbit

### (And why that should bother you too)

Last week, two satellites in low Earth orbit passed within tens of kilometers of each other. I know that because I downloaded a TLE file from CelesTrak, ran SGP4 propagation over a seven-day window, and computed the conjunction.

What I *don't* know is whether you can trust me.

You can read my source code. You can install my software. You can re-run my pipeline on your machine. But unless you do all three of those things — and you happen to have the same Python version and the same versions of every dependency — you have to trust that my numbers are right.

And here's the thing: today, almost no one does that. When LeoLabs announces an upcoming conjunction event, when Roscosmos claims a maneuver was routine, when CelesTrak publishes today's orbital elements, when NASA's Conjunction Assessment Risk Analysis flags a debris fragment — the global public discourse about what is happening in orbit is built on a model that asks the rest of the world to *believe*.

This works fine when authorities are correct, careful, and benevolent. It breaks down quickly when any of those three falter, or when the stakes get high enough to incentivize selective framing.

I think we can do better. I built something to demonstrate how.

---

## The project

**Orbital Sentinel** (`pip install orbital-sentinel`) is open-source software that lets anyone produce, verify, and dispute claims about the near-Earth orbital environment without trusting the producer.

The unit of work is an **`InvestigationCase`** — a single JSON file that contains everything needed to reach a conclusion about an orbital event:

- The original ingestion record (URL, fetch timestamp, SHA-256 of the bytes received).
- The derived evidence (detector outputs with their honesty fields preserved).
- The atomic claims (one verifiable statement per line of the explanation).
- The composite hypothesis they support.
- The cryptographic chain linking everything end-to-end.

If I send you a `case.json`, you can run:

```bash
pip install orbital-sentinel
orbital-sentinel self-verify --strict
orbital-sentinel verify-investigation-case case.json --strict
```

And you'll get a deterministic answer about whether my case is internally consistent. Not "probably." Not "with 95% confidence." A bit-exact match against a frozen cryptographic contract.

If you disagree with my conclusions, you can publish your own **`DissentLedger`**. It's a peer artifact, not a comment thread. It has the same cryptographic weight as my case did.

**There is no asymmetry between producer and reviewer.**

---

## A real example

I shipped two reference cases with the v0.1.0 release. They are produced from a single real CelesTrak ingestion on 2026-06-08 of the `stations` dataset (25 TLEs of all currently active space stations and visiting vehicles).

**Case 001 — ISS conjunction risk over 7 days.** Nine events detected. Eight of them are co-orbital modules and visiting vehicles already docked to the ISS (Progress, Cygnus, Soyuz, Crew Dragon) — miss distances at or near 0 km, which is exactly what you'd expect for things already attached to the station. The ninth event is real: NORAD 67688 (**HMU-SAT2**, a Malaysian cubesat) is predicted to approach the ISS within **46.91 km** on 2026-06-14T08:46Z.

**Case 002 — Tiangong conjunction risk over 7 days.** Same ingestion, different primary object (the Chinese space station). Six events. Four co-orbital. Two real non-cooperative approaches — including **HMU-SAT2 again at 25.70 km**.

A cubesat approaching both space stations within the same week is a real correlation. Not a flag, not an alert, not a risk score. Just a geometric fact, derived from public bytes, cryptographically tied to those bytes, and re-verifiable by anyone in the world for as long as Python and SHA-256 exist.

If you don't trust me, you don't have to. You can download `case.json`, run the verifiers, recompute the SHA-256 of the original CelesTrak payload from the producer's cache, and either reach the same conclusion or publish a dissent saying why I'm wrong.

---

## What's actually new here

Plenty of people have written orbital propagation code. Plenty of people have published TLE-based conjunction analyses. The new thing isn't the math.

The new thing is the **chain of custody**:

1. **The original CelesTrak bytes are content-addressed by SHA-256.** If those bytes change tomorrow (because CelesTrak updates the TLE — which they do, often), my hash still pins what *I* downloaded.
2. **Every derived artifact carries the hash of its inputs.** Bundle hashes evidence. Agent input hashes bundle. Explanation hashes agent input. Claims hash explanation. Hypothesis hashes claims. Chain hashes hypothesis. Case hashes chain. Break any link and the next hash is wrong.
3. **The explanation is mechanical**, not generated. Every sentence is a template-filled statement of the form *"Detector X identified event Y at time Z with miss distance D"*. No LLM, no NLP, no judgment about what it *means*.
4. **Verifiers are pure functions** that always return a structured report — never an exception, never a silent pass. If something is wrong, you get a typed finding with the exact discrepancy.
5. **The contract is frozen.** Sixteen canonical hashes are hardcoded into the test suite. CI verifies them on every commit. If I (or any future contributor) accidentally change anything that alters those hashes, CI fails loudly.

This is not the architecture of "AI for space situational awareness." It's the architecture of **public infrastructure for verifiable orbital claims**.

---

## What this is *not*

Honesty about scope matters more than coverage:

- **No AI, no LLM, no ML.** I will refuse PRs that introduce them. The point is verifiability, not cleverness.
- **No risk scores.** I don't tell you a conjunction is "dangerous." I tell you the miss distance and the propagation uncertainty. You decide.
- **No central server.** Cases live wherever you put them. The verifiers run on your machine.
- **No threat models, no attribution, no classification.** Geometry only.
- **No real-time anything.** TLEs are perishable; the system documents that explicitly via content-addressable provenance and preserves the original bytes you fetched.

If you came expecting "AI-powered SSA," you came to the wrong project. If you came expecting "an open Wikipedia for what's happening in orbit," you're closer.

---

## Why this matters

Three trajectories for the next decade of orbital governance:

**Trajectory A — Authority.** Each operator continues making claims. The rest of the world chooses who to believe. Dominant agencies establish narratives that can't be contradicted with comparable rigor. Smaller countries, smaller operators, independent observers, journalists, and the public have no recourse.

**Trajectory B — Algorithmic authority.** An "AI for space safety" platform emerges, managed by a company or coalition, that emits risk scores everyone is expected to trust. The trust shifts from agencies to platforms, but the asymmetry — and the inability to audit the underlying reasoning — remains.

**Trajectory C — Verifiable public infrastructure.** A layer analogous to TCP/IP, to HTTPS, to Wikipedia, to Git: any orbital claim is subject to the same process. Anyone can verify. Anyone can dissent. Truth emerges from the contrast of cryptographic evidence rather than from the authority of the emitter.

Orbital Sentinel is a bet on Trajectory C.

It is a small bet today. v0.1.0. Two reference cases. One contributor. But the architecture is correct, the contract is frozen, and the entry point for anyone in the world to participate is `pip install orbital-sentinel`.

---

## What you can do

The project is on PyPI. It works today. It has frozen tests passing on every commit. It has two real reference cases verifiable offline.

What it doesn't have is **you**.

- **If you're a researcher**, build a case about an orbital event you care about and publish it. The infrastructure is ready.
- **If you're a journalist covering space**, the next time a "near-miss" story breaks, ask the agencies involved for a verifiable case file. If they don't have one, ask why not.
- **If you're a developer**, audit a published case (the `AUDIT_REPORT.md` template is included) and submit a dissent if you disagree.
- **If you're at a national space agency**, especially one without privileged data access, this is the toolkit you've been missing.
- **If you work on reproducibility in science**, this is what content-addressable provenance looks like when it's applied to an actual high-stakes domain.

The architecture is documented in 43 ADRs (Architecture Decision Records, in Spanish — full translation pending community help). The tests are exhaustive. The cryptographic contract is empirically frozen. The three roles — producer, reviewer, dissenter — are symmetric.

What's missing is community. That's what comes next.

---

## Links

- **Code**: https://github.com/JFHelvetius/orbital_sentinel
- **Package**: https://pypi.org/project/orbital-sentinel/
- **Reference cases**: [reference_cases/](../reference_cases/)
- **Architecture (ADRs)**: [docs/adr/](adr/)
- **Issue templates** (the three roles, encoded): [.github/ISSUE_TEMPLATE/](../.github/ISSUE_TEMPLATE/)

If you have questions, open a GitHub Discussion. If you find a bug, file an issue. If you disagree with anything I've claimed in this essay, build the dissent.

That's the protocol.

---

*Posted 2026-06-08. License: same as the project — Apache 2.0. Reuse, translate, criticize, dissent.*

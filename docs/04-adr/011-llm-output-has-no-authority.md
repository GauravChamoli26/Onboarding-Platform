# ADR-011: LLM output has no authority over state or authorisation

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** B-06, D-02

## Context

Candidate-supplied text — resumes, and later screening transcripts — flows through four LLM paths. A candidate can embed instructions in a resume: white text, document metadata, a footer. This is a documented attack against exactly this class of system, and the attacker here has direct motive: they are being evaluated.

The spec already says AI scoring is advisory and humans decide. That was written as a fairness requirement.

## Decision

LLM output never drives a state transition, an authorisation decision, or an approval. It informs a human who decides.

Supporting controls:

- Candidate text is passed as clearly bounded input, never concatenated into the instruction portion of a prompt
- Every response is parsed into a Pydantic model; schema failure is an error, not a fallback
- Scores are clamped to range; rationale text is length-capped
- Resumes whose extracted text contains instruction-like patterns are flagged to HR rather than silently discarded
- A corpus of injection-styled resumes runs in CI, asserting score stability

## Consequences

A successful prompt injection can, at worst, produce a misleading summary that a human reads and evaluates. It cannot advance an application, approve an offer, or change a permission.

The fairness requirement and the security control turn out to be the same requirement. That is worth noticing: keeping humans in the decision loop is not only an ethical position, it caps the blast radius of a class of attack.

The cost is that no part of the pipeline can be fully automated on LLM output, even where that would be convenient.

This reinforces the deferral of `salary_fit_score` and `offer_confidence_score` (D-02): opaque numbers touching compensation are both harder to validate for fairness and harder to sanity-check against manipulation.

## Alternatives considered

**Auto-reject below a score threshold** — an obvious efficiency win, and rejected. It would make the score authoritative, which makes injection profitable and disparate impact invisible.

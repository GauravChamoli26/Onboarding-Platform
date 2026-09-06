# Employee Onboarding & Recruitment Platform
# 03 — Solution Design Document 3.0

**Status: SEALED.** Aligned to Build Spec V3.3.
**Supersedes:** SDD 2.0 (aligned to V3.2), SDD 1.0 (aligned to V3).
**Sealed:** 30 August 2026

This document bridges the sealed functional spec (02) and the engineering build. It is assembled in dependency order so that Phase 0 and Phase 1 can start against Sections 0–3 and 6 without waiting on any remaining business input.

Changes to this document require a Decision Log entry (01).

---

## Changelog

### SDD 2.0 → 3.0 — realignment to Spec V3.3

| # | Change | Decision |
|---|---|---|
| T1 | **Kit dispatch modelled properly.** Gifteko is first-party, not a vendor. New entities: Kit Catalogue Item, Organization Kit Profile, Client Kit. Dispatch Record now references a versioned Client Kit rather than a `kit_type` string | D-04, G-07 |
| T2 | **Kit readiness relocated to customer onboarding.** Branding artwork, proof and production happen once per customer with a multi-week lead time. New `AwaitingKitReadiness` dispatch status and readiness state machine | D-10 |
| T3 | **Three fulfilment modes** — buffer stock, weekly batching, drop-ship per hire — configured per customer, because the choice determines the dispatch SLA | D-12 |
| T4 | **Retention rewritten as three clocks**, with the Employment Record Pack handoff replacing multi-year joiner retention | C-02 to C-07 |
| T5 | **CTC calculator resolved** against the Labour Codes. Basic at 50% of CTC; Wage Code validation blocks offer generation | E-01, E-02 |
| T6 | **Voice AI deferred.** Layer 1 and Layer 2 adapter interfaces preserved behind an `AIScreening` flag; Screening Call Record unchanged so the manual path produces identical records | D-01 |
| T7 | **BGV manual-entry mode** added alongside the vendor adapter interface | D-05 |
| T8 | **Application security section** added (§1.4) with a ranked threat model, prompt-injection controls and portal token handling | B-01 to B-08 |
| T9 | **S1–S7 resolved in Spec V3.3** and removed from this document's change-control queue | — |
| T10 | New events: `EmploymentRecordHandedOff`, `EmploymentHandoffFailed`, `KitDispatchAwaitingReadiness`, `KitProfileReadinessChanged` | — |

### SDD 1.0 → 2.0 — realignment to V3.2 and structural gap fixes

SDD 1.0 was drafted against Spec V3 and predated the V3.2 seal. Retained below because the gaps it closed explain much of the current structure.

#### Realignment to V3.2

| # | Change | Origin |
|---|---|---|
| R1 | **Screening Call Record split across two layers.** Now stores `telephony_call_id` (Exotel) and `voice_ai_session_id` (Layer 2), plus transport-layer recording reference and retention date. | V3.2 architecture change |
| R2 | **Vendor selection closed** (Checklist item 5). Digio, AuthBridge, Exotel, Gifteko, AWS Mumbai, India-region LLM endpoints. Only the Voice AI layer remains pilot-pending. | V3.2 Vendor Selection |
| R3 | **Integration count corrected to 12**, not 11 — Tira became two integrations. Blocked-on-vendor count drops from 3 to 1. | V3.2 architecture change |
| R4 | **Domain Event catalogue re-pointed at the V3.2 list** (SDD 1.0 referenced the superseded V3 list) and extended — see Section 2. | V3.2 Architecture Foundation |
| R5 | **Data residency modelled as a first-class platform constraint**, including LLM inference endpoints and vendor attestation tracking. | V3.2 NFR |
| R6 | **SMS consolidated onto Exotel** with DLT template registration modelled explicitly. | V3.2 vendor consolidation |

#### Structural gap fixes

| # | Gap in SDD 1.0 | Fix |
|---|---|---|
| G1 | Approvals were nullable `approver_id` columns on three entities. Delegation, escalation and an approvals queue are unbuildable on that. | New shared **Approval Request / Approval Action / Approval Delegation** entities. All approval gates route through one engine. |
| G2 | No User, Role, or identity model. Every `user ref` and `actor_id` dangled. | New **User, Role, Role Assignment, Identity Provider Config** entities. |
| G3 | No entity for the candidate portal's expiring scoped links — the entire candidate security boundary. | New **Candidate Portal Token** entity. |
| G4 | `interviewer_ids array` cannot carry per-interviewer state (assignment status, per-person feedback SLA, reschedule requests, "own round only" note scope). | New **Interviewer Assignment** entity; Feedback now hangs off the assignment. |
| G5 | Fairness sign-off was a boolean on each summary row; V3.2 scopes it to a model version. | New **Model Version** and **Fairness Review** entities; the gate moves to the version. |
| G6 | Consent Log recorded grants only — no revocation, no validity expiry — while Module 10 requires both plus "more restrictive consent wins" at merge. | Consent Log becomes stateful: `status`, `revoked_at`, `expires_at`, `superseded_by`. |
| G7 | No BGV consent type despite BGV being the most consent-sensitive processing in the platform. | `BackgroundVerification` added to the consent type enum; BGV initiation gated on it. |
| G8 | Retention preserved "an anonymized aggregate record per Application" with no entity, no purge fields, and nothing for `RetentionPurgeExecuted` to attach to. | New **Application Analytics Record** and **Retention Job Run** entities; purge lifecycle fields on Candidate Profile. |
| G9 | CTC rules and approval thresholds were mutable unversioned JSON on Organization, while offers are legal documents that must be reproducible. | New versioned **CTC Rule Set** and **Approval Band Policy** entities; the version is stamped onto Offer and Negotiation Log. |
| G10 | Two different snapshot strategies (JD copied inline, pipeline referenced by FK) with no immutability guarantee on template versions. | Template versions are declared **immutable rows**; the FK snapshot is now safe. Stated as a constraint, not a convention. |
| G11 | Offer status enum had no `Declined`; `Reissued` duplicated the version chain. | Enum corrected; `Superseded` replaces `Reissued`; decline reason captured. |
| G12 | Interview Round enum had no Cancelled/Rescheduled despite both events existing; round decision had nowhere to live. | Enum corrected; `round_decision` + `rejection_reason_code` added. |
| G13 | Domain Event lacked `actor_id`, schema version, and sequencing — but the Timeline is defined as a read-layer over it and needs actor. | Envelope corrected in Section 2. |
| G14 | Notification Log had no DLT template reference — a regulatory requirement for Indian SMS. | New **Notification Template** entity (DLT registration + version); Notification Log references it. |
| G15 | `Marksheet` as a single enum value with one row per type made multiple marksheets unrepresentable. `address` existed in three places with no source of truth. | Document Submission keyed on `(application_id, document_type, sequence)`; address source-of-truth rule stated. |
| G16 | No async failure states. Resume parsing will fail on real files. | `Parse-Failed`, `Score-Failed`, `Screening-Unreachable` added to the state machine with defined recovery paths. |
| G17 | No constraints or indexes declared anywhere in a document claiming Sprint 1 readiness. | Constraint block added per entity group; multi-tenancy enforcement strategy stated in Section 6. |
| G18 | Board posting status JSON implied API parity across boards; LinkedIn is manual at launch. | **Board Posting** entity split out, with manual attestation fields. |

#### Spec-level contradictions — resolved in V3.3

SDD 2.0 raised seven contradictions internal to Spec V3.2 (S1–S7). All seven were resolved in Spec V3.3 §"Resolution of S1–S7" and are no longer open against this document. Two are worth carrying forward as design constraints:

- **S1/D-07:** Aadhaar capture is a prerequisite of the *signing step*, not of Module 6. Branch B (post-signature document collection) is specified in the state machine but **not built initially** — the ordering is configuration so Branch B is additive later.
- **S3:** `proposed_joining_date` appears in the offer letter; `confirmed_joining_date` is entered post-signature. Both fields exist on the Offer entity.

---

## Solution Design Checklist

| # | Item | Status |
|---|---|---|
| 1 | Data Model / ERD | Complete — Section 1 |
| 2 | Domain Event Contracts | Complete — Section 2 |
| 3 | Integration / API Contracts (12 integrations) | Complete — Section 3. Voice AI deferred with seam preserved |
| 4 | Business Rules & Configuration | **Complete** — Section 4. CTC resolved; band thresholds have an interim default |
| 5 | Vendor Positions | Closed — Section 5. Voice deferred, BGV contract deferred, both with adapters built |
| 6 | Non-Functional / Platform Design | Complete — Section 6 |
| 7 | Acceptance Criteria / Test Plan per Module | Complete — Section 7 |

---

## Section 0. Conventions

**Applied to every entity unless noted:**

- `id` — UUID v7 (time-ordered, index-friendly), primary key.
- `organization_id` — UUID FK, multi-tenant scope. Present on every entity without exception, including child records, so that tenant isolation can be enforced at a single layer rather than inferred through joins.
- `created_at`, `updated_at` — timestamptz, UTC. Display in Asia/Kolkata.
- `created_by`, `updated_by` — FK → User, nullable only where the actor is the system or an unauthenticated candidate.

**Versioning strategy.** Three distinct patterns are used deliberately; mixing them was a defect in SDD 1.0.

| Pattern | Used for | Rule |
|---|---|---|
| **Inline copy** | JD content on Job Posting | The text is copied onto the consuming record. Immune to upstream change by construction. |
| **Immutable version rows + FK snapshot** | Pipeline Template, CTC Rule Set, Approval Band Policy, Notification Template, Model Version | A version row is **never updated after activation**. Edits create a new row. Consumers store the version FK. Enforced by trigger, not convention. |
| **Entity versioning** | Offer | Multiple rows per parent; `version` increments; latest non-superseded row is current. |

**Enum handling.** All enums are stored as text with a check constraint, not integers — audit exports must be readable a decade out.

**Soft delete.** Not used. Records reach terminal states or are purged by the retention job. Nothing is hidden by a flag.

**Money.** `numeric(14,2)`, INR, with `currency` retained as a column for future multi-currency entities.

---

## Section 1. Data Model & ERD

42 entities across 11 domains. Entities marked **[NEW]** did not exist in SDD 1.0; **[REVISED]** existed but changed materially.

### A. Tenancy & Configuration

#### A1. Organization / Entity

| Field | Type | Notes |
|---|---|---|
| `name` | string | |
| `legal_entity_name`, `gstin`, `registered_address` | string / structured | Appears on offer letters |
| `active_ctc_rule_set_id` | FK → CTC Rule Set | Replaces the old inline JSON |
| `active_approval_band_policy_id` | FK → Approval Band Policy | Replaces the old inline JSON |
| `default_pipeline_template_id` | FK → Pipeline Template | Fallback when Configurable Pipelines flag is off |
| `document_phase_ordering` | enum(PreOfferLetter, PostSignature) | Default `PreOfferLetter`. Per organisation, never per candidate |
| `calendar_provider` | enum(GoogleWorkspace, MicrosoftOutlook) | Both adapters built |
| `bgv_incomplete_at_joining_policy` | enum(ConditionalProceed, Hold) | Module 8 |
| `talent_pool_consent_validity_months` | int | Default 24 |
| `retention_months_non_joiner` | int | Default 12. Applies to rejected, withdrawn, declined and no-show candidates |
| `employment_handoff_window_days` | int | Default 90. Days after `Onboarded` before the employment record pack is exported and purged |
| `employment_handoff_target` | enum(HRMSExport, ManualDownload, AdminHold) | `AdminHold` is the exception path for customers with no HRMS |
| `recording_retention_months` | int | Must not exceed the consent disclosure text |
| `timezone` | string | Default `Asia/Kolkata` |

#### A2. CTC Rule Set **[NEW]** *(immutable version rows)*

| Field | Type | Notes |
|---|---|---|
| `version` | int | Unique per organisation |
| `components` | JSON, ordered | Ordered component definitions — see Section 4.1 for the schema |
| `status` | enum(Draft, Active, Retired) | Only one Active per organisation |
| `effective_from`, `effective_to` | date | |
| `activated_by`, `activated_at` | | |

Rationale: an offer letter is a legal instrument. If the rule set that produced a breakdown can be edited in place, a past offer cannot be reproduced in a dispute or an audit.

#### A3. Approval Band Policy **[NEW]** *(immutable version rows)*

| Field | Type | Notes |
|---|---|---|
| `version` | int | |
| `bands` | JSON | designation → max CTC before approval is required |
| `escalation_approver_capability` | string | Which capability the approver must hold |
| `status`, `effective_from`, `effective_to` | | |

The **evaluated threshold value is stamped onto Negotiation Log** at check time, not merely referenced — so a band check remains explicable even if the policy is later retired.

#### A4. Feature Flag **[REVISED]**

| Field | Type | Notes |
|---|---|---|
| `flag_key` | enum(TalentPool, AICopilot, ConfigurablePipelines, InternalNotes, CrossRoundFeedbackVisibility) | `CrossRoundFeedbackVisibility` added — the permission matrix marks Interviewer feedback visibility "Configurable" with nothing backing it |
| `enabled` | bool | |
| `changed_by`, `changed_at`, `change_reason` | | Flags gate compliance-relevant behaviour (AI Copilot); who toggled matters |

Flag semantics are behavioural only — never silent data destruction. See Section 4.5.

#### A5. SLA Policy **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `sla_type` | enum(JobApproval, InterviewFeedback, OfferApproval, CTCApproval, DocumentSubmission, BGVTurnaround) | |
| `duration_business_days` | int | Defaults: job approval 2, feedback 3 |
| `reminder_offsets` | int[] | e.g. document reminders at day 2, 5, 8 |
| `escalation_target` | enum(RoleCapability, NamedUser, HRQueue) | |
| `escalation_after_misses` | int | Default 2 for feedback |

One service, one table. SDD 1.0 referenced a "shared SLA/escalation service" with no data behind it.

### B. Identity & Access

#### B1. User **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `email`, `full_name`, `employee_code` | string | |
| `status` | enum(Active, Suspended, Offboarded) | |
| `external_idp_subject` | string | SSO subject claim (SAML NameID / OIDC `sub`) |
| `idp_config_id` | FK → Identity Provider Config | |
| `last_login_at` | | |

Users are internal only. Candidates are **not** Users — they hold no account, by design (V3.2 Candidate Experience).

#### B2. Role **[NEW]** and B3. Role Assignment **[NEW]**

**Role:** `role_key` enum(HR, HiringManager, Interviewer, Employee, Admin), `capabilities` string[].

**Role Assignment:** `user_id`, `role_id`, `scope_type` enum(Organization, Department, JobPosting), `scope_id`, `granted_by`, `granted_at`, `expires_at` (nullable).

Scoping matters: a Hiring Manager's Talent Pool access is limited to "own reqs," which is a scoped grant, not a global one.

**Capabilities** are the enforcement primitive; roles are bundles of them. This resolves **S4** — `approve_ctc_above_band` can be granted to a Finance stakeholder without inventing a Finance role, and `view_unmasked_pii` can be granted to designated HR only, as the matrix requires.

Capability list (initial): `create_jd`, `approve_job`, `edit_jd_templates`, `add_resume_manually`, `shortlist`, `schedule_interview`, `submit_feedback`, `view_all_round_feedback`, `decide_round`, `mark_negotiation_complete`, `approve_ctc_above_band`, `generate_offer`, `approve_offer`, `verify_documents`, `view_unmasked_pii`, `resolve_bgv_flag`, `configure_ctc_rules`, `manage_notes`, `view_ai_copilot`, `search_talent_pool`, `reactivate_candidate`, `merge_profiles`, `configure_pipelines`, `manage_feature_flags`, `view_audit_log_full`, `export_pii`, `delegate_approval`, `manage_roles`, `submit_documents_on_behalf`.

> `submit_documents_on_behalf` is new and not in the V3.2 matrix. There is an HR path to add a resume manually but none to handle a candidate who emails documents directly. This will happen on day one.

#### B4. Identity Provider Config **[NEW]**

`protocol` enum(SAML2, OIDC), `metadata_url`, `certificate_ref`, `attribute_mapping` JSON, `default_role_id`, `jit_provisioning_enabled` bool.

#### B5. Candidate Portal Token **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `application_id` | FK | Scope is a single Application — never a profile |
| `token_hash` | string | Hash only. The raw token is never stored |
| `purpose` | enum(StatusView, DocumentSubmission, OfferReview, RescheduleRequest, ConsentManagement, Withdrawal) | Narrow scope per link |
| `issued_at`, `expires_at` | timestamptz | |
| `single_use` | bool | True for offer signing and consent revocation |
| `consumed_at` | timestamptz, nullable | |
| `revoked_at`, `revoked_reason` | nullable | Revoked on application terminal states |
| `issued_for_event_id` | FK → Domain Event | Which notification generated this link |
| `last_used_ip`, `use_count` | | Abuse detection |

This is the platform's entire candidate-facing authentication boundary and it was unmodelled. Constraints: expiry is mandatory; a token for a terminal-state Application is rejected at validation regardless of `expires_at`.

#### B6. Approval Delegation **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `delegator_user_id`, `delegate_user_id` | FK → User | |
| `capability` | string | Delegation is per-capability, not blanket |
| `valid_from`, `valid_to` | date | Module 1: "a named alternate for a date range" |
| `reason` | text | |
| `revoked_at` | nullable | |

Constraint: a delegate must independently hold the capability, or the delegation is rejected at creation. Delegation cannot manufacture authority.

### C. Approvals (shared engine)

#### C1. Approval Request **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `approval_type` | enum(JobPublish, CTCAboveBand, OfferLetter) | Extensible |
| `entity_type`, `entity_id` | polymorphic | Job Posting / Negotiation Log / Offer |
| `application_id` | FK, nullable | Denormalised for the approvals queue |
| `required_capability` | string | |
| `assigned_to_user_id` | FK → User | Resolved through active delegations at assignment time |
| `resolved_via_delegation_id` | FK, nullable | Audit trail for who actually holds it |
| `status` | enum(Pending, Approved, Rejected, Escalated, Withdrawn, Expired) | |
| `sla_policy_id` | FK → SLA Policy | |
| `due_at` | timestamptz | Computed in business days, org timezone |
| `escalated_at`, `escalated_to_user_id` | nullable | |
| `context_snapshot` | JSON | What the approver was shown at request time |

#### C2. Approval Action **[NEW]**

`approval_request_id` FK, `actor_id`, `action` enum(Approved, Rejected, Reassigned, Escalated, CommentAdded, Reminded), `comment` text, `acted_at`. One row per event — the full trail, since a request may escalate more than once.

**Why this exists:** three modules (1, 5, 7) each had a nullable `approver_id` column. Escalation after a configurable window, delegation across a date range, a unified pending-approvals dashboard, and the "Delegate own approval authority" permission row are all unbuildable against nullable columns. This is the largest single change in SDD 2.0.

### D. Job & JD

#### D1. JD Template

| Field | Type | Notes |
|---|---|---|
| `type` | enum(About, Perks) | |
| `content` | text | |
| `version` | int | Immutable once active |
| `is_active` | bool | |
| `created_by` | FK → User | |

#### D2. Job Posting **[REVISED]**

| Field | Type | Notes |
|---|---|---|
| `designation`, `department` | string | |
| `job_family` | string | Resolves the Pipeline Template |
| `jd_content`, `jd_version` | text, int | Inline copy — snapshot by construction |
| `jd_template_ids` | UUID[] | Which template versions were composed |
| `status` | enum(Draft, PendingApproval, Published, OnHold, Closed, Cancelled) | |
| `approval_request_id` | FK, nullable | **Replaces** `approver_id` / `approved_at` |
| `pipeline_template_version_id` | FK | Active template at publish |
| `openings_count`, `filled_count` | int | |
| `application_form_slug` | string | Embeds `job_id`; used for the public form |
| `published_at`, `closed_at` | | |

`board_posting_status` JSON removed — see D3.

#### D3. Board Posting **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `job_posting_id` | FK | |
| `board` | enum(CareerPortal, Naukri, LinkedIn) | |
| `integration_mode` | enum(API, Manual) | Naukri = API; LinkedIn = Manual at launch |
| `status` | enum(NotPosted, Queued, Posted, Failed, Expired, Removed) | |
| `external_posting_id`, `external_url` | string, nullable | |
| `posted_by_user_id`, `posted_at` | | **Manual attestation** — for LinkedIn there is no API to report status |
| `last_sync_at`, `failure_reason`, `retry_count` | | API mode only |

A single JSON blob could not represent a human attesting that they pasted a job into LinkedIn. That is the actual launch behaviour, so it needs a real record.

### E. Candidate & Application

#### E1. Candidate Profile **[REVISED]**

Canonical person record — one per human.

| Field | Type | Notes |
|---|---|---|
| `full_name`, `email`, `phone` | string | Plus `email_normalized`, `phone_e164` for fingerprinting |
| `resume_fingerprint_hash` | string | Dedup key |
| `parsed_skills`, `parsed_experience`, `parsed_education` | JSON | Parsed once, person-level |
| `address` | structured, nullable | **Source of truth.** Populated from the Module 6 Address document; Dispatch Record holds a point-in-time snapshot |
| `address_confirmed_at` | timestamptz, nullable | Drives the "stale address" re-confirmation in Module 9 |
| `talent_pool_status` | enum(None, Eligible, Active) | |
| `talent_pool_consent_id` | FK → Consent Log, nullable | |
| `merged_into_profile_id` | FK → self, nullable | Merge chain |
| `retention_status` | enum(Active, PurgeScheduled, Purged) | **[NEW]** |
| `purge_scheduled_for`, `purged_at` | date, timestamptz, nullable | **[NEW]** |

Address appeared in three places in SDD 1.0 with no stated authority. The rule is now: **Candidate Profile is canonical, Document Submission is the evidence, Dispatch Record is the snapshot.**

#### E2. Application **[REVISED]**

Candidate Profile × Job Posting — the core pipeline record and the hub entity.

| Field | Type | Notes |
|---|---|---|
| `candidate_profile_id`, `job_posting_id` | FK | |
| `source` | enum(applied, referred, hr_added) | |
| `ai_score`, `ai_score_rationale` | int, text, nullable | Advisory only |
| `status` | enum | Unified lifecycle value — Section 1.12 |
| `substatus_reason` | string, nullable | e.g. parse failure detail |
| `rejection_reason_code` | enum, nullable | Required on Rejected |
| `pipeline_template_version_id` | FK, snapshot | Locked at shortlist |
| `document_phase_ordering` | enum(PreOfferLetter, PostSignature) | **Snapshotted from Organization at shortlist** — an org-level config change must not reorder a live candidate's journey |
| `parallel_pipeline_ack_by`, `parallel_pipeline_ack_at` | nullable | Module 4 requires "an explicit decision"; there was nowhere to record that it was made |
| `withdrawn_at`, `withdrawal_reason` | nullable | |
| `current_round_number` | int | Read-model convenience |
| `stage_entered_at` | timestamptz | Powers funnel and time-in-stage analytics |

**Constraint:** partial unique index on `(candidate_profile_id, job_posting_id)` where status is not terminal. This is what enforces the merge rule "blocked if both profiles hold live Applications on the same job."

#### E3. Referral

`application_id` FK (1:1, only when `source=referred`), `referrer_employee_id` FK → User, `referral_bonus_flag` bool, `referrer_relationship` text, `milestones_notified` JSON.

Milestone tracking is explicit because the referrer notification set is **deliberately narrow** — received, shortlisted, outcome. Never feedback, scores, or compensation. Encoding it as data rather than as notification-service logic makes the restriction reviewable.

#### E4. Merge Log

`source_profile_id`, `target_profile_id` FK → Candidate Profile, `merged_by`, `merged_at`, `fields_reconciled` JSON (kept/discarded values per conflicting field), `consent_resolution` JSON (which consent won, per type).

**Merge semantics, stated explicitly** (SDD 1.0 left this ambiguous, and it will produce bugs otherwise):
- Applications, Documents and Consents **repoint** to the surviving profile.
- Audit Log entries **do not** — they retain original profile IDs and resolve through the merge chain at read time. V3.2: "historical audit entries are never rewritten."
- The more restrictive consent wins, per consent type, evaluated on effective state (a revoked consent beats an active one).

### F. Screening & Interview

#### F1. Screening Call Record **[REVISED — V3.2 two-layer split]**

| Field | Type | Notes |
|---|---|---|
| `application_id` | FK | |
| `telephony_call_id` | string | **Exotel (Layer 1)** — V3.2 required field |
| `voice_ai_session_id` | string, nullable | **Layer 2 vendor** — V3.2 required field |
| `voice_ai_vendor`, `voice_ai_model_version` | string | Set post-pilot; recorded per call so pilot comparisons remain attributable |
| `recording_ref` | encrypted pointer, nullable | Transport-layer recording |
| `recording_retention_until` | date | Retention obligation lives with the recording, not in policy prose |
| `recording_consent_id` | FK → Consent Log, nullable | Null means no recording may be retained |
| `pre_consent_segment_discarded` | bool | Resolves **S7** |
| `call_status` | enum(Completed, NoAnswer, Busy, Rescheduled, Escalated, DNDBlocked, DialFailed, ConsentDeclined, AbandonedByCandidate) | Extended — the SDD 1.0 enum had no representation for a DND-scrubbed number or a declined recording consent |
| `transcript_summary`, `transcript_ref` | text, pointer | |
| `preferred_slots` | JSON | Structured outcome from Layer 2 |
| `outcome_confidence` | decimal, nullable | Layer 2 self-reported; feeds pilot evaluation |

**Neither layer owns candidate state.** The Application state machine does. Both layers write to this record; only the platform advances the Application.

#### F2. Call Attempt **[NEW]**

`screening_call_record_id` FK, `attempt_number` int, `attempted_at`, `time_of_day_bucket` enum(Morning, Afternoon, Evening), `telephony_call_id`, `outcome`, `dnd_check_result` enum(Clear, Blocked, Unavailable), `duration_seconds`.

SDD 1.0 held attempts as `attempt_number` + a timestamp array. The retry policy is "3 attempts across **different times of day** over 2 days" — enforcing that requires per-attempt structure, and DND scrubbing is a per-dial regulatory check that must be evidenced per attempt.

#### F3. Interview Round **[REVISED]**

| Field | Type | Notes |
|---|---|---|
| `application_id` | FK | |
| `round_number`, `round_type` | int, string | From the snapshotted Pipeline Template |
| `scheduled_at`, `duration_minutes`, `location_or_link` | | |
| `status` | enum(Scheduled, Rescheduled, InProgress, Completed, FeedbackPending, FeedbackComplete, Cancelled, NoShow) | **Corrected** — `InterviewRescheduled` and `InterviewCancelled` events existed with no matching states |
| `round_decision` | enum(Reject, NextRound, OfferRecommended), nullable | **[NEW]** — the Hiring Manager's round decision had no home; only per-interviewer recommendations existed |
| `round_decision_by`, `round_decision_at` | | |
| `rejection_reason_code` | enum, nullable | Required when decision is Reject |
| `calendar_event_id`, `calendar_provider` | ref | |
| `reschedule_count` | int | |
| `feedback_due_at` | timestamptz | Derived from SLA Policy |

#### F4. Interviewer Assignment **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `interview_round_id`, `interviewer_user_id` | FK | |
| `is_panel_lead` | bool | The lead decides the round; others advise |
| `invitation_status` | enum(Invited, Accepted, Declined, Tentative) | From the calendar adapter |
| `feedback_status` | enum(Pending, Submitted, Waived) | |
| `feedback_due_at` | timestamptz | **Per interviewer** — the SLA is personal, not per round |
| `reminder_sent_count`, `escalated_at` | | |
| `reschedule_requested_at`, `reschedule_reason` | nullable | The matrix grants Interviewers "Request interview reschedule" with nothing to write to |

An array of UUIDs on Interview Round could carry none of this. Panel support, per-person SLA escalation, and the Interviewer's minimal-privilege scope ("own round only") all depend on this row existing.

#### F5. Feedback **[REVISED]**

`interviewer_assignment_id` FK (**changed** — was round + interviewer, which allowed orphan feedback from an unassigned user), `rating` int, `competency_ratings` JSON, `notes` text, `decision_recommendation` enum(Strong Yes, Yes, No, Strong No), `submitted_at`, `is_late` bool.

**Constraint:** unique on `interviewer_assignment_id`. One feedback per interviewer per round; panel independence is enforced by not exposing peer feedback before submission when `CrossRoundFeedbackVisibility` is off.

### G. Offer & Compensation

#### G1. Negotiation Log **[REVISED]**

| Field | Type | Notes |
|---|---|---|
| `application_id` | FK | 1:1 |
| `current_ctc`, `expected_ctc` | numeric | Was missing; needed for analytics and for the band conversation |
| `rounds` | JSON | Back-and-forth log |
| `final_ctc` | numeric | |
| `approval_band_policy_version_id` | FK | **[NEW]** Which policy was applied |
| `threshold_value_applied` | numeric | **[NEW]** The actual band figure, stamped at check time |
| `band_check_result` | enum(WithinBand, AboveBand) | |
| `approval_request_id` | FK, nullable | **Replaces** `approver_id`/`approved_at`. Present only when AboveBand |
| `completed_by`, `completed_at` | | |

#### G2. Offer **[REVISED]** *(entity-versioned)*

| Field | Type | Notes |
|---|---|---|
| `application_id`, `version` | FK, int | |
| `ctc_rule_set_version_id` | FK | **[NEW]** Reproducibility of the breakdown |
| `ctc_breakdown` | JSON | Output of the CTC calculator |
| `status` | enum(Drafted, PendingApproval, Approved, Sent, Viewed, Signed, Declined, Expired, Revoked, Superseded) | **Corrected**: `Declined` added (V3.2 makes it a distinct candidate-initiated outcome); `Reissued` replaced by `Superseded` on the prior row — reissue creates a *new version*, it is not a state of the old one |
| `decline_reason` | text, nullable | V3.2: "captured with an optional reason" |
| `approval_request_id` | FK, nullable | |
| `esign_vendor_ref_id` | string | Digio document reference |
| `esign_consent_id` | FK → Consent Log | |
| `signed_document_ref` | encrypted pointer | |
| `sent_at`, `expiry_date` | | |
| `expiry_reminders_sent` | JSON[] | **Corrected** from a bool — V3.2 specifies reminders, plural |
| `proposed_joining_date` | date | **[NEW]** Appears in the letter, pre-signature |
| `confirmed_joining_date` | date, nullable | Entered by HR post-signature. Resolves **S3** |
| `supersedes_offer_id` | FK → self, nullable | Explicit reissue chain |

Prior versions are retained in full for audit — never deleted, never edited.

### H. Documents, BGV & Dispatch

#### H1. Document Submission **[REVISED]**

| Field | Type | Notes |
|---|---|---|
| `application_id` | FK | |
| `document_type` | enum(Aadhar, PAN, Marksheet10, Marksheet12, MarksheetGraduation, MarksheetPostGraduation, EmploymentProof, EPFO, AddressProof, Photograph, Other) | **Expanded** — a single `Marksheet` value with one row per type made multiple marksheets unrepresentable |
| `sequence` | int | Multiple employment proofs across prior employers |
| `is_mandatory` | bool | Driven by org config |
| `status` | enum(Pending, Submitted, Rejected, Resubmitted, Verified) | |
| `file_ref` | encrypted pointer | |
| `file_hash`, `file_size`, `mime_type` | | Integrity + upload validation |
| `rejection_reason` | text, nullable | Drives the targeted resubmission request |
| `reminder_count`, `last_reminder_at` | | Day 2 / 5 / 8 |
| `verified_by`, `verified_at` | FK → User | **[NEW]** Was only recoverable from Audit Log |
| `retention_until` | date | |

**Constraint:** unique on `(application_id, document_type, sequence)`. Rejecting one document must not reset the rest of the form — enforced by row-level status, not form-level state.

#### H2. BGV Record **[REVISED]**

| Field | Type | Notes |
|---|---|---|
| `application_id` | FK | 1:1 |
| `consent_id` | FK → Consent Log | **[NEW]** BGV cannot initiate without it — resolves **G7** |
| `vendor` | enum(AuthBridge, SpringVerify) | Both, during the parallel pilot |
| `vendor_ref_id` | string | |
| `checks` | JSON | employment / criminal / education, status and turnaround each |
| `initiated_at`, `completed_at` | | **[NEW]** Turnaround is an explicit pilot comparison criterion and was unmeasurable |
| `overall_status` | enum(Initiated, InProgress, Clear, Flagged, Cancelled, VendorError) | |
| `report_ref` | encrypted pointer | **[NEW]** The actual report document |
| `flag_details` | JSON | Which check, what discrepancy |
| `flag_resolution` | enum(Proceed, Rescind, ConditionalProceed), nullable | |
| `resolution_notes`, `resolved_by`, `resolved_at` | | |
| `conditional_deadline` | date, nullable | Hard follow-up deadline |
| `is_pilot_parallel_run` | bool | Marks records created for the 20–30 candidate vendor comparison |

#### H3. Kit Catalogue Item **[NEW]**

Mirrors the existing Gifteko catalogue rather than inventing a structure. Categories and tiers are taken from how the business already segments its products.

| Field | Type | Notes |
|---|---|---|
| `sku`, `name`, `description` | string | |
| `category` | enum(WelcomeKit, Stationery, Drinkware, PremiumHamper, OfficeEssentials, TravelAndTech, Apparel) | Extensible — sourced from the live catalogue |
| `tier` | enum(Basic, Custom, Enterprise) | Existing Gifteko tiering |
| `customisable` | bool | Whether branding can be applied |
| `customisation_methods` | enum[](Embossing, LaserEngraving, Print, PackagingInsert) | |
| `lead_time_days_standard`, `lead_time_days_customised` | int | Customised items carry a materially longer lead time |
| `image_refs` | array | |
| `is_active` | bool | |

**No price field.** Gifteko prices by enquiry and quote, deliberately — the catalogue carries no public pricing. The platform therefore never displays or calculates kit cost; commercials are settled between the customer and Gifteko outside this system. This keeps a pricing engine out of scope entirely.

#### H4. Organization Kit Profile **[NEW]**

Per-customer branding setup and readiness. This is the entity whose absence would have caused the first real dispatch to fail.

| Field | Type | Notes |
|---|---|---|
| `organization_id` | FK | 1:1 |
| `brand_asset_refs` | array | Logo files, brand guideline document |
| `brand_colour_spec`, `customisation_notes` | | Matched to the customer's brand identity guidelines |
| `proof_ref`, `proof_approved_by`, `proof_approved_at` | | Artwork proof approval — happens **once per customer**, not per hire |
| `readiness_status` | enum(NotStarted, AssetsRequested, ProofPending, ProofApproved, StockReady) | |
| `readiness_blockers` | text | Surfaced to HR and to the Gifteko account manager |
| `fulfilment_mode` | enum(BufferStock, BatchedWeekly, DropShipPerHire) | See §3.8 |
| `buffer_stock_level`, `reorder_threshold` | int, nullable | `BufferStock` mode only |
| `account_manager_ref` | | Gifteko already assigns account managers; the platform should know who |

#### H5. Client Kit **[NEW]**

A configured kit for a specific customer — catalogue items plus branding, assigned to who receives it.

| Field | Type | Notes |
|---|---|---|
| `organization_id` | FK | |
| `name` | string | e.g. "Engineering Welcome Kit" |
| `catalogue_item_ids` | UUID[] | A kit is a bundle, not a single item |
| `applies_to` | JSON | Job family, designation band, or default. Mirrors the Pipeline Template pattern |
| `version`, `is_active` | | Immutable once active, same as other config entities |

#### H6. Dispatch Record **[REVISED]**

| Field | Type | Notes |
|---|---|---|
| `application_id` | FK | 1:1 |
| `gifteko_ref_id` | string | |
| `client_kit_id` | FK → Client Kit | **Replaces** the `kit_type` string |
| `client_kit_version` | int | Snapshot — a kit redesign must not rewrite a past dispatch |
| `fulfilment_mode` | enum | Snapshotted from the Kit Profile |
| `batch_id` | string, nullable | Set under `BatchedWeekly` |
| `address_snapshot` | structured | Captured at dispatch |
| `address_confirmed_at` | timestamptz | Module 9 re-confirms stale addresses |
| `status` | enum(Triggered, AwaitingKitReadiness, Queued, Dispatched, InTransit, Delivered, Failed, Returned) | `AwaitingKitReadiness` is new and necessary — see §3.8 |
| `tracking_reference`, `carrier` | string, nullable | |
| `retry_count`, `last_failure_reason`, `hr_alerted_at` | | |

### I. Consent, Communications & Audit

#### I1. Consent Log **[REVISED — now stateful]**

| Field | Type | Notes |
|---|---|---|
| `candidate_profile_id` | FK | Many per profile |
| `application_id` | FK, nullable | Some consents are application-scoped, some person-scoped |
| `consent_type` | enum(AICallRecording, ESignature, TalentPoolRetention, **BackgroundVerification**) | BGV consent added |
| `status` | enum(Granted, Revoked, Expired, Superseded) | **[NEW]** — SDD 1.0 modelled grants only |
| `granted_at`, `consent_method` | | enum(PortalCheckbox, VoiceAffirmation, ESignFlow) |
| `consent_text_version` | string | Which disclosure text was shown |
| `expires_at` | timestamptz, nullable | **[NEW]** Talent pool default 24 months |
| `revoked_at`, `revocation_method` | nullable | **[NEW]** |
| `superseded_by_consent_id` | FK → self, nullable | Re-ask on expiry creates a new row |
| `ip_address`, `user_agent` | nullable | Evidentiary |

Three V3.2 requirements were unbuildable without this: revocation at any time with immediate pool removal, the 24-month validity re-ask cycle, and "more restrictive consent wins" at merge — which needs effective state, not a grant record.

#### I2. Notification Template **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `template_key`, `version` | string, int | Immutable version rows |
| `channel` | enum(Email, Slack, SMS) | |
| `dlt_template_id`, `dlt_entity_id`, `dlt_registered_at` | string, date | **SMS only — mandatory.** Every Indian SMS must be attributable to a registered template |
| `dlt_approval_status` | enum(Pending, Approved, Rejected) | |
| `subject`, `body`, `variables` | | |
| `locale` | string | Regional-language support |

#### I3. Notification Log **[REVISED]**

| Field | Type | Notes |
|---|---|---|
| `recipient_type`, `recipient_ref` | enum(User, Candidate) + FK | |
| `channel` | enum(Email, Slack, SMS) | |
| `notification_template_version_id` | FK | **[NEW]** Regulatory attribution |
| `triggering_event_id` | FK → Domain Event | |
| `provider` | enum(SES, SendGrid, Exotel, Slack) | |
| `provider_message_id` | string | **[NEW]** Delivery reconciliation |
| `status` | enum(Queued, Sent, Delivered, Bounced, Failed, Suppressed) | |
| `failure_reason`, `retry_count` | | **[NEW]** |
| `portal_token_id` | FK, nullable | Which link was embedded |

#### I4. Audit Log

`actor_id`, `actor_role`, `actor_type` enum(User, Candidate, System), `action_type`, `entity_type`, `entity_id` (polymorphic), `before_state`, `after_state` JSON, `ip_address`, `session_id`, `timestamp`, `sequence_number` bigserial, `previous_hash`, `entry_hash`.

**Immutability mechanism** (SDD 1.0 required "immutably" without saying how): append-only table, `REVOKE UPDATE, DELETE` from all application roles, and a hash chain — each entry hashes its own content plus the previous entry's hash. Tampering breaks the chain verifiably. Verified nightly.

#### I5. Internal Note / Attachment

`application_id` FK, `author_id`, `author_role`, `note_text` text (nullable), `file_ref` pointer (nullable), `interview_round_id` FK nullable (scopes an Interviewer's "own round only" access), `visibility` enum(HROnly, HRAndHiringManager, AllInternal), `is_read_only` bool (set when the InternalNotes flag is off).

**Constraint:** exactly one of `note_text` or `file_ref`. Distinct from formal Document Submissions in retention, masking and access.

### J. Pipelines & AI

#### J1. Pipeline Template **[REVISED]**

`job_family` string, `version` int, `round_definitions` JSON ordered (round_type + sequence_number + default_duration + required_interviewer_capability), `status` enum(Draft, Active, Retired), `is_default` bool.

**Constraint — the one that makes the FK snapshot safe:** once `status = Active`, the row is immutable. Enforced by a database trigger. SDD 1.0 relied on an FK snapshot without guaranteeing the target could not change, which would have silently broken the promise that "a template change never retroactively rewrites a live candidate's pipeline."

#### J2. Model Version **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `purpose` | enum(JDGeneration, ResumeParsing, Scoring, Copilot, VoiceAI) | |
| `provider`, `model_identifier`, `endpoint_region` | string | `endpoint_region` is checked against the residency policy at call time |
| `prompt_version` | string | A prompt change is a model change for fairness purposes |
| `status` | enum(Candidate, Approved, Active, Retired) | |
| `activated_at`, `retired_at` | | |

#### J3. Fairness Review **[NEW]**

`model_version_id` FK, `review_type` enum(Fairness, Accuracy, Both), `outcome` enum(Approved, Rejected, ApprovedWithConditions), `reviewer_id` / `committee_name`, `reviewed_at`, `methodology_ref`, `findings` text, `conditions` text, `expires_at` nullable.

**The gate lives here, not on the summary.** V3.2: "sign-off attaches to a model version... New model version → fresh sign-off before outputs surface." SDD 1.0 put `fairness_reviewed bool` on each summary row, which meant activating a new model version required backfilling a boolean across every historical summary — and made it impossible to block a version's output at the version level.

#### J4. AI Copilot Summary **[REVISED]**

`application_id` FK, `model_version_id` FK (**replaces** the free-text `model_version` string), `summary_text`, `strengths[]`, `risks[]`, `suggested_questions[]`, `salary_fit_score`, `offer_confidence_score`, `input_snapshot_hash`, `generated_at`, `is_hidden` bool (set when the AICopilot flag is off — records retained for audit).

`fairness_reviewed` removed. Visibility is resolved at read time: a summary surfaces only if its `model_version_id` has an Active Fairness Review with outcome Approved and no expiry passed.

### K. Retention & Analytics

#### K1. Application Analytics Record **[NEW]**

| Field | Type | Notes |
|---|---|---|
| `original_application_id` | UUID | Retained as an identifier, no FK — the Application may be gone |
| `job_posting_id`, `designation`, `department`, `job_family` | | |
| `source` | enum | |
| `stage_reached`, `final_outcome`, `rejection_reason_code` | | |
| `applied_at`, `stage_timestamps` | JSON | Funnel and time-to-hire analytics |
| `rounds_completed`, `ai_score_band` | int, enum | **Band, not the raw score** — a precise score plus a job is re-identifying |
| `created_by_purge_run_id` | FK → Retention Job Run | |

Contains **no** name, contact, document, resume, transcript, or free text. This is what V3.2 cross-cutting requirement 6 promised — "Analytics survive; PII does not" — and it had no entity. It cannot be implemented as nulled-out columns on Application, because Application carries an FK to Candidate Profile.

#### K2. Retention Job Run **[NEW]**

`run_started_at`, `run_completed_at`, `profiles_evaluated`, `profiles_purged`, `applications_anonymized`, `documents_destroyed`, `recordings_destroyed`, `errors` JSON, `dry_run` bool.

Purge is destructive and irreversible. It runs in dry-run mode first in every environment, and each run is itself an auditable record. Emits `RetentionPurgeExecuted`.

### 1.12 Unified Candidate Lifecycle State Machine **[REVISED]**

```
Draft(job) → PendingApproval(job) → Published(job)
  → Applied → Parsed → Scored → Shortlisted
        ├─ Parse-Failed ──▶ (manual parse | HR re-upload) ──▶ Parsed
        ├─ Score-Failed ──▶ (retry | proceed unscored — scoring is advisory) ──▶ Shortlisted
        └─ Duplicate-Detected ──▶ (Merged ──▶ existing Application | Confirmed-Distinct ──▶ Parsed)

  → Screening [manual at launch; automated behind AIScreening flag] → Screened
        └─ Screening-Unreachable ──▶ HR manual outreach ──▶ (Screened | Rejected)
           [reached after 3 attempts, or immediately on DNDBlocked / ConsentDeclined]

  → Round[N]: Scheduled → Completed → FeedbackSubmitted
        → (Next Round | Offer-Recommended | Rejected)
        └─ Cancelled / No-Show ──▶ (Rescheduled | Rejected)

  → Offer-Recommended → Negotiation → (CTC-Pending-Approval →) Negotiation-Complete

  ── Branch A: document_phase_ordering = PreOfferLetter (default) ──
  → Documents-Requested → Documents-Partial → Documents-Submitted → Documents-Verified
  → Offer-Letter-Drafted → …

  ── Branch B: document_phase_ordering = PostSignature ──
  → Aadhaar-Capture  [minimal capture — Aadhaar eSign prerequisite, resolves S1]
  → Offer-Letter-Drafted → …
     …after Offer-Signed:
  → Documents-Requested → … → Documents-Verified → BGV-Initiated

  → Offer-Letter-Pending-Approval → Offer-Letter-Approved → Offer-Letter-Sent
  → (Offer-Signed | Offer-Declined | Offer-Expired)
     Offer-Expired → (Revoked | Reissued ──▶ back to Offer-Letter-Drafted, new version)
  → Joining-Date-Confirmed
  → BGV-Initiated → BGV-In-Progress
     → (BGV-Clear | BGV-Flagged → Flag-Under-Review → (Proceed | Conditional-Proceed | Rescind))
     → BGV-Incomplete-At-Joining ──▶ org policy ──▶ (Conditional-Proceed | Hold)
  → Onboarding-Kit-Triggered → Kit-Dispatched → Kit-Delivered
     └─ Kit-Dispatch-Failed ──▶ retry ──▶ (Kit-Dispatched | HR-Intervention)
  → (Onboarded | Joining-No-Show)
```

**Global transitions**, available from any non-terminal state: `Withdrawn` (candidate-initiated), `Rejected` (reason code required), `On-Hold` (inherited from the Job Posting).

**Terminal states:** Rejected → if consented → Talent-Pool · Withdrawn · Offer-Declined · Rescinded · Joining-No-Show · Onboarded.

**Changes from V3.2's diagram:**
- **Async failure states added** (`Parse-Failed`, `Score-Failed`, `Screening-Unreachable`). Parsing runs an LLM over candidate-supplied files; some fraction will fail, and without a state those applications become invisible.
- **`Duplicate-Detected` given a state.** The event existed with no corresponding application status, leaving the outcome of dedup undefined.
- **Branch B added** for inverted document ordering. V3.2 permits the configuration but diagrams only one path.
- **`BGV-Incomplete-At-Joining` made explicit** — Module 8 describes the policy decision but the machine had no state for it.

### 1.13 Key constraints & indexes

| Constraint | Purpose |
|---|---|
| Partial unique `(candidate_profile_id, job_posting_id)` where status not terminal | Enforces the merge block rule and prevents duplicate live applications |
| Unique `(application_id, document_type, sequence)` | One row per document instance |
| Unique `interviewer_assignment_id` on Feedback | One feedback per interviewer per round |
| Unique `(organization_id, version)` on all versioned config entities | |
| Check: exactly one Active CTC Rule Set / Approval Band Policy / Pipeline Template per scope | |
| Check: `note_text IS NOT NULL XOR file_ref IS NOT NULL` on Internal Note | |
| Trigger: reject UPDATE on Pipeline Template / CTC Rule Set / Notification Template where status = Active | Makes FK snapshots trustworthy |
| Trigger: reject UPDATE/DELETE on Audit Log | Immutability |
| FK: BGV Record requires a Granted, unexpired `consent_id` | Consent gate enforced in the schema, not only in code |
| Index: `(organization_id, status, stage_entered_at)` on Application | Dashboards and SLA sweeps |
| Index: `(assigned_to_user_id, status, due_at)` on Approval Request | The approvals queue |
| Index: `(organization_id, entity_type, entity_id, emitted_at)` on Domain Event | Timeline read-model |
| Index: `resume_fingerprint_hash`, `email_normalized`, `phone_e164` on Candidate Profile | Dedup on intake |

---

## Section 2. Domain Event Contracts

### 2.1 Envelope

Every event on the bus carries an identical envelope. SDD 1.0's Domain Event entity omitted `actor_id`, which broke the Candidate 360 Timeline — V3.2 defines it as a read-layer over the event stream requiring "timestamp, actor, source, and record links."

```json
{
  "event_id": "uuid-v7",
  "event_type": "OfferLetterSent",
  "schema_version": 1,
  "organization_id": "uuid",
  "entity_type": "Offer",
  "entity_id": "uuid",
  "application_id": "uuid | null",
  "candidate_profile_id": "uuid | null",
  "actor_id": "uuid | 'system' | 'candidate:{application_id}'",
  "actor_type": "User | System | Candidate | Vendor",
  "correlation_id": "uuid",
  "causation_id": "uuid | null",
  "sequence_number": 84213,
  "payload": { },
  "contains_pii": false,
  "emitted_at": "2026-08-22T09:14:22.481Z"
}
```

| Field | Why it is there |
|---|---|
| `schema_version` | Payload shapes will change. Consumers must be able to branch rather than break. |
| `sequence_number` | Monotonic per organisation. Gives consumers ordering and gap detection. |
| `correlation_id` / `causation_id` | A single HR action fans out to notifications, audit entries and timeline rows. Tracing needs the chain. |
| `application_id`, `candidate_profile_id` | Denormalised so the Timeline and Talent Pool read-models need no joins. |
| `contains_pii` | Drives redaction in logs, exports and the DLQ. |

**Payload rule:** payloads carry identifiers and state transitions, never PII. `DocumentSubmitted` carries `document_type` and `document_submission_id` — never the file or the Aadhaar number. This keeps the event store outside the purge path.

### 2.2 Delivery semantics

| Property | Decision |
|---|---|
| Guarantee | At-least-once. Exactly-once is not achievable across an external webhook boundary. |
| Consumer requirement | **Idempotent by `event_id`.** Every consumer keeps a processed-event table. |
| Ordering | Per `(organization_id, application_id)` partition key. Global ordering is not guaranteed and is not needed. |
| Retry | Exponential backoff, 5 attempts, jittered: 1s, 4s, 15s, 60s, 300s. |
| DLQ | Per-consumer dead-letter queue. Entries are alertable and replayable. **Age of oldest DLQ entry is a monitored SLO.** V3.2 requires resilience "applied to the event bus as well as external integrations" — SDD 1.0 had no mechanism for it. |
| Emission | Transactional outbox. The event row is written in the same transaction as the state change, then relayed. No dual-write. |
| Ordering across layers | Neither telephony nor voice AI owns state; both emit events that the platform reduces into Application transitions. |

### 2.3 Catalogue

V3.2's catalogue, plus additions. Additions are marked **[+]** and each is justified — none is speculative.

**Job lifecycle:** `JDDrafted`, `JDApprovalRequested`, `JDPublished`, `JDVersionUpdated`, `JobOnHold`, `JobClosed`, **[+]** `JobBoardPostingSucceeded`, **[+]** `JobBoardPostingFailed` *(Naukri API failures are silent otherwise)*, **[+]** `JobBoardManuallyPosted` *(LinkedIn attestation)*.

**Application intake:** `CandidateApplied`, `ReferralSubmitted`, `ApplicationParsed`, `ApplicationScored`, `DuplicateDetected`, **[+]** `ApplicationParseFailed`, **[+]** `ApplicationScoringFailed` *(async steps that will fail on real files)*, **[+]** `DuplicateResolved`.

**Screening & interviews:** `Shortlisted`, `ScreeningCallAttempted`, `ScreeningCompleted`, `ScreeningEscalated`, `InterviewScheduled`, `InterviewRescheduled`, `InterviewCancelled`, `InterviewCompleted`, `RoundFeedbackSubmitted`, `FeedbackSLABreached`, **[+]** `ScreeningCallBlockedByDND` *(regulatory evidence)*, **[+]** `ScreeningConsentDeclined`, **[+]** `InterviewerAssigned`, **[+]** `InterviewNoShow`, **[+]** `RoundDecisionRecorded`.

**Approvals [+ entire group]:** `ApprovalRequested`, `ApprovalGranted`, `ApprovalRejected`, `ApprovalDelegated`, `ApprovalEscalated`, `ApprovalReminderSent`, `ApprovalExpired`.

> V3.2 promised escalation after a configurable window across three modules but provided only `FeedbackSLABreached`. The escalation service had nothing to emit and the notification service nothing to subscribe to.

**Offer & compensation:** `OfferRecommended`, `NegotiationComplete`, `CTCApprovalRequested`, `CTCApprovalGranted`, `OfferLetterDrafted`, `OfferLetterApproved`, `OfferLetterSent`, `OfferSigned`, `OfferDeclined`, `OfferExpired`, `OfferRevoked`, `OfferReissued`, **[+]** `OfferViewed` *(portal open — expiry-nudge signal)*, **[+]** `OfferExpiryReminderSent` *(Offer carried a reminder field that Notification Log could not reference)*, **[+]** `JoiningDateConfirmed`.

**Documents:** `DocumentsRequested`, `DocumentSubmitted`, `DocumentRejected`, `DocumentsVerified`, `DocumentReminderSent`, **[+]** `DocumentsPartiallySubmitted`, **[+]** `DocumentSubmittedOnBehalf` *(HR-assisted path)*.

**BGV & onboarding:** `BGVInitiated`, `BGVCleared`, `BGVFlagged`, `BGVFlagResolved`, `KitDispatched`, `KitDelivered`, `KitDispatchFailed`, `Onboarded`, `JoiningNoShow`, **[+]** `BGVIncompleteAtJoining`, **[+]** `BGVVendorError`, **[+]** `DispatchAddressReconfirmed`.

**Candidate & data lifecycle:** `CandidateRejected`, `CandidateWithdrawn`, `ConsentGranted`, `ConsentRevoked`, `TalentPoolAdded`, `TalentPoolReactivated`, `ProfilesMerged`, `SensitiveDataAccessed`, `RetentionPurgeExecuted`, **[+]** `ConsentExpired`, **[+]** `ConsentReaskSent` *(the 24-month cycle)*, **[+]** `PIIExported` *(cross-cutting requirement 9 requires exports be logged; only reads were covered)*, **[+]** `PortalTokenIssued`, **[+]** `PortalTokenRevoked`, **[+]** `EmploymentRecordHandedOff`, **[+]** `EmploymentHandoffFailed`, **[+]** `KitDispatchAwaitingReadiness`, **[+]** `KitProfileReadinessChanged`.

**Platform [+ entire group]:** `FeatureFlagChanged`, `ModelVersionActivated`, `FairnessReviewRecorded`, `VendorWebhookVerificationFailed`.

### 2.4 Subscriber map

| Consumer | Subscribes to | Purpose |
|---|---|---|
| Candidate 360 Timeline | All events where `application_id` is present | Chronological read-model |
| Notification Service | Named subset with template bindings | Email / Slack / SMS |
| Audit Log Writer | All | Immutable record |
| Reporting / Analytics | State-transition events | Funnel, time-to-hire, SLA |
| Talent Pool Service | `CandidateRejected`, `ConsentGranted`, `ConsentRevoked`, `ConsentExpired` | Pool membership |
| SLA / Escalation Service | Approval and feedback events, plus a timer sweep | Reminders and escalation |
| Retention Service | `ConsentRevoked`, `ConsentExpired`, terminal application states | Purge scheduling |

---

## Section 3. Integration & API Contracts

**12 integrations** — Tira split into two, per V3.2. Eleven are contracted; one is pilot-pending.

### 3.0 Common integration pattern

Every external integration is built behind an internal adapter interface. Nothing calls a vendor SDK directly from module code. This is what makes the AuthBridge/SpringVerify parallel pilot possible "without rework," and it is the same property that will let the Voice AI vendor be swapped after the pilot.

| Concern | Standard |
|---|---|
| Outbound auth | Credentials in AWS Secrets Manager, rotated; never in config files |
| Inbound webhooks | Signature verification mandatory. Unverified payloads are rejected and emit `VendorWebhookVerificationFailed` |
| Idempotency | Vendor-supplied idempotency keys on writes; webhook handlers idempotent on vendor event ID |
| Retry | Exponential backoff, 5 attempts, then DLQ + HR/ops alert |
| Timeouts | 10s connect, 30s read; circuit breaker opens at 50% failures over 20 requests |
| Residency | Every adapter declares its data region; a call to a non-India endpoint for a PII-bearing payload fails closed |
| PII minimisation | Adapters send the minimum field set. Documented per integration below |

### 3.1 Digio — e-signature

| | |
|---|---|
| Direction | Outbound REST + inbound webhook |
| Mode | **Embedded** in the candidate portal — not a hosted handoff (this was decisive in vendor selection) |
| Method | Aadhaar eSign (UIDAI) |
| Key calls | Create signature request (document + signer) → return embed token → poll/receive status |
| Webhooks | `signature.completed`, `signature.declined`, `signature.expired` |
| PII sent | Candidate name, email, phone, Aadhaar reference, offer PDF |
| Writes to | Offer (`esign_vendor_ref_id`, `status`, `signed_document_ref`), Consent Log (`ESignature`) |
| Failure mode | Expiry is authoritative on our side, not Digio's — our `expiry_date` governs, so a vendor-side lapse cannot silently extend an offer |
| Fallback | Leegality — adapter interface identical |

### 3.2 AuthBridge — background verification

| | |
|---|---|
| Direction | Outbound REST + inbound webhook |
| Checks | Employment history, criminal record, education |
| Precondition | **`BackgroundVerification` consent Granted and unexpired.** Enforced at the adapter, not only in the module |
| PII sent | Name, DOB, address, employment history, education records, ID references |
| Webhooks | Per-check status, final report ready |
| Writes to | BGV Record (`checks`, `overall_status`, `report_ref`, `completed_at`) |
| Pilot | 20–30 candidates run in parallel against SpringVerify. Both adapters live; `is_pilot_parallel_run` marks the records. Comparison on report quality, turnaround (`initiated_at` → `completed_at`), and candidate experience |
| Regional coverage | Tier II/III regional-language document handling was the deciding factor — the pilot should deliberately include non-metro candidates or it will not test the thing that drove the selection |

### 3.3 Exotel — telephony (Layer 1) and SMS

**All regulatory obligations for automated outbound voice sit here.** An AI vendor cannot remediate a telephony vendor's compliance gap.

| Capability | Contract |
|---|---|
| Number provisioning | Indian DIDs, CLI presentation |
| DLT | Entity + template registration; **template ID attached to every SMS**, stored on Notification Template |
| DND scrubbing | **Before every dial.** Result recorded per Call Attempt as evidence, not just as a branch |
| Recording | Transport layer, with retention. Start deferred until after the consent affirmation where supported (**S7**) |
| Streaming | SIP / API media stream to Layer 2 |
| Dialer | Outbound capacity for retry windows |
| Webhooks | Call initiated, answered, completed, failed, recording available |
| Writes to | Screening Call Record, Call Attempt, Notification Log |
| Fallback | Ozonetel / Knowlarity |

### 3.4 Voice AI — Layer 2 **[DEFERRED — seam preserved]**

| | |
|---|---|
| Shortlist | Gnani, Sarvam, Bolna, SquadStack |
| Scope | ASR, LLM orchestration, TTS, conversation graph, structured outcome capture |
| Boundary | Receives an audio stream from Layer 1; returns structured output. **Owns no candidate state** |
| Contract we require | Session ID returned synchronously; structured outcome (preferred slots, transcript summary, confidence); webhook on session end |
| Writes to | Screening Call Record (`voice_ai_session_id`, `transcript_summary`, `preferred_slots`, `outcome_confidence`) |
| Reasoning | May call our India-region LLM endpoint rather than the vendor's own, where the vendor supports bring-your-own-endpoint — preferred, as it keeps inference inside our residency boundary |

**Deferred at launch (D-01).** HR performs screening manually, writing to the same Screening Call Record, emitting the same events, driving the same state transition. Layer 1 and Layer 2 remain distinct adapter interfaces behind an `AIScreening` feature flag; reintroduction — bought or built — is an adapter implementation plus a flag flip, with no change to the state machine, the record, or the candidate experience.

Manual screening also produces the transcript corpus that will make a later vendor evaluation meaningful: vendors get measured against real recorded calls rather than a demo script.

**Pilot design, for when this reopens.** Selection is by live phone-line measurement, not datasheet language support. The pilot must measure, per vendor, across at least three regional accents and both mobile and landline conditions: word error rate on the actual screening script, structured-slot extraction accuracy, barge-in handling, latency to first response, and candidate drop-off rate. **The adapter is built before the pilot**, so the pilot runs through production integration code and vendor swap is configuration.

**Residency gate — added:** Layer 2 processes raw candidate voice, arguably the most sensitive stream in the platform, and was omitted from V3.2's pre-contract requirement list (**S6**). Residency confirmation is a pilot gate, not a post-selection formality. A vendor that cannot process and store audio in India is disqualified regardless of accuracy scores.

### 3.5 Naukri — job board (API)

Paid RMS corporate subscription. Outbound post/update/close; inbound application pull or push depending on subscription tier. Writes to Board Posting. Failures emit `JobBoardPostingFailed` and alert HR — a silently unposted job is a hiring delay nobody notices.

### 3.6 LinkedIn — job board (manual)

No API at launch. Recruiter System Connect requires Talent Solutions Partner approval — months-long, low acceptance. The platform generates pre-filled copy plus the application link; HR posts manually and records the attestation (`posted_by_user_id`, `posted_at`, `external_url`). Modelled as `integration_mode = Manual` so the same entity serves both paths and a future API upgrade is a mode change, not a migration.

### 3.7 Career Portal — native

First-party. Public application form with `job_id` embedded, spam/bot protection (rate limiting + CAPTCHA + honeypot), file type and size validation, virus scan before storage.

### 3.8 Gifteko — onboarding kit **[FIRST-PARTY]**

Outbound dispatch trigger (name, address, joining date, kit type); inbound webhooks `KitDispatched` / `KitDelivered` / `KitDispatchFailed`. Retry with backoff; HR alerted on persistent failure. Address re-confirmed with the candidate if stale beyond the configured interval, then snapshotted.

**Gifteko is first-party — the group's own corporate gifting business, and the origin of this platform.** That changes three things against how a vendor integration is treated:

1. **No procurement path.** No contract negotiation, no vendor selection, no per-unit commercial tier. It ships when the module ships.
2. **Data agreement still required, but of a different kind.** If Gifteko and the platform sit in separate legal entities under common ownership, DPDP still requires an intra-group data-sharing agreement and a defined purpose — common ownership is not an exemption. If they are one legal entity, the transfer is internal and the candidate privacy notice simply has to describe dispatch as a purpose. **Confirm the legal structure**, because it determines which applies.
3. **Not deferrable.** Kit dispatch is not a post-offer convenience here; it is the capability the rest of the platform was built to extend. Treating it as an optional integration inverts the product.

**Keep the adapter boundary anyway.** Gifteko becomes the default implementation of a `KitDispatchProvider` interface rather than the only one. This costs nothing now and preserves the ability to serve a customer who wants their own gifting supplier — a plausible enterprise ask that would otherwise require unpicking a hard-wired integration. With separate legal entities, the interface is also the legal boundary, which makes the minimal payload a compliance property rather than just good hygiene.

#### Three operational findings from the existing business

**1. Kit readiness has a multi-week lead time, and the model had no state for it.**

Gifteko's customisation is embossing, laser engraving and brand-matched configuration — artwork, proof, approval, production. That happens **once per customer**, not once per hire, and it takes weeks. Without modelling it, the first dispatch for a new customer fires against branded stock that does not exist yet.

Kit readiness is therefore a **customer onboarding step, not a dispatch-time step**. It belongs alongside SSO configuration and CTC rule setup in Phase 2's organisation setup, and the Dispatch Record gains an `AwaitingKitReadiness` status so a premature trigger parks visibly instead of failing. Emits `KitDispatchAwaitingReadiness`.

**2. Bulk multi-destination fulfilment and per-hire dispatch are different operations.**

The existing business is built for large-scale multi-destination deployments — campaign-shaped, ordered in bulk. An ATS generates the opposite: single units, one address, trickling in as hires close. That is a different fulfilment model, and it needs an explicit operational choice per customer rather than an assumption:

| Mode | How it works | Suits |
|---|---|---|
| `BufferStock` | Branded stock held per customer; pick-and-pack singles; reorder at threshold | Steady hiring, established customers |
| `BatchedWeekly` | Dispatches accumulate and ship in a weekly batch | Cost-efficient; acceptable where joining dates are known in advance |
| `DropShipPerHire` | Single unit produced or shipped per hire | Low or unpredictable volume; highest unit cost |

This choice determines what dispatch SLA the platform can honestly promise HR, so it is configuration, not a runtime decision.

**3. No pricing in the platform.**

Gifteko's catalogue is deliberately published without pricing — everything routes through enquiry and quote. The platform follows that: kit selection is by catalogue and tier, cost is settled commercially outside the system. No price fields, no pricing engine, no budget approval flow for kits. A genuine scope reduction that falls out of how the business already operates.

#### Entity relationship

Kit Catalogue Item (Gifteko-managed) → composed into Client Kit (per customer, versioned) → assigned by job family or designation band → referenced by Dispatch Record with a version snapshot. Organization Kit Profile holds the branding assets, proof approval, readiness state and fulfilment mode.

### 3.9 Calendar — Google Workspace / Microsoft Outlook

Both adapters built; provider determined per organisation. Create, update and cancel invites on every schedule change. Free/busy lookup feeds the scheduling engine. Writes `calendar_event_id` and interviewer `invitation_status` back to Interviewer Assignment. Failure to create an invite must not leave a scheduled round with no invitation — the round stays `Scheduled` with an ops alert rather than silently proceeding.

### 3.10 Slack — team notifications

Outbound only, via the notification service. Approval requests, SLA breaches, escalations. No PII in Slack messages beyond candidate name and a deep link — Slack sits outside the residency boundary, so the message body is a pointer, not a payload.

### 3.11 Email — AWS SES or SendGrid

Commodity. SES preferred given AWS hosting. Bounce and complaint webhooks feed Notification Log status.

### 3.12 LLM inference — AWS Bedrock Mumbai / Azure OpenAI India

Used by JD generation, resume parsing, scoring, AI Copilot, and possibly Layer 2 reasoning. Every call records `model_version_id`. **Region is asserted per call and the adapter fails closed on a non-India endpoint** — this is the mechanism behind V3.2's residency commitment, which would otherwise be a documentation claim rather than an enforced control.

---

## Section 4. Business Rules & Configuration

Structure is defined here. **Values marked [BLOCKED] require an HR/Finance working session** — this section is deliberately parameterised rather than invented, because guessing a salary structure and then discovering it is wrong is far more expensive than waiting for it.

### 4.1 CTC calculator — RESOLVED

Finalised against the four Labour Codes, in force since 21 November 2025. The structure below is the seeded V1 rule set; the engine stays generic so any organisation can define its own.

**The constraint that drives everything:** the Code on Wages redefines "wages" as basic pay, dearness allowance and retaining allowance, with HRA, conveyance, statutory bonus, overtime and commission listed as exclusions — but if those excluded components together exceed 50% of total remuneration, the excess is folded back into wages for PF, gratuity and bonus purposes. The practical effect for structuring is that basic must sit at or above 50%, or the statutory bases silently expand anyway. Structures that historically kept basic at 30–40% no longer work.

#### Seeded rule set V1

| # | Component | Rule | Notes |
|---|---|---|---|
| 1 | **Basic Salary** | **50% of CTC** | The Labour Code floor. Configurable upward, never below 50% |
| 2 | **House Rent Allowance** | 50% of Basic (metro) / 40% (non-metro) | Metro status from the offer location |
| 3 | **Employer PF** | 12% of Basic, capped at the statutory wage ceiling | Ceiling configurable — see below |
| 4 | **Gratuity** | 4.81% of Basic | The 15/26 formula expressed as an annual accrual |
| 5 | **Employer ESI** | 3.25% of gross, **only if** monthly gross ≤ threshold | Conditional component; skipped for most hires |
| 6 | **Special Allowance** | **Balancing figure** | Absorbs the remainder so components always sum to CTC |

Employee-side deductions — employee PF at 12%, professional tax by state, TDS — are shown as an indicative net-pay illustration, **not** as CTC components. They are the employee's deductions, not the company's cost.

#### Statutory parameters — configurable, not hard-coded

These change by notification, so each is a dated configuration value on the rule set version rather than a constant in code.

| Parameter | Current value | Note |
|---|---|---|
| EPF wage ceiling | **₹15,000/month** | The proposed increase to ₹21,000–₹25,000 has been repeatedly deferred; sources conflict on current status. Verify before go-live and treat as a dated config value either way |
| EPF rate | 12% employee + 12% employer | Employer split 3.67% EPF / 8.33% EPS |
| ESI | 3.25% employer + 0.75% employee | Eligibility at gross ≤ ₹21,000/month |
| Gratuity accrual | 4.81% of Basic | Statutory cap ₹20,00,000 |
| Professional tax | State-specific | Display-only in the net illustration |

#### Rule set JSON — V1, concrete

```json
{
  "version": 1,
  "statutory_params": {
    "epf_wage_ceiling_monthly": 15000,
    "epf_employer_rate": 0.12,
    "epf_ceiling_applies": true,
    "esi_employer_rate": 0.0325,
    "esi_eligibility_gross_monthly": 21000,
    "gratuity_accrual_rate": 0.0481,
    "as_of": "2026-08-30"
  },
  "components": [
    { "key": "basic", "label": "Basic Salary", "display_order": 1,
      "type": "percentage_of", "base": "ctc_annual", "value": 0.50,
      "is_wages": true, "taxable": true, "min_percentage_of_ctc": 0.50 },

    { "key": "hra", "label": "House Rent Allowance", "display_order": 2,
      "type": "percentage_of", "base": "basic",
      "value_by_location": { "metro": 0.50, "non_metro": 0.40 },
      "is_wages": false, "taxable": "partial" },

    { "key": "special_allowance", "label": "Special Allowance", "display_order": 3,
      "type": "balancing_figure",
      "is_wages": false, "taxable": true },

    { "key": "pf_employer", "label": "Provident Fund (Employer)", "display_order": 4,
      "type": "statutory_percentage", "base": "basic",
      "rate_param": "epf_employer_rate", "ceiling_param": "epf_wage_ceiling_monthly",
      "is_wages": false, "in_hand": false },

    { "key": "gratuity", "label": "Gratuity", "display_order": 5,
      "type": "statutory_percentage", "base": "basic",
      "rate_param": "gratuity_accrual_rate",
      "is_wages": false, "in_hand": false },

    { "key": "esi_employer", "label": "ESI (Employer)", "display_order": 6,
      "type": "conditional_statutory", "base": "gross_monthly",
      "rate_param": "esi_employer_rate",
      "condition": "gross_monthly <= esi_eligibility_gross_monthly",
      "is_wages": false, "in_hand": false }
  ],
  "rounding": { "mode": "nearest", "to_nearest": 1, "absorbed_by": "special_allowance" },
  "validation": {
    "sum_must_equal": "ctc_annual",
    "tolerance": 1.00,
    "wage_code_floor": {
      "rule": "sum(components where is_wages = false and excludable) <= 0.50 * ctc_annual",
      "on_breach": "block_offer_generation"
    }
  }
}
```

#### Worked example — ₹10,00,000 CTC, metro

| Component | Amount | Wages? |
|---|---|---|
| Basic Salary | ₹5,00,000 | Yes |
| HRA | ₹2,50,000 | No |
| Special Allowance (balancing) | ₹2,04,350 | No |
| Employer PF (12% of ₹1,80,000 ceiling) | ₹21,600 | No |
| Gratuity (4.81% of Basic) | ₹24,050 | No |
| **Total CTC** | **₹10,00,000** | |

Wage Code check: excluded components total ₹4,54,350 = 45.4% of CTC. Below the 50% ceiling — passes.

#### Two design gates

**The Wage Code validation is a hard block, not a warning.** If a configured rule set would push excluded components past 50%, offer generation is refused with the specific component named. A silent pass here creates a statutory shortfall that surfaces months later as an EPFO demand notice with arrears and interest — which is exactly the failure this validation exists to prevent.

**[OPEN — counsel] The denominator.** Whether "total remuneration" for the 50% test means total CTC or gross salary excluding employer PF and gratuity is genuinely ambiguous, and payroll vendors have taken different readings. The engine computes against CTC, which is the conservative reading; the denominator is a config value so it can be switched without a code change. Worth one question to counsel, not a blocker.

**Variable pay is not in V1.** It can be added as a component with a payout frequency, but it reduces the fixed offer and complicates the Wage Code arithmetic. Recommend leaving it out until a customer asks.

### 4.2 Approval bands — [BLOCKED on HR/Finance]

Required per entity: designation → maximum CTC without approval; the capability required to approve above band; whether the band is absolute or a percentage over the posted range.

Fixed now: above-band routes to an Approval Request with `required_capability = approve_ctc_above_band`; the evaluated threshold is stamped onto Negotiation Log; below-threshold passes through with no approval record but with an audit entry.

### 4.3 Default pipeline templates — [BLOCKED on HR input]

Required: real round structures per job family. Fixed now: the fallback default when Configurable Pipelines is off is a three-round template (Screening → Technical → HM), replaceable per organisation without code change.

### 4.4 SLA and reminder defaults

| Rule | Default | Configurable |
|---|---|---|
| Job approval window | 2 business days, then escalate | Yes |
| Interview feedback | 3 business days; reminder, then escalate on second miss | Yes |
| Document reminders | Day 2, 5, 8 | Yes |
| Screening retry | 3 attempts, different times of day, across 2 days | Yes |
| Offer expiry | Set at send time; reminders at T-3 and T-1 days | Yes |
| Talent pool consent validity | 24 months, then re-ask or purge | Yes |
| Address staleness | 30 days before dispatch re-confirmation | Yes |
| BGV conditional deadline | Set per case at flag resolution | Per case |

Business days computed against a per-organisation holiday calendar in the organisation's timezone. A naive calendar-day implementation will breach SLAs across Indian festival clusters.

### 4.5 Feature flag semantics

Flags govern behaviour, never silent data destruction.

| Flag | Off behaviour |
|---|---|
| Talent Pool | Pooled profiles non-searchable; no new entries. Existing profiles retained, consent stands. Purge only via the retention job or explicit revocation |
| AI Copilot | Summaries hidden, no new generation; records retained for audit |
| Internal Notes | Existing notes read-only for Admin, hidden from other roles |
| Configurable Pipelines | Falls back to the org default template; in-flight Applications keep their snapshotted pipeline |
| Cross-Round Feedback Visibility | Interviewers see only their own feedback |

### 4.6 Retention

Retention runs on **three independent clocks**. Which clock applies is determined by the Application's terminal state, not by data type — this is the distinction that a single retention period cannot express.

| Track | Trigger | Retention | Rationale |
|---|---|---|---|
| **A — Non-joiner** | Rejected, Withdrawn, Offer-Declined, Rescinded, Joining-No-Show | **12 months** from terminal state | Recruitment data. Long enough to answer a discrimination challenge or a candidate query, short enough to limit exposure |
| **B — Joiner** | Onboarded | **Handoff at +90 days, then purge** | The data stops being recruitment data. Rather than inherit multi-year employment-record obligations, the compliance pack is exported to the customer's system of record and destroyed here |
| **C — Talent pool** | Rejected **with** retention consent | Consent validity, default 24 months, re-askable | Consent-driven, and **extends** Track A rather than running alongside it |

**Precedence rules** — these matter more than the numbers, because they are where a single-clock implementation silently does the wrong thing:

1. **The longest applicable clock wins.** A pooled candidate is retained for 24 months, not purged at 12.
2. **Track B supersedes everything on `Onboarded`.** The moment an Application reaches Onboarded, its documents leave the candidate retention regime and enter the handoff window. The candidate purge job must never touch them; the handoff job owns them.
3. **Consent revocation collapses Track C to Track A**, not to immediate deletion — the profile returns to the 12-month clock from its original terminal state, which may mean immediate purge if that date has passed.
4. **Compliance documents do not follow pool consent.** Talent-pool consent covers profile and skills data for future matching. It is not consent to retain Aadhaar, PAN or EPFO documents, which purge on their own clock regardless of pool status.

| Data | Clock | On purge |
|---|---|---|
| Candidate Profile — non-joiner, not pooled | A: 12 months | Identifying fields destroyed; Application Analytics Record created |
| Candidate Profile — pooled | C: 24 months, re-askable | As above on expiry without renewal |
| Candidate Profile — joiner | B: handoff +90d | Identifying fields destroyed after successful handoff; Analytics Record retained |
| Documents (Aadhaar/PAN/EPFO/marksheets) — non-joiner | A: 12 months | Files destroyed, hashes retained for audit |
| Documents — joiner | B: handoff +90d | Exported in the Employment Record Pack, then destroyed here |
| Call recordings | Org-configured, capped by the consent disclosure text | Destroyed; Screening Call Record retained without `recording_ref` |
| Offer documents (signed) — joiner | B: handoff +90d | Included in the Employment Record Pack, then destroyed here |
| Offer documents (signed) — non-joiner | A: 12 months | Destroyed; Offer row retained without `signed_document_ref` |
| Audit Log | Never purged | Contains no free-text PII by construction |
| Domain Events | Never purged | Payloads carry no PII by rule (Section 2.1) |
| Application Analytics Record | Never purged | Anonymised by construction |

#### Track B — the Employment Record Handoff

The statutory retention periods for employment records run to years and are measured from **end of employment** — an event this platform never sees. Scope ends at `Onboarded`: no payroll, no attendance, no exit. "Retain for N years from exit" is therefore unimplementable here, and in practice degrades into retain-forever.

The resolution is to move the obligation rather than inherit it.

| Step | Behaviour |
|---|---|
| `Onboarded` | Handoff window opens. Records frozen — no candidate purge, no edits |
| +90 days (configurable) | **Employment Record Pack** assembled and exported to the customer's system of record |
| Export confirmed | Documents, signed offer and identifying profile fields destroyed here. Analytics Record retained. Emits `EmploymentRecordHandedOff` then `RetentionPurgeExecuted` |
| Export fails | Retry with backoff, then alert. **Nothing is destroyed without a confirmed successful handoff** |

**Employment Record Pack** — a versioned, documented export contract, not an ad-hoc dump: structured JSON (identity fields, offer terms, CTC breakdown with its rule set version, joining date, BGV outcome) plus the document set and signed offer PDF, with a manifest and per-file hashes.

Ninety days is chosen to cover onboarding corrections — a re-issued document, a corrected EPFO detail — while staying well short of any period where the data would start looking like an employment record we are choosing to hold.

**Exception path.** A customer with no HRMS gets `AdminHold`: the pack is generated and made available for download, and an Admin confirms receipt to trigger the purge. If they never confirm, records hold and appear on a compliance dashboard rather than expiring silently.

**Backups inherit the longest clock.** A backup that outlives the retention window makes the purge cosmetic, so backup retention is set from the longest active clock — now Track C's 24 months rather than a multi-year employment period, which is a useful side effect of the handoff design. Track A restoration from an old backup must re-run the purge before the data is reachable.

Purge runs as a scheduled job, dry-run first, emitting `RetentionPurgeExecuted` with a Retention Job Run record.

### 4.7 Document phase ordering — [BLOCKED: confirm default per organisation]

Default `PreOfferLetter`. Set per organisation, snapshotted onto the Application at shortlist so a mid-flight config change cannot reorder a live candidate's journey. Branch B requires the Aadhaar-capture step (**S1**).

---

## Section 5. Vendor Selection & Pre-Contract Requirements

Closed by V3.2. Recorded here for completeness with the pre-contract checklist extended.

| Integration | Selected | Fallback | Status |
|---|---|---|---|
| E-signature | **Digio** | Leegality | Sealed |
| Background verification | **AuthBridge** | SpringVerify (parallel pilot) | Sealed, pilot pending |
| Telephony + SMS (Layer 1) | **Exotel** | Ozonetel / Knowlarity | Sealed |
| Voice AI (Layer 2) | **Pilot required** — Gnani, Sarvam, Bolna, SquadStack | — | **Open** |
| Job board — Naukri | API adapter (paid RMS) | Manual package | Sealed |
| Job board — LinkedIn | Manual posting package | — | Sealed; no API at launch |
| Onboarding kit | **Gifteko** | — | **First-party** — the group's own gifting business. Not a procurement decision |
| Calendar | Google Workspace / Microsoft Outlook | — | Both adapters built |
| Team notifications | **Slack** | — | Fixed |
| Email | AWS SES (SendGrid alternate) | Either | Commodity |
| Hosting | **AWS Mumbai (ap-south-1)**, DR Hyderabad (ap-south-2) | Azure India / GCP Mumbai | Sealed |
| LLM inference | India-region endpoints (Bedrock Mumbai / Azure OpenAI India) | — | Sealed |

### 5.1 Pre-contract requirements — **extended**

V3.2 required a DPA, DPDP attestation, written India residency confirmation, breach-notification SLA and a named escalation path from **Digio, AuthBridge and Exotel**. That list is narrower than the actual processor set.

| Processor | Data received | In V3.2 list | Required |
|---|---|---|---|
| Digio | Name, contact, Aadhaar reference, offer document | Yes | Full set |
| AuthBridge | Name, DOB, address, employment, education, ID references | Yes | Full set |
| Exotel | Phone number, call audio, SMS content | Yes | Full set |
| **Voice AI (Layer 2)** | **Raw candidate voice, transcripts** | **No** | **Full set — as a pilot gate, not post-selection** |
| **Gifteko** | Name, postal address, joining date | **No** | **First-party.** Intra-group data-sharing agreement if a separate entity; internal transfer if the same entity. Confirm structure |
| Naukri | Job content; candidate applications inbound | No | DPA |
| Slack | Candidate name, deep links | No | Existing enterprise agreement to be confirmed |
| SES / SendGrid | Email address, message content | No | DPA; SES within AWS agreement if used |

**Commercial:** e-signature, BGV and voice are volume-tiered. Final pricing is blocked on the monthly volume assumptions in Section 8. Public rate ranges at selection: e-sign ₹3–₹25 per signature; BGV ₹500–₹8,000 per candidate depending on check depth and geography.

---

## Section 6. Non-Functional & Platform Design

### 6.1 Authentication & authorisation

**Internal roles:** SSO via SAML 2.0 / OIDC, per-organisation IdP config, JIT provisioning optional. No local passwords for internal users.

**Candidates:** no account, no SSO. Access is exclusively through Candidate Portal Tokens — expiring, single-Application-scoped, purpose-narrowed, revocable, hashed at rest (B5). Every token use is logged; a token for a terminal-state Application is rejected regardless of expiry.

**Authorisation model:** capability-based (B2/B3). Every API endpoint declares a required capability; roles are capability bundles; scoped grants support "own reqs" and "own round only." Enforcement is at a single middleware layer, not scattered through handlers.

**Approval authority** resolves through Approval Delegation at assignment time, and a delegate must independently hold the capability — delegation cannot manufacture authority.

### 6.2 Multi-tenancy isolation

`organization_id` is on every entity. **Enforcement is PostgreSQL row-level security** with the tenant set per connection from the authenticated session, plus an application-layer guard as defence in depth. Application code cannot issue an unscoped query even by accident.

Isolation is a **standing test-suite requirement**, not a review item: every integration test runs with two tenants present and asserts zero cross-tenant visibility. A tenant-leak regression is the single worst failure mode this platform has.

### 6.3 Data residency — enforced, not documented

| Layer | Control |
|---|---|
| Application, database, object storage | AWS Mumbai (ap-south-1); DR Hyderabad (ap-south-2) |
| LLM inference | India-region endpoints only. **Adapter fails closed** on a non-India endpoint for any PII-bearing payload |
| Encryption keys | KMS, India region |
| Vendor residency | Written attestation as a pre-contract condition (5.1), recorded and re-verified annually |
| Backups | India region only; DR restore tested quarterly |

DPDP permits cross-border transfer by default with no broad country restrictions currently in force, so India hosting is not strictly mandated for recruitment data. It is adopted anyway — the platform stores Aadhaar, PAN and EPFO details, and India hosting is the expected posture for sensitive personal data under DPDP and in audit. Recording the reasoning matters: it is a deliberate posture choice, not a misread of the law.

### 6.4 Data security

| Control | Implementation |
|---|---|
| At rest | AES-256; separate KMS keys for documents, recordings and database |
| In transit | TLS 1.2+ everywhere, including internal service hops |
| Field-level masking | Aadhaar / PAN / EPFO masked by default; unmasking requires `view_unmasked_pii` and emits `SensitiveDataAccessed` on **every read** |
| Document storage | S3 with server-side encryption, no public access, pre-signed URLs scoped and short-lived |
| Exports | PII-bearing exports require `export_pii`, are watermarked with requester and timestamp, and emit `PIIExported` |
| Upload safety | Type allowlist, size limits, virus scan before storage, content-type verification |
| Secrets | AWS Secrets Manager, rotated, never in code or config |
| Public form | Rate limiting, CAPTCHA, honeypot |

### 6.5 Resilience & async processing

**Async job queues** for resume parsing, AI scoring, voice call orchestration, notification dispatch, calendar sync and the retention job. Each has: bounded retry, a DLQ, an alert on DLQ depth, and a defined application state for permanent failure (Section 1.12) — a failed parse must surface, not disappear.

**Transactional outbox** for event emission — state change and event row commit together.

**Circuit breakers** per external integration. An Exotel outage must not block interview scheduling; a Digio outage must not block document verification. Module coupling runs through events, so degradation is partial by design.

### 6.6 Observability

Structured JSON logs with `correlation_id`; **PII redacted at the logging layer**, not by convention. Metrics: queue depth and age, DLQ depth, event lag per consumer, integration error rate and latency, SLA breach counts, token validation failures. Traces across the module → event → consumer → vendor path.

Alerting priorities: tenant-isolation assertion failure, audit hash-chain break, DLQ depth threshold, residency fail-closed trigger, purge job failure.

### 6.7 Deployment

Containerised services on ECS or EKS in ap-south-1; RDS PostgreSQL Multi-AZ with cross-region read replica in ap-south-2; S3 with cross-region replication in-country; managed queue and event bus. IaC-defined, with environment parity for dev / staging / production and no manual production changes.

**Backup/DR:** point-in-time recovery, retention aligned to Section 4.6 (backups must not outlive the retention policy or the purge is cosmetic), quarterly restore drills.

### 6.8 Implementation stack — recommendation

Not specified in V3.2 and therefore still open. Given the team's Python background and the workload profile — LLM orchestration, resume parsing, async pipelines — a Python stack is the natural fit: **FastAPI** for services, **SQLAlchemy + Alembic** for the model and migrations, **Celery** or **Dramatiq** on SQS for the job queues, **Pydantic** for the event envelope and payload schemas.

Pydantic in particular earns its place here: the event contracts in Section 2 need runtime validation at both emit and consume, and `schema_version` branching is far cleaner with typed models than with dictionary handling. Worth confirming as an explicit decision rather than letting it happen by default.

---

## Section 7. Acceptance Criteria & Test Plan

Criteria are written to be testable — each is a pass/fail assertion, not a description. Cross-cutting suites run against every module.

### 7.0 Cross-cutting suites (run continuously)

| Suite | Assertion |
|---|---|
| Tenant isolation | With two organisations seeded, no API call, query, export, or event delivery surfaces another tenant's data. Zero exceptions |
| Audit completeness | Every status change, feedback entry, approval, decision, note, consent action and merge produces exactly one audit entry; hash chain verifies |
| Event emission | Every state transition emits its event; no orphan events; no state change without an event |
| Residency fail-closed | A forced non-India LLM endpoint causes the call to fail, not to succeed and log a warning |
| PII masking | Aadhaar/PAN/EPFO masked for every role lacking the capability; each unmask emits `SensitiveDataAccessed` |
| Idempotency | Replaying any webhook or event twice produces one state change |
| Token security | An expired, consumed, revoked, wrong-purpose, or terminal-state token is rejected in all cases |

### 7.1 Module 1 — JD Creation

- LLM draft composes from the **active** template versions; edits do not mutate templates.
- Post-publish edit increments `jd_version`; existing Applications retain the version they applied against.
- Publish requires an approved Approval Request; unactioned requests escalate after the configured window and emit `ApprovalEscalated`.
- Delegation within its date range routes to the delegate; outside the range it routes to the delegator. A delegate lacking the capability is rejected at delegation creation.
- Naukri failure emits `JobBoardPostingFailed` and alerts; LinkedIn records manual attestation.
- Application form URL resolves the correct `job_id`.

### 7.2 Module 2 — Resume Collection, Tagging & Scoring

- Same person via three sources (applied / referred / hr_added) produces **one** Candidate Profile and three Applications.
- Dedup triggers on normalised email, normalised phone, and resume fingerprint independently.
- Parsing occurs once per profile; scoring once per Application.
- A malformed or corrupt resume produces `Parse-Failed` with an HR-visible recovery path — never a silently stalled Application.
- Referrer receives exactly three notifications (received, shortlisted, outcome) and **no** feedback, score, or compensation data. Asserted by inspecting notification payloads, not by inspecting UI.

### 7.3 Module 3 — Screening & Interviews

- DND-listed number is never dialled; `DNDBlocked` recorded on the attempt.
- Three attempts land in different time-of-day buckets across two days; the fourth never fires; escalation to HR occurs.
- Declined recording consent halts recording, sets `ConsentDeclined`, and retains no audio.
- Both `telephony_call_id` and `voice_ai_session_id` are populated on every completed call — a call debuggable in only one layer is a failed assertion.
- Pipeline snapshot: editing a template after shortlist does not alter in-flight Applications. Attempting to update an Active template version is rejected at the database.
- Panel: each interviewer submits independent feedback; peer feedback is hidden before submission when the visibility flag is off; the lead's round decision is recorded with a reason code on reject.
- Feedback SLA: reminder at breach, escalation on second miss, `FeedbackSLABreached` emitted, tracked **per interviewer**.
- Calendar invites created, updated and cancelled on every schedule change; invite failure leaves the round visibly unconfirmed.

### 7.4 Modules 4–5 — Offer Decision & Negotiation

- Parallel-pipeline detection surfaces the candidate's other open Applications and blocks progression until acknowledged; the acknowledgement is recorded.
- Above-band CTC creates an Approval Request; below-band passes through with an audit entry and no approval record.
- The applied threshold value and policy version are stamped onto Negotiation Log and remain readable after the policy is retired.

### 7.5 Module 6 — Document Collection

- Multiple marksheets and multiple employment proofs are all submittable and independently trackable.
- Rejecting one document requests exactly that document with its reason; the rest of the form is untouched.
- Reminders fire at day 2, 5 and 8 against business days, and stop on submission.
- HR-assisted submission (`submit_documents_on_behalf`) is captured with the acting user and emits `DocumentSubmittedOnBehalf`.
- Address written to the document flows to Candidate Profile as source of truth.

### 7.6 Module 7 — Offer Letter & Signature

- CTC breakdown sums to CTC within ₹1; drafting is blocked otherwise.
- **Basic is never below 50% of CTC**, and a rule set configured to breach the Wage Code excluded-component ceiling blocks offer generation with the offending component named — a warning is not sufficient.
- Changing a statutory parameter (EPF ceiling, ESI threshold) creates a new rule set version; historical offers still reproduce against their original version.
- The rule set version is stamped and the breakdown is reproducible after the rule set is retired.
- Signing is embedded in the portal — no redirect to a hosted vendor page.
- Expiry is governed by our `expiry_date`; a vendor-side lapse cannot extend an offer. Reminders fire at T-3 and T-1.
- Reissue creates a **new version** with fresh expiry; the prior version becomes `Superseded` and remains readable.
- Decline is recorded as a distinct outcome with an optional reason — not conflated with expiry or withdrawal.
- **Branch B:** with `PostSignature` ordering, Aadhaar capture precedes signing and the flow completes without Module 6 having run.

### 7.7 Module 8 — BGV

- Initiation without a Granted, unexpired `BackgroundVerification` consent is rejected **at the database**, not only in code.
- Each of Proceed, Rescind and Conditional Proceed produces its correct downstream state; Conditional Proceed requires a deadline and generates follow-up.
- BGV incomplete at joining date applies the organisation's configured policy.
- Parallel pilot: both vendors' records are created and comparable on turnaround, and the run is identifiable via `is_pilot_parallel_run`.

### 7.8 Module 9 — Kit Dispatch

- Triggers only on Proceed or Conditional Proceed.
- A dispatch triggered before the Organization Kit Profile reaches `StockReady` parks in `AwaitingKitReadiness` and alerts, rather than failing at the vendor boundary or dispatching unbranded stock.
- A Client Kit redesign does not alter any past Dispatch Record — version snapshot holds.
- Under `BatchedWeekly`, dispatches accumulate to a batch and the promised delivery date reflects the batch schedule, not the trigger date.
- Address stale beyond the interval triggers re-confirmation before dispatch; the confirmation is recorded.
- Dispatch failure retries with backoff, then alerts HR; the address snapshot is immutable after dispatch.

### 7.9 Module 10 — Talent Pool

- Pool entry requires explicit consent; without it, the profile is scheduled for purge.
- Revocation removes the profile from search **immediately** and schedules purge; the revocation link is present in every pool communication.
- Consent expiry at the validity period triggers re-ask, then purge on no response.
- Reactivation creates a **new Application against the existing profile** — never a duplicate profile.
- Turning the flag off makes the pool non-searchable and destroys nothing.

### 7.10 Module 11 — AI Copilot

- No summary surfaces without an Approved Fairness Review on its `model_version_id`.
- Activating a new model version hides its output until fresh sign-off — **without touching historical summary rows**.
- A prompt change is treated as a new model version.
- Flag off hides summaries and stops generation; records are retained.
- Pre-production validation against historical hiring outcomes is completed and documented before any output is treated as trusted input.

### 7.11 Candidate Merge

- Applications, documents and consents repoint to the survivor; audit entries retain original profile IDs and resolve through the merge chain.
- Merge is blocked when both profiles hold live Applications on the same job — enforced by the partial unique index.
- More restrictive consent wins per type, evaluated on effective state.
- Discarded field values are recorded in Merge Log.

### 7.12 Retention

- Purge destroys identifying fields and creates an Application Analytics Record with the specified fields and nothing more.
- **A candidate who reached `Onboarded` is never touched by the candidate purge job**, at any age, under any configuration. Asserted directly, not inferred from a date comparison.
- The Employment Record Pack is generated at the configured window, validates against its manifest hashes, and **no destruction occurs until export is confirmed**. A failed export leaves everything intact and raises an alert.
- Under `AdminHold`, records persist indefinitely without Admin confirmation and surface on the compliance dashboard.
- A pooled candidate at 13 months is retained; the same candidate with consent revoked is purged on the Track A clock, not deleted immediately.
- Talent-pool consent does not extend document retention — compliance documents purge on their own clock while the profile remains pooled.
- Restoring a Track A candidate from a backup older than their purge date re-runs the purge before the data is reachable.
- Funnel and time-to-hire reports return identical aggregates before and after a purge.
- Backups do not retain purged PII beyond the retention window.
- Dry-run mode changes nothing and reports what would change.

---

## Section 8. Open Items & Decision Log

### 8.1 Closed by V3.2

E-signature vendor · BGV vendor · telephony and DLT provider · job board posting approach · hosting region · LLM residency · SMS provider.

### 8.2 Open items

All architecture-blocking items are closed. What remains needs business or legal input and none of it gates the build.

| # | Item | Owner | Interim position |
|---|---|---|---|
| 1 | Approval band thresholds per designation | HR/Finance | Every offer routes to approval (E-05) |
| 2 | Wage Code 50% denominator — total CTC or gross excluding employer PF and gratuity | Legal | Computed against CTC; denominator is a config value |
| 3 | Gifteko sub-processor agreement and customer DPA disclosure | Legal | — |
| 4 | Kit branding onboarding for the design partner | Gifteko ops | **Multi-week lead time; gates first dispatch** |
| 5 | Permanent fairness sign-off owner | Leadership | Project lead, interim |
| 6 | Naukri RMS subscription justification at launch volumes | Product | Career portal live regardless |
| 7 | Catalogue categories confirmed against Gifteko's internal structure | Gifteko ops | Inferred from the public catalogue |

**Previously blocking, now closed:** CTC rules (E-01), monthly volumes (E-07), default pipeline templates (E-06), statutory retention (C-03, C-04), voice AI selection (D-01, deferred), document-phase ordering (D-07, Branch A).

### 8.3 Change control

S1–S7 were resolved in Spec V3.3. Any further change to this document or the spec requires a Decision Log entry (01) with an ID, date, rationale and reversibility rating.

### 8.4 Suggested build sequence

| Sprint | Content | Depends on |
|---|---|---|
| 0 | Stack confirmation, IaC, RLS multi-tenancy, CI with the tenant-isolation suite | 8.2 #9 |
| 1 | Identity & access (B1–B5), Approval engine (C1–C2), Audit Log, event bus + outbox | Nothing external |
| 2 | Organization config, JD templates, Job Posting, Board Posting, Module 1 | Sprint 1 |
| 3 | Candidate Profile, Application, dedup, parsing/scoring adapters, Module 2 | Sprint 1, LLM endpoint |
| 4 | Pipeline templates, Interview Rounds, Interviewer Assignment, Feedback, calendar adapters, Module 3B | Sprint 3 |
| 5 | Exotel adapter, Voice AI adapter (vendor-agnostic), Consent Log, Module 3A | Sprint 4; **pilot runs here** |
| 6 | Negotiation, CTC engine, Offer, Digio, Modules 4–5–7 | **Blocked on 8.2 #1** |
| 7 | Documents, BGV, Dispatch, Modules 6–8–9 | Sprint 6 |
| 8 | Talent Pool, Merge, Retention, Timeline, Reporting | Sprint 3+ |
| 9 | AI Copilot behind flag, Model Version, Fairness Review | **Blocked on 8.2 #6** |

Sprints 1–5 have no dependency on the open business decisions. The CTC working session needs to conclude before Sprint 6, which gives roughly ten weeks of runway — that is the single scheduling constraint worth tracking now.

---

*SDD 3.0 — sealed 30 August 2026, aligned to Build Spec V3.3. All seven sections are build-ready. Changes require a Decision Log entry (01).*

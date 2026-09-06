# Employee Onboarding & Recruitment Platform
# 02 — Build Spec V3.3 (Enterprise Edition, India)

**Status: SEALED.** Functional scope, business rules and vendor positions are final for the initial build. Changes require a Decision Log entry (01), not a quiet revision.

---

## Changelog: V3.2 → V3.3

V3.3 resolves the seven internal contradictions raised during solution design, folds in every business decision taken since the V3.2 seal, and corrects one significant mischaracterisation.

### Corrections to V3.2

| # | Change | Decision |
|---|---|---|
| 1 | **Gifteko is first-party**, not a vendor. It is the group's existing corporate gifting business and the reason this platform exists. Kit dispatch is core scope, not an optional integration. The kit model is expanded accordingly | D-04, G-01 |
| 2 | **CTC structure specified** against the four Labour Codes, in force since 21 November 2025. Basic must sit at or above 50% of CTC | E-01 |
| 3 | **Retention replaced with a three-clock model**, including an Employment Record Pack handoff that removes multi-year employment-record obligations from this platform | C-02 to C-07 |
| 4 | **AI voice screening deferred.** Manual HR screening at launch, integration seam preserved | D-01 |
| 5 | **AI Copilot descoped** to narrative outputs. Salary-fit and offer-confidence scores deferred pending a validation corpus | D-02 |
| 6 | **BGV module retained, vendor contract deferred.** Manual-entry mode at launch | D-05 |
| 7 | Seven internal contradictions (S1–S7) resolved — see below | — |

### Resolution of S1–S7

| # | Contradiction in V3.2 | Resolution |
|---|---|---|
| S1 | Module 7 justified Aadhaar eSign with "Aadhaar is already on file from Module 6", but the spec allowed inverting document collection to post-signature, where Module 6 has not run | Aadhaar capture is a prerequisite of **signing**, not of Module 6. Branch B gains a minimal Aadhaar-capture step. **Branch A is the only ordering built initially** (D-07) |
| S2 | Under inverted ordering, BGV triggered on offer-signed before employment and education documents existed | BGV initiation gated on document availability, not signature alone |
| S3 | `joining_date` sat on the Offer, but HR entered it after signing — so a signed letter would not state it | Split into `proposed_joining_date` (in the letter, pre-signature) and `confirmed_joining_date` (post-signature) |
| S4 | Module 5 routed above-band CTC to "Finance or HR Head"; no Finance role existed | Modelled as a **capability** (`approve_ctc_above_band`) grantable to any named user, rather than inventing a role |
| S5 | "None of the open questions block architecture" — but document ordering and voice selection both did | Reclassified. Both now resolved |
| S6 | Pre-contract DPA requirements named three vendors; the voice layer and Gifteko were omitted | Extended to all third-party processors. Gifteko follows the first-party sub-processor path instead |
| S7 | Recording consent captured "at call open", after transport-layer recording had started | Recording start deferred to a post-consent trigger; any pre-consent segment discarded and the discard logged. Moot at launch with voice deferred |

---

## Scope Statement

Full hiring lifecycle from job description creation through onboarding kit dispatch.

**Out of scope, unchanged:** payroll, leave, attendance, performance management, LMS, asset management.

**The scope boundary is load-bearing.** It is why employment records hand off to the customer at Onboarded + 90 days rather than being retained here. Expanding scope later is possible; doing so silently is not.

---

## Launch Scope vs Full Scope

Every module below is specified in full. This table records what ships at launch and what sits behind a flag.

| Module | Launch | Notes |
|---|---|---|
| 1 — JD Creation | ✅ | |
| 2 — Resume Collection & Scoring | ✅ | |
| 3A — Screening | ✅ **Manual** | Voice AI deferred; adapter seam preserved |
| 3B — Interview Rounds | ✅ | Panel support included |
| 4 — Offer Decision | ✅ | |
| 5 — Negotiation | ✅ | Interim approval band: all offers route to approval |
| 6 — Document Collection | ✅ | Branch A ordering only |
| 7 — Offer Letter & E-Signature | ✅ | Digio, Aadhaar eSign |
| 8 — Background Verification | ✅ **Manual entry** | Module complete; AuthBridge adapter pending contract |
| 9 — Onboarding Kit Dispatch | ✅ | **First-party. Core scope** |
| 10 — Talent Pool | Flag off | |
| 11 — AI Copilot | Flag off | Narrative only when enabled; shadow generation from Phase 3 |

Every vendor-dependent stage is skippable by flag, with the skip recorded on the candidate timeline (D-06).

---

## Architecture Foundation: Event-Driven Design & Feature Flags

Every module emits domain events rather than calling downstream services directly. Candidate 360 Timeline, Notification service, Audit Log, Reporting, Talent Pool and Retention all subscribe to this stream.

Each event carries: `event_type`, `schema_version`, `organization_id`, `entity_type`, `entity_id`, `application_id`, `actor_id` (or `system`), `correlation_id`, `sequence_number`, `payload`, `contains_pii`, `emitted_at`.

**Payloads carry identifiers and state transitions, never PII.** `DocumentSubmitted` carries the document type and record ID — never the file or the Aadhaar number. This keeps the event store outside the purge path.

### Feature Flags

Per organisation, Admin-managed. **Flags govern behaviour, never silent data destruction.**

| Flag | Off behaviour |
|---|---|
| `TalentPool` | Pooled profiles non-searchable, no new entries. Existing profiles retained, consent stands |
| `AICopilot` | Summaries hidden, no new generation; records retained for audit |
| `InternalNotes` | Existing notes read-only for Admin, hidden from other roles |
| `ConfigurablePipelines` | Falls back to the organisation default template; in-flight Applications keep their snapshot |
| `CrossRoundFeedbackVisibility` | Interviewers see only their own feedback |
| `AIScreening` | Screening performed manually by HR; identical records, events and states |
| `BackgroundVerification` | Stage skipped; skip recorded on the timeline |
| `KitDispatch` | Stage skipped; for customers using their own gifting supplier |

---

## Roles & Permissions

**Roles:** HR, Hiring Manager, Interviewer, Employee (Referrer), Candidate, Admin, System/AI Agents.

Interviewer is a minimal-privilege role scoped to assigned rounds. A Hiring Manager may act as an Interviewer; a panel member need not hold Hiring Manager privileges.

**Capabilities are the enforcement primitive; roles are bundles of them.** This is what allows `approve_ctc_above_band` to be granted to a Finance stakeholder without inventing a Finance role (S4), and `view_unmasked_pii` to be restricted to designated HR only.

| Action | HR | Hiring Manager | Interviewer | Referrer | Admin |
|---|---|---|---|---|---|
| Create/edit JD | ✅ | ✅ | – | – | ✅ |
| Approve & publish job | ✅ default | Configurable | – | – | ✅ |
| Edit About/Perks templates | ✅ | – | – | – | ✅ |
| Add resume manually | ✅ | – | – | – | ✅ |
| Submit referral | – | – | – | ✅ | – |
| View own referral status | – | – | – | ✅ | – |
| Shortlist candidate | ✅ | ✅ | – | – | – |
| Schedule/reschedule interview | ✅ | ✅ | – | – | ✅ |
| Request interview reschedule | – | – | ✅ | – | – |
| Submit interview feedback | – | ✅ if assigned | ✅ | – | – |
| View others' round feedback | ✅ | ✅ | Flag-controlled | – | ✅ |
| Final round decision | ✅ | ✅ | – | – | – |
| Mark negotiation complete | ✅ | – | – | – | – |
| Approve CTC above band | Capability | – | – | – | ✅ |
| Generate offer letter | ✅ | – | – | – | – |
| Approve offer letter before send | ✅ | – | – | – | ✅ |
| Verify/reject submitted documents | ✅ | – | – | – | ✅ |
| **Submit documents on behalf of candidate** | ✅ | – | – | – | ✅ |
| View unmasked PII (Aadhaar/PAN/EPFO) | Designated only | – | – | – | ✅ |
| Initiate/resolve BGV flag | ✅ | – | – | – | ✅ |
| Configure CTC rules per entity | – | – | – | – | ✅ |
| **Configure kit profile & client kits** | ✅ | – | – | – | ✅ |
| Add/view internal notes | ✅ | ✅ | Own round only | – | ✅ |
| View AI Copilot summary | ✅ | ✅ | – | – | ✅ |
| Search/view Talent Pool | ✅ | ✅ own reqs | – | – | ✅ |
| Reactivate from Talent Pool | ✅ | – | – | – | ✅ |
| Merge duplicate profiles | – | – | – | – | ✅ |
| Configure pipeline templates | Input only | Input only | – | – | ✅ |
| Manage feature flags | – | – | – | – | ✅ |
| View audit log | Own actions | Own actions | – | – | Full |
| Export audit log / PII reports | Designated, logged | – | – | – | ✅ logged |
| Delegate own approval authority | ✅ | ✅ | – | – | ✅ |
| Manage roles/permissions | – | – | – | – | ✅ |

**Candidate actions** — view status, submit and resubmit documents, request reschedule, sign or decline the offer, withdraw, grant or revoke consent, download own documents — are exercised exclusively through the token-based candidate portal and are not rows in this matrix.

> `submit_documents_on_behalf` is new in V3.3. There was an HR path to add a resume manually but none to handle a candidate who emails documents directly, which happens on day one.

---

## Unified Candidate Lifecycle State Machine

```
Draft(job) → PendingApproval(job) → Published(job)
  → Applied → Parsed → Scored → Shortlisted
        ├─ Parse-Failed ──▶ (manual parse | HR re-upload) ──▶ Parsed
        ├─ Score-Failed ──▶ (retry | proceed unscored) ──▶ Shortlisted
        └─ Duplicate-Detected ──▶ (Merged | Confirmed-Distinct ──▶ Parsed)

  → Screening → Screened
        └─ Screening-Unreachable ──▶ HR outreach ──▶ (Screened | Rejected)

  → Round[N]: Scheduled → Completed → FeedbackSubmitted
        → (Next Round | Offer-Recommended | Rejected)
        └─ Cancelled / No-Show ──▶ (Rescheduled | Rejected)

  → Offer-Recommended → Negotiation → (CTC-Pending-Approval →) Negotiation-Complete

  → Documents-Requested → Documents-Partial → Documents-Submitted → Documents-Verified
     [Branch B, not built initially: Aadhaar-Capture → offer letter → documents after signing]

  → Offer-Letter-Drafted → Offer-Letter-Pending-Approval → Offer-Letter-Approved
  → Offer-Letter-Sent → (Offer-Signed | Offer-Declined | Offer-Expired)
     Offer-Expired → (Revoked | Reissued ──▶ Offer-Letter-Drafted, new version)

  → Joining-Date-Confirmed
  → BGV-Initiated → BGV-In-Progress
     → (BGV-Clear | BGV-Flagged → Flag-Under-Review → (Proceed | Conditional-Proceed | Rescind))
     → BGV-Incomplete-At-Joining ──▶ org policy ──▶ (Conditional-Proceed | Hold)

  → Onboarding-Kit-Triggered
     ├─ Awaiting-Kit-Readiness ──▶ (branding/stock ready) ──▶ Kit-Dispatched
     └─ Kit-Dispatched → Kit-Delivered
        └─ Kit-Dispatch-Failed ──▶ retry ──▶ (Kit-Dispatched | HR-Intervention)

  → (Onboarded | Joining-No-Show)
     Onboarded ──▶ [+90 days] ──▶ Employment-Record-Handed-Off ──▶ purged here
```

**Global transitions** from any non-terminal state: `Withdrawn`, `Rejected` (reason code required), `On-Hold` (inherited from the job posting).

**Terminal states:** Rejected → if consented → Talent-Pool · Withdrawn · Offer-Declined · Rescinded · Joining-No-Show · Onboarded.

**New in V3.3:** async failure states (`Parse-Failed`, `Score-Failed`, `Screening-Unreachable`) — parsing runs an LLM over candidate-supplied files and some fraction will fail; `Duplicate-Detected` given a state rather than only an event; `Awaiting-Kit-Readiness`; and the employment handoff terminus.

---

## Module 1: Job Description Creation

Input form → LLM draft from versioned templates → edit → approval gate → publish. JD versioning on post-publish edits; each Application stores the JD version it applied against. Job ID embedded in the auto-generated application form.

**Job board adapters:** Career Portal (native), Naukri (API, paid RMS subscription — see H-07), LinkedIn (manual posting package with attestation; no API at launch).

**Approval:** routes through the shared approval engine. The designated approver may delegate to a named alternate for a date range, and a delegate must independently hold the capability — delegation cannot manufacture authority. Unactioned approvals escalate after a configurable window (default 2 business days).

## Module 2: Resume Collection, Tagging & AI Scoring

Sources: applied, referred, hr_added. Dedup via normalised email, normalised phone, and resume-content fingerprint against Candidate Profile. Parsing once per Candidate Profile; scoring per Application.

**Scoring is advisory only.** Humans decide. This is a fairness requirement and simultaneously the control that caps the impact of prompt injection via resume content (B-06).

**Referrer feedback loop:** the referring employee is notified at exactly three milestones — referral received, shortlisted, outcome. Deliberately excludes feedback, scores and compensation.

A malformed or corrupt resume produces `Parse-Failed` with an HR-visible recovery path, never a silently stalled Application.

## Module 3: Screening → Interview Rounds

### Step A — Screening **[Manual at launch]**

HR performs the screening conversation and records the outcome. Identical Screening Call Record, identical events, identical state transition to the automated path.

**The automated path remains fully specified and unbuilt.** Two separately contracted layers, because an AI vendor cannot remediate a telephony vendor's compliance gap:

- **Layer 1 — Telephony (Exotel).** Indian DIDs, PSTN, DLT registration and template approval, DND scrubbing before every dial, CLI presentation, transport-layer recording with retention, outbound dialer, media streaming to Layer 2. All regulatory obligations for automated outbound voice sit here.
- **Layer 2 — Voice AI (deferred).** ASR, LLM orchestration, TTS, conversation graph, structured outcome capture.

Platform-side logic, unchanged and applying to both paths: retry policy of 3 attempts across different times of day over 2 days then escalate to HR; AI-voice disclosure and recording consent captured at call open and written to the Consent Log; candidate callback request to reschedule.

**Exotel is still integrated at launch for SMS**, so DLT template registration happens once regardless.

### Step B — Interview Rounds

Scheduling engine matches candidate slots to interviewer availability; no overlap escalates to HR.

**Configurable pipelines** per organisation and job family. The state machine is fixed; round count and type vary. The active template version is snapshotted onto the Application at shortlist — later template edits never alter in-flight candidates.

**Panel support:** multiple assigned Interviewers per round, each submitting independent feedback via their own Interviewer Assignment. The Hiring Manager decides the round, and that decision is recorded with a reason code on reject.

**Calendar:** native Google Workspace and Microsoft Outlook invites, created, updated and cancelled on schedule changes. Invite failure leaves the round visibly unconfirmed rather than silently proceeding.

**SLA:** feedback overdue (default 3 business days) triggers a reminder; a second miss escalates and emits `FeedbackSLABreached`. Tracked per interviewer, not per round.

**Default pipeline templates** (E-06) — deliberately short, since long pipelines drive drop-off:

| Job family | Rounds |
|---|---|
| Default (fallback) | Screening → Functional → Hiring Manager |
| Engineering | Screening → Technical 1 → Technical 2 → Hiring Manager |
| Sales / BD | Screening → Hiring Manager → Case or role-play → Leadership |
| Operations / Support | Screening → Functional → Hiring Manager |
| Leadership / Senior | Screening → Hiring Manager → Panel → Founder/CXO |
| Intern / Entry | Screening → Functional → Hiring Manager |

## Module 4: Offer Decision → HR Notification

Hiring Manager marks Offer-Recommended; HR notified via the centralised notification service. Parallel-pipeline detection surfaces the candidate's other open Applications and blocks progression until explicitly acknowledged, with the acknowledgement recorded.

## Module 5: Salary Negotiation

HR negotiates offline and records final CTC. Above-band values route to an Approval Request requiring `approve_ctc_above_band`, with delegation and escalation, before Module 7 proceeds.

**Interim rule (E-05): every offer routes to approval** until band thresholds are set. The policy version and the evaluated threshold value are both stamped onto the Negotiation Log, so a band check remains explicable after the policy is retired.

## Module 6: Document Collection

**Trigger:** negotiation complete (Branch A — the only ordering built initially).

Auto-generated form collects Aadhaar, PAN, marksheets (10th, 12th, graduation, post-graduation as separate instances), employment proof (multiple instances across prior employers), EPFO details, address proof and photograph.

Reminders at day 2, 5 and 8 against business days. HR rejection triggers a targeted resubmission request naming the document and reason; the rest of the form is not reset.

**HR-assisted submission** is supported for candidates who send documents directly, recorded with the acting user.

Formal compliance documents — strict retention, masking and access rules, distinct from Internal Notes. Unmasked access to Aadhaar, PAN and EPFO is restricted to designated HR and Admin, and **every read emits `SensitiveDataAccessed`**.

Address written here flows to Candidate Profile as source of truth; Dispatch Record holds a point-in-time snapshot.

## Module 7: Offer Letter Generation & Digital Signature

HR opens the templatised letter → CTC calculator generates the breakdown → approval gate → e-signature via Digio embedded in the candidate portal → candidate signs → HR enters confirmed joining date.

### CTC Structure (E-01)

Specified against the four Labour Codes, in force since 21 November 2025. The Code on Wages folds excluded allowances back into "wages" for PF, gratuity and bonus purposes if they exceed 50% of total remuneration — so basic must sit at or above 50%.

| # | Component | Rule |
|---|---|---|
| 1 | Basic Salary | **50% of CTC** — the Labour Code floor. Configurable upward, never below |
| 2 | House Rent Allowance | 50% of Basic (metro) / 40% (non-metro) |
| 3 | Special Allowance | Balancing figure |
| 4 | Employer PF | 12% of Basic, capped at the statutory wage ceiling |
| 5 | Gratuity | 4.81% of Basic |
| 6 | Employer ESI | 3.25% of gross, only where monthly gross is within the threshold |

Employee-side deductions are shown as an indicative net-pay illustration, not as CTC components.

**Two hard gates.** The breakdown must sum to CTC within ₹1. The Wage Code excluded-component check **blocks offer generation** rather than warning (E-02) — a silent pass becomes an EPFO demand notice with arrears months later.

Statutory parameters are dated configuration values, not constants (E-03). Rule sets are immutable version rows and the version is stamped onto the Offer, so a past offer remains reproducible after the rules change (E-04).

### Signature & Expiry

Aadhaar eSign is the signing method, embedded in the portal rather than a hosted handoff. Signature consent is captured in the Consent Log.

Configurable expiry set at send time, with reminders at T-3 and T-1 days. Unsigned letters move to Offer-Expired, after which HR revokes or reissues. **Reissue creates a new version** with fresh expiry; the prior version becomes Superseded and is retained for audit.

Offer-Declined is a distinct candidate-initiated outcome with an optional reason, separate from expiry and withdrawal.

`proposed_joining_date` appears in the letter; `confirmed_joining_date` is entered post-signature (S3).

## Module 8: Background Verification

**Trigger:** offer signed, joining date entered, and required documents available (S2).

**Precondition: `BackgroundVerification` consent, Granted and unexpired.** Enforced by a database constraint, not only in application code (C-09).

Checks: employment history, criminal record, education.

**Launch mode is manual entry** (D-05). HR runs verification through whatever agency they use today and records the outcome. Identical states, events and downstream behaviour. The AuthBridge adapter is built to the same interface and plugs in when the contract and the parallel SpringVerify pilot complete.

Flagged results route to HR with three outcomes — Proceed, Rescind, or Conditional Proceed with a hard follow-up deadline. Outcome and rationale logged; emits `BGVFlagResolved`.

If BGV is incomplete by the joining date, Admin-configured organisation policy determines conditional proceed or hold.

## Module 9: Onboarding Kit Dispatch **[First-party — core scope]**

Gifteko is the group's own corporate gifting business. This module is the reason the platform exists, not an optional integration.

**Trigger:** BGV resolved to Proceed or Conditional Proceed.

### Kit configuration — a customer onboarding step

Branding is embossing, laser engraving and brand-matched configuration: artwork, proof, approval, production. It happens **once per customer** and takes weeks. It is therefore set up alongside SSO and CTC configuration, not at dispatch time (D-10).

- **Kit Catalogue Item** — Gifteko-managed. Categories: Welcome Kits, Stationery, Drinkware, Premium Hampers, Office Essentials, Travel & Tech, Apparel. Tiers: Basic, Custom, Enterprise. **No price fields** — Gifteko prices by enquiry and quote, and commercials settle outside this system (D-11).
- **Organization Kit Profile** — brand assets, artwork proof and approval, readiness status, fulfilment mode, buffer stock levels, account manager.
- **Client Kit** — a configured bundle assigned by job family or designation band. Versioned; the version is snapshotted onto the Dispatch Record.

A dispatch triggered before readiness parks in `Awaiting-Kit-Readiness` and alerts, rather than failing at the boundary or shipping unbranded stock.

### Fulfilment modes (D-12)

The existing business is built for bulk multi-destination campaigns; an ATS produces single units trickling in as hires close. The mode is chosen per customer because it determines the dispatch SLA the platform can honestly promise.

| Mode | Behaviour | Suits |
|---|---|---|
| Buffer stock | Branded stock held per customer, pick-and-pack singles, reorder at threshold | Steady hiring |
| Weekly batching | Dispatches accumulate and ship weekly | Known joining dates, cost efficiency |
| Drop-ship per hire | Single unit per hire | Low or unpredictable volume |

Address re-confirmed with the candidate if stale beyond a configurable interval, then snapshotted. Dispatch failure retries with backoff, then alerts HR.

## Module 10: Talent Pool **[Flag off at launch]**

At rejection, with candidate consent, the profile is tagged Talent-Pool-eligible rather than scheduled for purge. Searchable by skills, past role and score history. Reactivation creates a new Application against the existing profile — never a duplicate.

Consent is revocable at any time via a link in every talent-pool communication and from the portal. Revocation removes the profile from the pool immediately and returns it to the standard retention clock. Consent carries a configurable validity period (default 24 months), after which the candidate is re-asked or the profile purges.

## Module 11: AI Hiring Copilot **[Flag off at launch — narrative outputs only]**

Per-Application advisory summary from existing resume, feedback and scoring data: summary, strengths, risks, suggested questions.

**`salary_fit_score` and `offer_confidence_score` are deferred** (D-02). No historical hiring outcome data exists, so predictive validity cannot be established. Narrative outputs are visibly checkable against the source data sitting next to them; opaque numbers touching compensation are not. At roughly 100–200 hires per year, credible subgroup analysis is years away.

**Shadow-mode generation runs from Phase 3** — generated and stored, surfaced to nobody — to build the validation corpus the project lacks. This is processing of candidate data and must appear in the privacy notice from day one (D-03).

**Fairness review is version-scoped.** Sign-off attaches to a Model Version, not to individual summaries. A new model version — or a prompt change, which counts as one — requires fresh sign-off before any output surfaces. Available fairness evidence without outcome data is counterfactual testing: hold a resume constant and vary only name, college or city, asserting output stability.

Humans remain decision-makers throughout.

---

## Candidate Experience

Candidates interact via a token-based portal. No SSO, no account creation. Secure expiring links scoped to a single Application, exchanged on first use for a short-lived scoped session cookie (B-01).

- View application status at a stage-appropriate level — never internal scores, feedback or notes
- Submit and resubmit documents
- Request an interview or screening reschedule
- Review and sign, or decline, the offer letter — embedded, not a hosted handoff
- Withdraw the application
- Grant or revoke consent
- Download own submitted documents and signed offer

Every candidate action emits a domain event and appears on the Timeline.

---

## Cross-Cutting Requirements

1. **Roles & permissions** — capability-based, Admin-managed, with delegation and escalation.
2. **Notifications** — centralised service driven by the event stream. Email, Slack, SMS. SMS runs through Exotel with DLT-registered, versioned templates; every SMS is attributable to a registered template ID.
3. **Candidate 360 View & Timeline** — chronological view of communication, workflow, approvals, reminders and system actions, each with timestamp, actor, source and record links. A read-layer over the event stream.
4. **Internal Notes & Attachments** — role-protected and audited, distinct from formal Document Submissions.
5. **Reporting & Dashboards** — operational (pending approvals, today's interviews, SLA breaches, BGV status, kit readiness, onboarding progress) and analytical (time-to-hire, funnel drop-off, source effectiveness, feedback turnaround), both role-based.
6. **Retention** — three clocks. See below.
7. **Candidate Merge** — Admin tool. Applications, documents and consents repoint to the survivor; audit entries retain original profile IDs and resolve through the merge chain. More restrictive consent wins. Merge blocked if both profiles hold live Applications on the same job.
8. **Audit trail** — every status change, feedback entry, approval, decision, note, consent action and merge logged immutably via an append-only hash chain, verified nightly.
9. **Data security** — AES-256 at rest, TLS 1.2+ in transit, field-level masking with capability-gated unmasking, permissioned and logged PII exports.

### Retention — three clocks (C-02 to C-07)

| Track | Trigger | Retention |
|---|---|---|
| **A — Non-joiner** | Rejected, Withdrawn, Declined, Rescinded, No-Show | **12 months** from terminal state |
| **B — Joiner** | Onboarded | **Employment Record Pack exported to the customer at +90 days, then purged here** |
| **C — Talent pool** | Rejected with consent | 24 months, re-askable. **Extends** Track A |

**Precedence:** longest applicable clock wins; reaching Onboarded moves an Application out of the candidate retention regime entirely; consent revocation collapses Track C to Track A rather than triggering immediate deletion; pool consent never extends document retention.

Purge removes identifying fields but preserves an anonymised Application Analytics Record — job, stage reached, source, dates, outcome, reason code. Analytics survive; PII does not.

**Track B rationale:** statutory employment retention runs to years and is measured from end of employment, an event this platform never observes. Rather than inherit an obligation it cannot discharge, the compliance pack is handed to the customer's system of record and destroyed here. Nothing is destroyed without a confirmed successful export.

---

## Vendor Positions

| Integration | Position | Status |
|---|---|---|
| E-signature | **Digio** (fallback Leegality) | Contracted. Aadhaar eSign is mandatory for Indian offer letters, which eliminates non-UIDAI platforms |
| Telephony + SMS | **Exotel** (fallback Ozonetel/Knowlarity) | Contracted. Carries DLT, DND, CLI and recording obligations. Live at launch for SMS |
| Voice AI | Deferred | Shortlist retained: Gnani, Sarvam, Bolna, SquadStack. Selection by live phone-line pilot when reopened, with residency as a gate |
| Background verification | **AuthBridge** (parallel pilot with SpringVerify) | Module built, contract deferred |
| Onboarding kit | **Gifteko** | **First-party.** Not a procurement decision |
| Job board — Naukri | API adapter, paid RMS | Under review (H-07) |
| Job board — LinkedIn | Manual posting package | No API at launch |
| Calendar | Google Workspace / Microsoft Outlook | Both adapters built |
| Team notifications | Slack | Fixed |
| Email | AWS SES | Commodity |
| Hosting | AWS Mumbai (ap-south-1), DR Hyderabad (ap-south-2) | Fixed |
| LLM inference | India-region endpoints only | Fixed |

**Pre-contract requirements** for every third-party processor: data processing agreement, DPDP compliance attestation, written India data-residency confirmation, breach-notification SLA, named support escalation path.

**Gifteko follows a different path.** Separate legal entities under common ownership means it is a **sub-processor**, not an internal transfer — common ownership is not a DPDP exemption. Required: a sub-processing agreement, disclosure in the customer DPA, notification rights on change, and flow-down of security and residency obligations (C-08).

---

## Non-Functional Requirements

**Data residency.** DPDP permits cross-border transfer by default, so India hosting is not strictly mandated. Adopted anyway: the platform stores Aadhaar, PAN and EPFO details, and India hosting is the expected posture in audit. Enforced by adapters failing closed on a non-India endpoint for any PII-bearing payload — a control, not a policy statement. Encryption keys held in India.

**Multi-tenancy.** `organization_id` on every entity, enforced by PostgreSQL row-level security with an application-layer guard as defence in depth. A two-tenant isolation assertion runs on every pull request, permanently.

**Also:** multi-entity configuration; SSO (SAML/OIDC) for internal roles with token-based candidate access; integration resilience (retry with backoff, dead-letter queues, signature-verified webhooks) applied to the event bus as well as external integrations; async job queues with defined failure states; spam and bot protection on the public form; backup and DR consistent with the retention policy.

**Volume assumption:** 500–1,000 applications per month at launch (E-07).

---

## Open Items

| # | Item | Owner | Interim position |
|---|---|---|---|
| 1 | Approval band thresholds per designation | HR/Finance | All offers route to approval |
| 2 | Wage Code 50% denominator confirmation | Legal | Computed against CTC; configurable |
| 3 | Gifteko sub-processor agreement and DPA disclosure | Legal | — |
| 4 | Kit branding onboarding for the design partner | Gifteko ops | **Multi-week lead time; gates first dispatch** |
| 5 | Permanent fairness sign-off owner | Leadership | Project lead, interim |
| 6 | Naukri RMS subscription justification | Product | Career portal live regardless |
| 7 | Catalogue categories confirmed against internal structure | Gifteko ops | Inferred from the public catalogue |

---

*Sealed 30 August 2026. Supersedes V3.2. Changes require a Decision Log entry (01).*

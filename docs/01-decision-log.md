# Employee Onboarding & Recruitment Platform
# 01 — Decision Log

**Last updated:** 30 August 2026
**Status:** Living document. Every change to a sealed document requires an entry here.

The purpose of this log is that a year from now, someone can reconstruct why the system looks the way it does — including the decisions that were reversed, and the ones we got wrong first time.

**Reversibility ratings:** **Hard** — changing it means significant rework. **Moderate** — a contained migration. **Easy** — configuration or a small change.

---

## A. Architecture & Technology

| ID | Decision | Rationale | Reversibility |
|---|---|---|---|
| **A-01** | Python 3.12 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 | Team fluency; strongest ecosystem for LLM orchestration and document parsing, which is where the difficult work sits | Hard |
| **A-02** | PostgreSQL 16, row-level security as the multi-tenancy mechanism | Tenant isolation enforced at the database rather than in application code, so an unscoped query is impossible by construction | Hard |
| **A-03** | Modular monolith, not microservices | The event bus already provides decoupling. Microservices would add distributed transactions and eleven pipelines for a small team. Module boundaries enforced in code, so the seams exist if a split is ever needed | Hard |
| **A-04** | React + TypeScript for the internal application | Substantial SPA — pipeline views, timeline, scheduling, dashboards. The one place the Python stack cannot reach | Hard |
| **A-05** | Jinja2 + HTMX for the candidate portal | Six screens, token-authenticated, must work on low-end Android over patchy connections. Server rendering keeps the token boundary server-side and the payload small. Stays in Python | Moderate |
| **A-06** | Transactional outbox → EventBridge → per-consumer SQS | Outbox guarantees the event commits with the state change. EventBridge gives content-based routing; per-consumer queues give real DLQs | Moderate |
| **A-07** | Celery on SQS for async work | Mature and well documented. Dramatiq was genuinely close on API quality; Celery won on ecosystem | Easy |
| **A-08** | PostgreSQL full-text search for Talent Pool. **No OpenSearch** | 6–12k profiles/year is three orders of magnitude below where a search cluster is needed. Avoids a second system in the purge path, which is where compliance gaps come from | Easy |
| **A-09** | Direct SAML/OIDC service provider implementation | Per-organisation IdP config is a core multi-tenant requirement, and every SSO-as-a-service option is hosted outside India. Keycloak in-region was the alternative; rejected as a permanent operational commitment | Moderate |
| **A-10** | No LLM orchestration framework — direct Bedrock SDK | LangChain-style abstraction makes prompt pinning, model-version stamping and per-call region assertion harder. All three are hard requirements here | Easy |
| **A-11** | Terraform with a **self-managed S3 state backend in ap-south-1** | Confirmed once dedicated DevOps capacity was on the team — the one-language argument for CDK Python no longer applied. Terraform Cloud rejected: US-hosted, and state carries infrastructure topology | Hard |
| **A-12** | ECS Fargate | No cluster to manage at this scale | Moderate |
| **A-13** | Self-hosted Sentry or GlitchTip in-region | Sentry SaaS is out-of-region and error payloads carry request data. A residency decision, not a preference | Easy |
| **A-14** | Feature flags in our own table, no third-party service | Already modelled with the audit fields required; third-party flag services are out-of-region | Easy |

## B. Security

| ID | Decision | Rationale | Reversibility |
|---|---|---|---|
| **B-01** | Portal token **exchanged on first use** for a scoped session cookie; token in path, never query string | The candidate boundary is a bearer credential in an email. Query strings leak via access logs, analytics and `Referer` headers. Exchange means the token is transmitted once | Hard |
| **B-02** | Object-level authorisation resolved in one middleware layer from the authenticated principal, never from a request parameter | IDOR is the platform's top-ranked threat — every meaningful URL carries an application, candidate or document ID | Hard |
| **B-03** | User-uploaded files served from a separate S3 domain, never the app origin | SVG and HTML uploads are executable. Serving them same-origin is stored XSS against HR users | Moderate |
| **B-04** | ClamAV scan on upload with a quarantine bucket | Resumes are attacker-supplied files | Easy |
| **B-05** | AWS WAF with OWASP managed rules and bot control | The application form is unauthenticated and internet-facing | Easy |
| **B-06** | LLM output has **no authority** — never drives a state transition, authorisation decision or approval | Neutralises prompt injection via resume content. Written as a fairness requirement; it doubles as the security control | Hard |
| **B-07** | Penetration test before go-live, annually thereafter. Vendor booked in Phase 8 | Good testers are scheduled months ahead | Easy |
| **B-08** | Audit Log is append-only with a hash chain, verified nightly | "Immutable" needs a mechanism, not an adjective | Moderate |

## C. Compliance & Data Protection

| ID | Decision | Rationale | Reversibility |
|---|---|---|---|
| **C-01** | India-region hosting and India-region LLM inference | DPDP permits cross-border transfer by default, so this is not strictly mandated. Adopted anyway: the platform stores Aadhaar, PAN and EPFO details, and India hosting is the expected posture in audit. Residency enforced by adapters failing closed, not by policy prose | Hard |
| **C-02** | Retention runs on **three clocks**, not one | A single period cannot express the difference between a rejected candidate and a hired employee | Hard |
| **C-03** | Non-joiner retention: **12 months** from terminal state | Long enough to answer a discrimination challenge or a candidate query; short enough to limit exposure | Easy |
| **C-04** | Joiner track: **Employment Record Pack handed off to the customer at Onboarded + 90 days, then purged here** | Statutory employment retention runs to years and is measured from end of employment — an event this platform never sees. Moving the obligation is correct; inheriting it would mean holding the highest-sensitivity data indefinitely for no product reason | Hard |
| **C-05** | Talent pool: 24 months consent validity, **extends** the non-joiner clock rather than running alongside it | Longest applicable clock wins. Otherwise consent is meaningless | Easy |
| **C-06** | Pool consent never extends **document** retention | Consenting to be considered for future roles is not consenting to keep your Aadhaar on file | Easy |
| **C-07** | Backup retention set from the longest active clock | A backup outliving the retention window makes the purge cosmetic | Easy |
| **C-08** | Gifteko treated as a **sub-processor**, disclosed in the customer DPA | Separate legal entities under common ownership. Common ownership is not a DPDP exemption; the hiring customer is the Data Fiduciary and the platform is their Processor | Hard |
| **C-09** | BGV requires its own consent type, enforced by a database constraint | Background verification was the most consent-sensitive processing in the platform and had no consent record at all | Moderate |

## D. Product Scope

| ID | Decision | Rationale | Reversibility |
|---|---|---|---|
| **D-01** | **AI voice screening deferred.** HR performs screening manually at launch | Building in-house is a research-grade problem; buying is premature without evidence. Manual screening produces the transcript corpus that will answer the buy/build question properly. Telephony and voice-AI adapter interfaces are preserved behind an `AIScreening` flag — reintroduction is an implementation plus a flag flip | Easy — deliberately |
| **D-02** | **AI Copilot ships narrative outputs only.** `salary_fit_score` and `offer_confidence_score` deferred | No historical hiring outcome data exists, so predictive validity cannot be established. Narrative outputs are visibly checkable next to the source data; opaque scores touching compensation are not. At ~100–200 hires/year, credible subgroup analysis is years away | Easy |
| **D-03** | Shadow-mode Copilot generation from Phase 3 — generate and store, surface nothing | Builds the validation corpus the project lacks, from real pipeline data. Must be disclosed in the candidate privacy notice from day one; retrofitting that is not possible | Easy |
| **D-04** | **Gifteko kit dispatch ships at launch.** Not deferrable | First-party — the group's existing corporate gifting business and the reason this platform exists. Deferring it would ship the generic half of the system and omit the differentiator. *This reverses an earlier recommendation made when Gifteko was mistakenly treated as a third-party vendor* | Hard |
| **D-05** | **BGV module ships; AuthBridge contract defers.** Manual-entry mode at launch | An ATS without background verification is visibly incomplete. What genuinely defers is the vendor contract and the 20–30 candidate parallel pilot — a procurement exercise, not a build task. Same state machine, same events, adapter plugs in later | Easy |
| **D-06** | Every vendor-dependent stage is **skippable by feature flag**, with the skip recorded on the timeline | Turns scope decisions into configuration rather than rework. Generalised from the voice deferral | Moderate |
| **D-07** | Document-phase ordering: **Branch A only** (documents before offer letter) pre-raise | Branch B built as configuration so it is additive later, but not implemented until a customer asks | Moderate |
| **D-08** | **Design partner with real hires**, not a controlled demo | A demo shows the product works; a partner hiring through it shows whether it is worth paying for. Accepts that the full compliance floor ships early | Hard |
| **D-09** | LinkedIn: manual posting package, no API at launch | Recruiter System Connect requires Talent Solutions Partner approval — months-long with low acceptance | Easy |
| **D-10** | Kit readiness (branding artwork, proof, approval, production) is a **Phase 2 customer-onboarding step**, not a Phase 7 dispatch step | Happens once per customer with a multi-week lead time. Modelled at dispatch time, the first real dispatch would fire against stock that does not exist | Moderate |
| **D-11** | No kit pricing in the platform | Gifteko prices by enquiry and quote and publishes no rates. Commercials settle outside the system — removes a pricing engine from scope entirely | Easy |
| **D-12** | Three fulfilment modes per customer: buffer stock, weekly batching, drop-ship per hire | Existing fulfilment is built for bulk multi-destination campaigns; an ATS produces single units trickling in. The choice determines what dispatch SLA can honestly be promised | Moderate |

## E. Business Rules

| ID | Decision | Rationale | Reversibility |
|---|---|---|---|
| **E-01** | **CTC V1: Basic at 50% of CTC**, HRA at 50%/40% by metro status, Special Allowance as balancing figure, employer PF at 12% capped at ceiling, gratuity at 4.81%, employer ESI conditional | The four Labour Codes came into force 21 November 2025. Under the new wage definition, excluded allowances exceeding 50% of total remuneration are folded back into wages for PF, gratuity and bonus. Structures keeping basic at 30–40% no longer work | Moderate |
| **E-02** | Wage Code validation **blocks offer generation**, it does not warn | A silent pass becomes an EPFO demand notice with arrears and interest months later | Easy |
| **E-03** | Statutory parameters (EPF ceiling, ESI threshold, gratuity rate) are **dated configuration values**, not constants | They change by notification. The EPF ceiling increase has been repeatedly deferred and sources conflict on current status | Easy |
| **E-04** | CTC rule sets and approval band policies are **immutable version rows**; the version is stamped onto Offer and Negotiation Log | An offer letter is a legal instrument and must be reproducible after the rules change | Hard |
| **E-05** | Approval bands: **interim default is that every offer routes to approval** until thresholds are set | Safe, configurable, and removes an undecided business input from the critical path | Easy |
| **E-06** | Six default pipeline templates proposed (default, engineering, sales, operations, leadership, entry) — deliberately short | Long pipelines drive candidate drop-off. Templates are versioned and snapshotted at shortlist, so HR can revise freely without touching in-flight candidates. They need to be reasonable, not right | Easy |
| **E-07** | Volume assumption: **500–1,000 applications/month** at launch | Confirms Postgres FTS, sizes infrastructure, and establishes that vendor negotiation should target no minimum commitment rather than a lower unit rate | Easy |

## F. Process

| ID | Decision | Rationale |
|---|---|---|
| **F-01** | Spec and SDD are sealed; changes require a Decision Log entry | Makes change visible rather than preventing it |
| **F-02** | Two-tenant isolation suite in CI from week 2, permanently | Cross-tenant leakage is the worst available failure. It is asserted continuously, not reviewed |
| **F-03** | QA capability from Phase 1, not Phase 8 | The cross-cutting suites run from the moment the platform core exists |
| **F-04** | Team sizing owned outside this documentation set | Capacity assumptions are recorded only so timelines can be rescaled |
| **F-05** | Every phase is audited against the roadmap's own deliverable list before the next phase starts | A phase-completion audit before Phase 2 found three Phase 1 items silently skipped — Candidate Portal Token, notification service, SAML/OIDC. All three were in the roadmap's Phase 1 bullet list. Counting units built is not the same as checking them against what the phase was defined as |
| **F-06** | Anything deferred gets an entry in section I with a named trigger | Same finding. The three gaps were not decisions, they were omissions, and an omission looks exactly like a deferral until someone checks |

---

## I. Deferred with triggers

Things deliberately not built yet, each with the event that makes them required.

**A deferral without a trigger is forgetting.** This section exists because that
happened: three Phase 1 deliverables were quietly skipped and only found by an
audit before Phase 2. The trigger column is the point of the table — an item
here without one should be treated as an open bug in this log.

| ID | Deferred | Why it was safe to defer | Trigger — required by |
|---|---|---|---|
| **X-01** | **SAML/OIDC service provider.** `IdentityProviderConfig` is modelled; the flow is not built. Authentication runs on the development stub | The stub is hard-gated to `APP_ENV=local` with three independent guards plus a CI warning. Everything through Phase 5 is demonstrable locally | **The design partner's first login.** Nothing outside the team can authenticate until this exists. Budget two weeks (ADR-006) |
| **X-02** | **Candidate Portal Token.** Designed in ADR-010, not implemented | Nothing before Module 6 touches a candidate-facing surface | **Phase 6 — document collection.** It is the entire candidate security boundary; Module 6 cannot ship without it |
| **X-03** | **Real notification channel adapters** (SES/SendGrid, Slack, Exotel) | The service, template resolution, DLT gating and logging are complete and tested against a recording adapter. Only the final hop is stubbed. Unconfigured channels log `Suppressed`, not `Failed` | **Vendor contracts.** Exotel additionally blocked on DLT registration, which is the longest external lead time in the project |
| **X-04** | **Terraform, WAF, VPC endpoints, per-service IAM** | Nothing is deployed. There is no environment for these to protect | **First deployed environment.** Phase 0's security baseline lands with it, not before |
| **X-05** | **semgrep and Trivy in CI.** `bandit` and `pip-audit` are wired; these two are not | Bandit covers Python static analysis; Trivy scans container images, and no image is built yet | **semgrep: next CI change** (it is ten minutes). **Trivy: first container build** |
| **X-06** | **EventBridge publisher adapter.** The `EventPublisher` interface and an in-process implementation exist | The outbox, relay, consumer idempotency and DLQ handling — the parts with real bugs in them — are identical either way | **First deployed environment** |
| **X-07** | **Per-organisation weekend configuration.** `business_days` supports it; nothing writes it | Saturday/Sunday is correct for the design partner. Six-day weeks and working-Saturday exceptions are supported in the calculation | **First customer with a six-day week.** Data change, not code |

---

## G. Reversed decisions

Kept deliberately. A decision log that only records what survived is a marketing document.

| ID | Original | Revised to | Why it was wrong |
|---|---|---|---|
| **G-01** | Defer Gifteko kit dispatch behind a flag, alongside AuthBridge | **Ships at launch** (D-04) | Gifteko was treated as a third-party vendor carrying a contract, DPA, residency attestation and per-unit cost. It is first-party — the existing business this platform extends. The recommendation optimised away the differentiator |
| **G-02** | Defer AuthBridge entirely pre-raise | **Module ships, contract defers** (D-05) | The functional objection was right: an ATS without BGV is visibly incomplete, and BGV sits on the critical path between offer and dispatch. Splitting module from vendor preserves completeness at no build cost |
| **G-03** | CTC as "Fixed less EPF less cess" | **Labour Code-compliant structure** (E-01) | Cess is a surcharge on income tax deducted from the employee, not a CTC component. More fundamentally, the whole shape predated the Labour Codes coming into force |
| **G-04** | Retention: single period, six months | **Three clocks** (C-02 to C-07) | A single period cannot distinguish a rejected candidate from a hired employee, and would have purged employment records well inside their statutory life |
| **G-05** | Joiner records retained for the statutory period | **Handoff at +90 days, then purge** (C-04) | The statutory clock runs from end of employment, which this platform never observes. "Retain for N years from exit" degrades into retain-forever |
| **G-06** | Terraform vs CDK Python left genuinely open | **Terraform confirmed** (A-11) | The CDK case rested entirely on having no dedicated DevOps capacity. That premise was wrong |
| **G-07** | `kit_type` as a bare string on Dispatch Record | **Kit Catalogue Item, Client Kit, Organization Kit Profile** | The model was generic in the one area where the product has a real differentiator, and had no representation of branding lead time |
| **G-08** | Reuse a running PostgreSQL for tests via `TEST_DATABASE_URL`, to skip container startup | **Reverted.** The suite always starts a throwaway container | The implementation ran `DROP SCHEMA public CASCADE` on a database other connections were attached to. PostgreSQL terminates those connections and asyncpg reports `unexpected connection_lost()` — every test errored. The failure mode existed *only* on the path the feature was meant to accelerate, which is the path that was never exercised before shipping it. Twenty seconds a run did not justify a second code path through test setup |

---

## H. Open decisions

| ID | Question | Owner | Needed by | Interim position |
|---|---|---|---|---|
| **H-01** | Approval band thresholds per designation and entity | HR/Finance | No deadline | All offers route to approval (E-05) |
| **H-02** | Wage Code 50% denominator — total CTC or gross excluding employer PF and gratuity? | Legal | Before Phase 6 | Engine computes against CTC (conservative); denominator is configurable |
| **H-03** | Gifteko sub-processor agreement and customer DPA disclosure | Legal | Before first customer | — |
| **H-04** | Arm's-length commercial terms between the two entities, in writing | Legal/Finance | Before diligence | — |
| **H-05** | Kit branding onboarding for the design partner | Gifteko ops | **Week 4** | Multi-week lead time; gates the first dispatch |
| **H-06** | Permanent fairness sign-off owner | Leadership | Before scale | Project lead, interim. A reviewer assessing their own system is a weak control |
| **H-07** | Naukri RMS subscription — justified at launch volumes? | Product | Week 12 | Career portal is live; Naukri may not earn its cost initially |
| **H-08** | Catalogue categories and tiers confirmed against Gifteko's internal structure | Gifteko ops | Before Phase 2 | Inferred from six featured products on the public site |

---

## I. Deferred build items

Work that is designed and specified but deliberately not built yet. Every entry
names a **trigger** — the condition that makes it required — because a
deferral without one is indistinguishable from forgetting.

That is not hypothetical. An audit before Phase 2 found three items from the
Phase 1 deliverable list absent, and they were absent precisely because they had
been deferred implicitly rather than recorded here. One of them, the
notification service, turned out to block Phase 2.

| ID | Item | Designed in | Trigger | Estimate |
|---|---|---|---|---|
| **I-01** | **SAML 2.0 / OIDC service provider.** Per-organisation IdP configuration, JIT provisioning, session establishment | ADR-006, SDD §B4. `IdentityProviderConfig` model exists; no flow | **Before the design partner's first login.** Nobody outside the team can authenticate until this exists | ~2 weeks |
| **I-02** | **Candidate Portal Token.** Issue, hash, scope, expire, revoke, validate; exchange-on-first-use for a scoped session cookie | ADR-010, SDD §B5. Not built | **Before Phase 6** (document collection). It is the entire candidate-facing security boundary | ~1 week |
| **I-03** | **Real notification channel adapters.** SES or SendGrid, Slack, Exotel SMS | SDD §3.10–3.11. Service, template resolution, DLT gating and logging are complete; only the final hop is stubbed | **Email: before the design partner.** SMS: after DLT registration completes (Track B, week 10) | ~3 days each |
| **I-04** | **EventBridge publisher.** Currently in-process dispatch behind the same interface | ADR-004, SDD §2.2 | **Before deployment.** Local and CI need no message bus | ~2 days |
| **I-05** | **Terraform / infrastructure.** VPC, RDS, ECS, WAF, VPC endpoints, IAM roles, in-region Terraform state | ADR-009, ADR-014, Roadmap Phase 0 | **Before anything is deployed.** Nothing runs outside a laptop today | ~1 week |
| **I-06** | **semgrep and Trivy in CI.** Roadmap names both; CI currently runs bandit and pip-audit | Roadmap Phase 0, SDD §1.4 | Cheap now, no dependency. Do it opportunistically | ~1 hour |

### The development auth stub

**I-01 has a companion that must be deleted, not merely superseded.**
`platform_core/auth/dev_stub.py` resolves the tenant and user from HTTP headers
— the exact vulnerability row-level security exists to prevent. It is currently
held in place by four independent guards: an import-time environment check, a
startup check in the app factory, a test asserting the first guard fires, and a
CI step that warns while the file exists.

When I-01 lands, the file is **deleted**. A guard left in place is a guard
someone can weaken. Everything to remove is tagged `PHASE1-AUTH-REMOVE-DEV-STUB`.

---

## J. Process decisions

| ID | Decision | Rationale |
|---|---|---|
| **J-01** | Branch protection on `main` deferred | With one contributor and `ci-prep.ps1` run before every push, a pull request with zero required approvals is ceremony rather than review. **Trigger: the second person who can push** — most likely the frontend engineer in Phase 2 — or a design partner running real hires, whichever comes first |
| **J-02** | Every phase ends with an audit against the roadmap's own deliverable list, not against what was built | The Phase 1 audit found three gaps. Checking work against memory of the work is not a check |
| **J-03** | A change to test infrastructure is exercised on the path it changes, before it ships | G-08. A test-setup optimisation was written, documented and handed over without once being run in the configuration it enabled. Its only failure mode lived there |

---

*Entries are append-only. A superseded decision moves to section G with its reversal recorded; it is never deleted.*

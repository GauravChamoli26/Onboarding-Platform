# Employee Onboarding & Recruitment Platform
# 06 — Technology Stack & Build Roadmap

**Companion to:** Build Spec V3.2 (sealed) and SDD 2.0
**Purpose:** a single document to sign off on. Every stack row below is a decision with a named alternative, so you can accept, reject, or defer each one rather than inheriting a stack by default.
**Assumed team:** 7 people (see Part 5). Timelines scale roughly linearly below that and not at all above about 10.

---

## Part 1. Stack Decisions

Three constraints shape almost every choice here, and it's worth stating them up front because they rule out otherwise-obvious options:

1. **India data residency.** This eliminates most SaaS developer tooling that would normally be a default — error tracking, feature flags, SSO-as-a-service, managed observability. Anything that receives candidate data, error payloads included, has to be in-region or self-hosted.
2. **Python-first team.** The stack is chosen so that everything except the browser is Python.
3. **Small team, long roadmap.** Favour boring, well-documented tools over anything requiring specialist operational knowledge.

### 1.1 Core application

| Layer | Decision | Why | Alternative considered |
|---|---|---|---|
| Language | **Python 3.12** | Team fluency; strongest ecosystem for LLM orchestration and document parsing, which is where the hard work is | Node/TypeScript — would unify with frontend but discards the team's strongest skill |
| API framework | **FastAPI** | Async-native (needed for vendor webhooks and LLM calls), OpenAPI generated from code, Pydantic-native | Django + DRF — better admin scaffolding, worse async story, heavier ORM coupling |
| Data model | **SQLAlchemy 2.0** (typed ORM) | Explicit control over the constraints and triggers in SDD §1.13; RLS works cleanly | Django ORM, Tortoise, raw SQL |
| Migrations | **Alembic** | Pairs with SQLAlchemy; the immutability triggers need hand-written migration steps | — |
| Validation & contracts | **Pydantic v2** | One schema layer for API request/response, event envelopes, LLM structured output, and vendor payloads | Pure dataclasses + manual validation |
| Database | **PostgreSQL 16** (RDS Multi-AZ) | Row-level security is the multi-tenancy mechanism (SDD §6.2); JSONB for rule sets and payloads; full-text search for the talent pool | MySQL — no RLS, weaker JSON |
| Task queue | **Celery** on **SQS** | Mature, well-documented, large hiring pool. Handles parsing, scoring, notifications, calendar sync, retention | **Dramatiq** — cleaner API and better defaults, smaller community. Genuinely close; pick Celery for the ecosystem |
| Scheduled jobs | **EventBridge Scheduler → SQS → Celery** | SLA sweeps, reminders, offer expiry, consent expiry, retention runs | Celery Beat — needs a singleton process, which is a failure mode |
| Event bus | **Transactional outbox → relay → EventBridge → SQS per consumer** | Outbox guarantees the event commits with the state change; EventBridge gives content-based routing so consumers subscribe to patterns, not to everything; per-consumer SQS gives the DLQs SDD §2.2 requires | SNS fan-out (no filtering richness); Kafka/MSK (operationally heavy for this volume) |
| Cache | **ElastiCache Redis** | Session data, rate limiting, free/busy lookups, idempotency keys | — |
| Object storage | **S3, SSE-KMS**, separate keys for documents / recordings / exports | Per SDD §6.4 | — |

### 1.2 The search decision — deliberately boring

**Start with PostgreSQL full-text search plus `pg_trgm`.** Do not provision OpenSearch.

The Talent Pool needs search by skills, past role, and score history — structured fields against what will be thousands, not millions, of profiles for years. Postgres handles that comfortably, and it keeps the data inside one residency boundary, one backup policy, and one purge path. Adding a search cluster now means the retention job has to delete from two systems and prove it, which is exactly the kind of complexity that produces a compliance gap.

Revisit if profile counts pass roughly 500k or fuzzy semantic search becomes a product requirement.

### 1.3 Authentication — where residency bites hardest

| Need | Decision | Why |
|---|---|---|
| Internal SSO (SAML 2.0 / OIDC) | **Implement the SP directly**: `Authlib` for OIDC, `python3-saml` for SAML | Per-organisation IdP config (SDD §B4) is a core multi-tenant requirement, and off-the-shelf multi-tenant SSO products are all out-of-region |
| Candidate access | **Own implementation** — Candidate Portal Token (SDD §B5) | No account, no IdP. Hashed, scoped, expiring tokens |
| Session management | Signed cookies for the internal app, short-lived JWTs internally | — |

**What this rules out and why it matters:** WorkOS, Auth0, Clerk and Cognito's federation would each solve per-tenant SSO faster, but they're US or EU hosted and would sit in the authentication path for data covered by your residency posture. Keycloak self-hosted in ap-south-1 is the one viable off-the-shelf option — take it if you'd rather run a container than maintain SAML code, but it's a real operational commitment. **My recommendation is direct implementation**, because SAML SP code is well-trodden and mostly write-once, whereas Keycloak upgrades are forever.

Budget two weeks for this and don't underestimate it. Enterprise customers will each have their own IdP quirks.

### 1.4 Application security

SDD §6.4 covers data security — encryption, masking, export controls. This section covers the application layer: what an attacker actually reaches first. Every control below is a build task with a phase in Part 2, not a policy statement.

#### Threat model — what this platform is actually exposed to

Ranked by likelihood × impact for this system specifically, not generic OWASP order.

| # | Threat | Why it ranks here | Control |
|---|---|---|---|
| 1 | **Broken object-level authorisation (IDOR)** | Every meaningful URL carries an application, candidate, or document ID. One missing ownership check exposes another candidate's Aadhaar | Authorisation resolved in one middleware layer from the authenticated principal, never from a request parameter. Every object-scoped endpoint has a negative test |
| 2 | **Cross-tenant leakage** | Multi-entity by design; the worst possible failure | RLS at the database, enforced per connection. Two-tenant assertion suite on every PR (§1.8) |
| 3 | **Portal token leakage** | The entire candidate boundary is a link in an email. Links leak via forwarding, browser history, server access logs, and `Referer` headers | See "Portal token handling" below |
| 4 | **Prompt injection via resume content** | Under-appreciated and specific to this platform. A candidate can embed instructions in a resume — white text, metadata, or a footer — aimed at the parser, the scorer, or the Copilot | See "LLM input handling" below |
| 5 | **Stored XSS via uploaded files and parsed text** | Resumes are attacker-supplied files rendered back into an HR user's browser. SVG and HTML uploads are executable | Serve all user files from a separate S3 domain via short-TTL pre-signed URLs, never from the app origin. `Content-Disposition: attachment`. Sanitise parsed text before render |
| 6 | **Insider PII access** | Designated HR can unmask Aadhaar/PAN/EPFO. The risk is misuse, not breach | Every unmask emits `SensitiveDataAccessed`; exports watermarked and emit `PIIExported`; anomaly alerting on unmask volume per user |
| 7 | **Webhook spoofing** | Six vendors post state changes that advance the pipeline. A forged `OfferSigned` is a serious problem | Signature verification mandatory, timestamp window to defeat replay, vendor IP allowlist where supported. Unverified payloads rejected and emit `VendorWebhookVerificationFailed` |
| 8 | **SSRF** | Resume parsing and vendor callbacks both handle attacker-influenced URLs | No outbound fetch from parsed content. Egress allowlist at the VPC level |
| 9 | **Public form abuse** | The application form is unauthenticated and internet-facing | WAF rate limiting, CAPTCHA, honeypot, per-IP throttling |

#### LLM input handling — prompt injection

This deserves its own treatment because the platform runs candidate-supplied text through four LLM paths (parsing, scoring, Copilot, and possibly voice reasoning), and the naive design lets a candidate influence their own evaluation.

| Control | Implementation |
|---|---|
| Untrusted-content delimiting | Candidate text is passed as clearly bounded input, never concatenated into the instruction portion of a prompt |
| Structured output only | Every LLM response is parsed into a Pydantic model. Free-text that fails schema validation is a failure, not a fallback |
| No authority | LLM output never drives a state transition, an authorisation decision, or an approval. Scoring is advisory by spec — that property is a security control, not just a product choice |
| Bounded values | Scores clamped to range; rationale length-capped; no field accepts arbitrary text into a privileged context |
| Detection | Log and flag resumes whose extracted text contains instruction-like patterns; surface to HR rather than silently discarding |
| Regression tests | A corpus of injection-styled resumes runs in CI, asserting scores stay stable |

The single most important line there: **scoring is advisory and humans decide**. That was written as a fairness requirement, and it happens to also neutralise the impact of a successful injection.

#### Portal token handling

The candidate portal token is the platform's weakest link by design — an unauthenticated bearer credential delivered by email.

- **Exchange on first use.** The link token is single-use for exchange; the browser receives a short-lived, `HttpOnly`, `SameSite=Lax` session cookie scoped to that Application. The token itself is never repeatedly transmitted or replayed.
- **Token in path, never query string.** Query strings land in access logs, analytics, and `Referer` headers.
- **`Referrer-Policy: no-referrer`** on all portal pages, so an embedded vendor iframe never receives the URL.
- Hashed at rest, constant-time comparison, purpose-scoped, expiring, revoked on terminal application states.
- Rate-limited per token and per IP; validation failures alert above threshold.

#### Standard controls

| Area | Decision |
|---|---|
| Edge | **AWS WAF** on ALB/CloudFront — OWASP managed rule set, rate-based rules, bot control on the public form. Shield Standard |
| Network | Private subnets; no public database; VPC endpoints for S3, Secrets Manager and Bedrock so PII traffic never traverses the internet |
| IAM | Per-service task roles, least privilege. No shared credentials between `api`, workers, and relay |
| Injection | SQLAlchemy parameterisation throughout; raw SQL only in reviewed migrations, never built from input |
| CSRF | Required for the server-rendered candidate portal — synchroniser tokens on every state-changing form |
| Headers | CSP with an explicit `frame-src` allowance for the Digio embed; HSTS; `X-Content-Type-Options`; `frame-ancestors 'none'` on the internal app |
| Uploads | Content-sniffed type allowlist (not extension), size caps, **ClamAV scan before storage**, quarantine bucket until clean |
| Secrets | AWS Secrets Manager with rotation; no secrets in the repo, images, or task definitions |
| Logging | PII redaction in the log formatter itself. Tokens, Aadhaar, PAN and file contents never reach CloudWatch |
| Dependencies | `pip-audit` and `npm audit` in CI; Renovate for updates; SBOM generated per release |
| Static analysis | `bandit` + `semgrep` in CI, blocking on high severity |
| Containers | Trivy scan on build; ECR scan on push; distroless or slim base images |
| Dynamic testing | OWASP ZAP baseline scan against staging, nightly |
| Backups | Encrypted, in-region, retention aligned to the purge policy (§4.6 of the SDD) — a backup outliving the purge window makes the purge cosmetic |

#### Security in the delivery process

- **Threat model refreshed per phase**, not once. Each phase adds a new attack surface — Phase 3 adds file upload, Phase 5 adds inbound telephony webhooks, Phase 7 adds the highest-sensitivity documents in the system.
- **Negative tests are acceptance criteria**, not a separate security backlog. The cross-cutting suites in SDD §7.0 already include tenant isolation, PII masking, idempotency and token security.
- **Penetration test before go-live and annually.** Book the vendor by Phase 8 — good testers are booked months out, and finding one in Phase 10 is how launches slip.
- **Incident response runbook and DPDP breach-notification path** written and rehearsed before launch. The notification SLA is contractual with your vendors; yours to the regulator and to candidates needs an owner and a clock.
- **Vulnerability disclosure contact** published before the public application form is live.

### 1.5 AI and document processing

| Layer | Decision | Notes |
|---|---|---|
| LLM access | **`boto3` → AWS Bedrock (ap-south-1)** | Confirm which models are actually available in Mumbai at build time — regional model availability changes and is not the same as service availability |
| Structured output | **Pydantic models + `instructor`** (or plain tool-use with Pydantic parsing) | Every LLM output that enters the database is validated against a schema. No free-text parsing |
| Orchestration framework | **None** | Deliberate. LangChain and LlamaIndex add abstraction that makes prompt pinning, model version stamping, and per-call region assertion harder — all three are hard requirements here (SDD §J2, §3.12). Direct SDK calls in your own service layer are ~200 lines and fully controllable |
| Resume text extraction | `pypdf` + `pdfplumber` (PDF), `python-docx` (DOCX) | |
| Scanned resumes | **AWS Textract (ap-south-1)** | Confirm regional availability; needed for the Tier II/III candidate reality |
| Prompt versioning | Own table — `Model Version` (SDD §J2) | A prompt change is a model version change. Already in the data model |

### 1.6 Frontend — the one non-Python part

This is unavoidable, so plan for it rather than discovering it in month four. Two surfaces with genuinely different requirements:

**Internal application** (HR, Hiring Manager, Interviewer, Admin) — dashboards, pipeline views, scheduling, Candidate 360 timeline, approvals queue. This needs a real SPA.

| Layer | Decision |
|---|---|
| Framework | **React 18 + TypeScript + Vite** |
| Components | **shadcn/ui + Tailwind** — own the component code rather than depend on a library's roadmap |
| State/data | **TanStack Query** for server state; avoid a global store until something demands one |
| Forms | **React Hook Form + Zod** |
| Tables | **TanStack Table** — the pipeline and reporting views need virtualisation |

**Candidate portal** (6 screens: status, document upload, reschedule request, offer review and sign, withdraw, consent) — token-authenticated, no accounts, no persistent state, must work on low-end Android over patchy connections.

**Recommendation: server-rendered Jinja2 + HTMX, not React.** Reasons: it stays in Python, so the whole team can maintain it; the payload is a fraction of an SPA's, which matters for the candidates you're actually trying to reach; and it keeps the token-validation boundary on the server where it belongs, with no client-side auth logic to get wrong. The Digio signing widget embeds fine either way.

The counter-argument is two frontend paradigms in one codebase. It's a real cost, and if you'd rather have one, use React for both. But the portal is small and security-sensitive, and those are the exact conditions where server rendering wins.

**Staffing note:** with a Python-heavy team, the internal SPA is your genuine skills gap. One dedicated frontend engineer from Phase 2 onward, not a backend engineer learning React under deadline.

### 1.7 Infrastructure and operations

| Layer | Decision | Why |
|---|---|---|
| Compute | **ECS Fargate** | No cluster to manage. EKS only if you already run Kubernetes |
| IaC | **Terraform** | Confirmed — dedicated DevOps capacity on the team removes the one-language argument for CDK. State backend must be **self-managed S3 in ap-south-1 with DynamoDB locking and SSE-KMS**, not Terraform Cloud (US-hosted, and state files carry infrastructure metadata) |
| CI/CD | **GitHub Actions** | Tenant-isolation suite (SDD §7.0) runs on every PR from day one |
| Secrets | **AWS Secrets Manager** with rotation | |
| Logging & metrics | **CloudWatch + OpenTelemetry** | In-region. PII redaction in the logging formatter, not by convention |
| Error tracking | **Self-hosted Sentry or GlitchTip in ap-south-1** | Sentry SaaS is out-of-region and error payloads carry request data. This is a residency decision, not a preference |
| Feature flags | **Own table** (SDD §A4) | LaunchDarkly is out-of-region and the flags are already modelled with the audit fields you need |
| Uptime/alerting | CloudWatch Alarms → SNS → Slack/PagerDuty | |

**DR caveat worth checking early:** ap-south-2 (Hyderabad) carries a smaller service catalogue than ap-south-1. Verify that every service in your DR path exists there before designing the failover, because discovering a gap during a drill is a bad day.

### 1.8 Testing and quality

| Layer | Decision |
|---|---|
| Test runner | `pytest` + `pytest-asyncio` |
| Database tests | **`testcontainers`** — real Postgres, because RLS and triggers cannot be tested against SQLite |
| Fixtures | `factory-boy` / `polyfactory` |
| API contract tests | `schemathesis` against the generated OpenAPI spec |
| Vendor mocking | `respx` + recorded fixtures per vendor |
| Frontend | Vitest + Testing Library; Playwright for the critical candidate journeys |
| Lint/format/types | `ruff`, `mypy` (strict on the domain layer), `pre-commit` |

### 1.9 Architecture shape — modular monolith, not microservices

**One deployable API application, organised into modules with enforced boundaries, plus separate worker and relay processes.** Deploy as: `api`, `worker-default`, `worker-llm` (separate pool — LLM calls are slow and shouldn't starve fast jobs), `outbox-relay`, `scheduler`.

The event bus already gives you the decoupling that usually motivates microservices, and you get it without distributed transactions, network failure between every module, or eleven deployment pipelines for a team of seven. Module boundaries are enforced in code — modules communicate through events and published interfaces, never by importing each other's internals — so if a module genuinely needs to split out later, the seam is already there.

Splitting early would be the single most expensive mistake available at this stage.

```
onboarding-platform/
├── infra/                    # Terraform
├── backend/
│   ├── src/platform_core/    # shared kernel
│   │   ├── auth/             # SSO SP, capabilities, portal tokens
│   │   ├── events/           # envelope, outbox, publisher, consumer base
│   │   ├── audit/            # hash-chained writer
│   │   ├── approvals/        # shared approval engine
│   │   ├── notifications/    # channel adapters, template resolution
│   │   ├── sla/              # escalation service
│   │   └── tenancy/          # RLS session management
│   ├── src/modules/          # one package per spec module
│   │   ├── jobs/  candidates/  screening/  interviews/
│   │   ├── offers/  documents/  bgv/  dispatch/
│   │   ├── talent_pool/  copilot/  reporting/
│   ├── src/integrations/     # one adapter per vendor, uniform interface
│   │   ├── digio/  authbridge/  exotel/  voice_ai/
│   │   ├── naukri/  gifteko/  calendar/  slack/  email/  llm/
│   └── tests/
├── frontend-internal/        # React + TS
├── candidate-portal/         # Jinja2 + HTMX (served by FastAPI)
└── docs/                     # spec, SDD, ADRs
```

Every integration sits behind a uniform adapter interface. That is what makes the AuthBridge/SpringVerify parallel pilot possible without rework, and what will let the voice AI vendor be swapped after the pilot.

---

## Part 2. Build Roadmap

Two tracks run in parallel from week 1. Track B is not engineering work, but it determines whether Track A stalls in month four.

### Track B — procurement, compliance, business input (starts immediately)

| Item | Owner | Start | Must complete by |
|---|---|---|---|
| DLT entity + template registration (Exotel) | Ops/Legal | **Week 1** | Week 10 — gates all SMS testing |
| Vendor DPAs, DPDP attestations, written residency confirmations (Digio, Exotel; AuthBridge when contracted) | Legal | Week 1 | Before each contract |
| **Gifteko sub-processor agreement** + disclosure in the customer DPA (separate entities confirmed) | Legal | Week 1 | Before first customer |
| **Arm's-length commercial terms between the entities**, in writing | Legal/Finance | Week 2 | Before diligence |
| **Kit branding onboarding** for the design partner — assets, proof, approval, production | Gifteko ops | **Week 4** | **Before first dispatch — multi-week lead time** |
| ~~Voice AI decision~~ — **resolved**: deferred. Manual screening at launch; build/buy reopened when the team chooses | — | — | Removed from the DPA and contracting queue |
| ~~CTC working session~~ — **resolved**: Labour Code-compliant V1 rule set, SDD §4.1 | — | — | — |
| Approval band thresholds | HR/Finance | Week 4 | Interim default in place; no longer blocking |
| ~~Monthly volume assumptions~~ — **resolved**: 500–1,000 applications/month | — | — | — |
| Naukri RMS subscription | Procurement | Week 4 | Week 12 |
| ~~Retention periods~~ — **resolved**: 12 months non-joiner, handoff-and-purge for joiners | — | — | Confirm the Wage Code denominator with counsel |
| ~~Default pipeline templates~~ — **proposed** in Part 6; HR to confirm | HR | Week 4 | Week 16 |
| ~~Fairness sign-off owner~~ — **resolved**: interim owner named | — | — | Permanent appointment before scale |
| S1–S7 spec change control (S1 and S3 with counsel) | Product + Legal | Week 2 | Week 6 |

### Track A — engineering

Durations assume the team in Part 5. Each phase has an exit criterion, not just a deliverable — a phase isn't done because the code exists.

---

#### Phase 0 — Foundations · 2 weeks · *no external dependencies*

Terraform for VPC, RDS, S3, SQS, EventBridge, ECS in ap-south-1 with ap-south-2 DR skeleton. Repo structure, CI pipeline, `ruff`/`mypy`/`pre-commit`. Base FastAPI app with health checks. **PostgreSQL RLS tenancy pattern implemented and proven.**

Security baseline lands here too: WAF, private subnets with VPC endpoints, per-service IAM roles, the PII-redacting log formatter, and `bandit`/`semgrep`/`pip-audit`/Trivy wired into CI as blocking checks. First threat-model session (§1.4).

**Exit:** a two-tenant isolation test suite runs on every PR and fails the build on any cross-tenant leak. This lands in week 2 and never comes out, and no PR merges past a high-severity static-analysis finding.

---

#### Phase 1 — Platform core · 4 weeks

The shared kernel everything else depends on. Nothing here is a spec module, and it is all load-bearing.

- **Identity & access:** User, Role, Role Assignment, capability enforcement middleware, SAML/OIDC SP with per-org IdP config
- **Candidate Portal Token:** issue, hash, scope, expire, revoke, validate
- **Approval engine:** Approval Request, Approval Action, Approval Delegation, escalation
- **Audit Log:** hash-chained append-only writer, nightly verification job
- **Event infrastructure:** envelope, transactional outbox, relay, EventBridge routing, consumer base class with idempotency, DLQs
- **SLA service:** business-day calculation against a per-org holiday calendar
- **Notification service:** channel adapters, template resolution (SMS blocked on DLT, so build against a stub)

Portal token security is built to the §1.4 design here — exchange-on-first-use for a scoped session cookie, token in path not query string, `Referrer-Policy: no-referrer`, rate limiting per token and per IP. Object-level authorisation is enforced in the middleware layer, with negative tests as a standing requirement.

**Exit:** an end-to-end walkthrough with no business modules — a user authenticates via SSO, an approval request is created, escalates on SLA breach, emits an event, produces a notification and an audit entry, and the audit chain verifies.

> This phase looks like infrastructure and gets cut under pressure. Don't. Every one of these was a gap in SDD 1.0 precisely because they're invisible until something depends on them.

---

#### Phase 2 — Jobs & JD · 3 weeks · **Module 1**

Organization config, CTC Rule Set and Approval Band Policy entities, **Organization Kit Profile and Client Kit setup** (branding assets, proof approval, readiness state, fulfilment mode), JD Template with immutable versioning, Job Posting, Board Posting, LLM JD generation via Bedrock, publish approval gate, Naukri adapter, LinkedIn manual attestation, public application form with bot protection.

**Exit:** a job goes from draft through approval to published on the career portal and Naukri, with a working application form. First real user-facing slice.

*Frontend engineer joins here.*

---

#### Phase 3 — Candidates & intake · 4 weeks · **Module 2**

Candidate Profile with dedup fingerprinting, Application, Referral with the deliberately-narrow notification set, resume parsing (Bedrock + Textract fallback), AI scoring, `Parse-Failed`/`Score-Failed` recovery paths, HR manual upload, Model Version entity.

**Shadow-mode Copilot generation starts here** — generate, store, surface nothing. This is what builds the validation corpus you don't currently have. It needs to be in the candidate privacy notice from day one.

This phase opens two new attack surfaces at once — attacker-supplied file upload and attacker-supplied LLM input — so the §1.4 controls for both land with it: content-sniffed type allowlist, ClamAV quarantine scan, user files served only from a separate S3 domain, and the prompt-injection control set including the CI injection corpus. Threat model refreshed.

**Exit:** the same person applying through all three sources produces one profile and three applications; a corrupt resume surfaces as a recoverable failure rather than a stalled application. A resume carrying embedded instructions does not move its own score.

---

#### Phase 4 — Interviews · 4 weeks · **Module 3B**

Pipeline Template with activation immutability trigger, snapshot-at-shortlist, Interview Round, Interviewer Assignment, panel feedback, round decision, Google and Outlook calendar adapters, scheduling engine with free/busy matching, per-interviewer feedback SLA and escalation.

**Exit:** a three-round panel interview schedules, reschedules and cancels with correct calendar behaviour; editing the template mid-flight provably does not alter the in-flight candidate.

---

#### Phase 5 — Screening · 1 week · **Module 3A** · *voice deferred*

Exotel adapter for SMS only. Screening Call Record and Call Attempt written by HR through a manual screening workflow, with consent capture and escalation unchanged. The state machine, data model and candidate experience are identical to the automated path — only the caller changes.

**The seam is kept open by design.** Layer 1 (telephony) and Layer 2 (voice AI) remain separate adapter interfaces behind a `AIScreening` feature flag. Reintroducing voice — whether bought or built — is an adapter implementation plus a flag, with no change to the state machine, the record, or the candidate experience. The build/buy question reopens whenever the team is ready; nothing in this phase forecloses either answer.

Inbound webhook authentication is hardened here across all vendor callbacks — signature verification, replay window, IP allowlisting where supported — since a forged pipeline-advancing callback is threat #7.

**Exit (voice path):** both `telephony_call_id` and `voice_ai_session_id` populate on every completed call; a DND-listed number is never dialled and the check is evidenced.
**Exit (manual path):** a screening outcome recorded by HR produces the same record, the same events, and the same state transition as an automated one — so switching on voice later is a configuration change, not a migration.

---

#### Phase 6 — Offer & compensation · 5 weeks · **Modules 4, 5, 7** · *no longer blocked*

Parallel-pipeline detection, Negotiation Log with band check and threshold stamping, CTC calculator engine, Offer versioning with corrected status enum, expiry and reminders, reissue chain, Digio embedded signing, decline handling, **Branch B** (Aadhaar capture before signing) if S1 resolves that way.

**Exit:** breakdown sums to gross within ₹1; a retired rule set still reproduces a historical offer exactly; reissue creates a new version and supersedes the old one readably.

> Previously the project's one hard external blocker. With the minimal Fixed/EPF/cess structure decided, the engine and its first rule set can be built together. The engine stays generic — a company that later wants Basic/HRA/gratuity/variable adds a rule set version, not a code change.

---

#### Phase 7 — Documents, BGV, dispatch · 4 weeks · **Modules 6, 8, 9**

Document Submission with per-instance tracking and targeted resubmission, field-level masking with `SensitiveDataAccessed` on every unmask, HR-assisted submission, consent-gated BGV initiation, three flag resolutions, Gifteko dispatch with address re-confirmation.

**BGV ships with a manual-entry mode** alongside the adapter interface; the AuthBridge and SpringVerify adapters land when the contract and parallel pilot complete.

**Kit dispatch now carries a real model** — Kit Catalogue Item, Client Kit, Organization Kit Profile and the three fulfilment modes (SDD §H3–H6, §3.8). Note that **kit readiness is set up in Phase 2, not Phase 7**: branding artwork, proof and production take weeks and happen once per customer, so it belongs with organisation onboarding alongside SSO and CTC configuration. Phase 7 only consumes it.

Highest-sensitivity data in the system arrives in this phase. Insider-risk controls go live with it: unmask logging, export watermarking, and anomaly alerting on unmask volume per user. Threat model refreshed.

**Exit:** rejecting one document requests exactly that document; BGV initiation without valid consent is rejected at the database, not just in code.

**The AuthBridge/SpringVerify parallel pilot runs during this phase** — 20 to 30 candidates, deliberately including non-metro profiles, since regional-language document handling was the deciding selection factor and won't be tested by metro candidates.

---

#### Phase 8 — Data lifecycle & reporting · 4 weeks

Talent Pool with consent validity and revocation, Candidate Merge with the repoint-vs-audit-chain semantics, retention job with dry-run and Application Analytics Record, Candidate 360 Timeline read-model, operational and analytical dashboards.

Retention implements the three-clock model in SDD §4.6, including the Employment Record Pack handoff and the assertion that an `Onboarded` candidate is never reachable by the candidate purge job. Backup retention is set from the joiner clock, since a backup outliving the purge window makes the purge cosmetic.

**Book the penetration-test vendor during this phase.** Good testers are scheduled months ahead; looking in Phase 10 is how launches slip.

**Exit:** funnel and time-to-hire aggregates are byte-identical before and after a purge run.

---

#### Phase 9 — AI Copilot, narrative only · 2 weeks

Summary, strengths, risks, suggested questions. Fairness Review entity and version gate. **`salary_fit_score` and `offer_confidence_score` are not built** — deferred pending a validation corpus, per the change-control entry.

Counterfactual testing harness: name, college and city perturbation across a few hundred inputs, asserting output stability. This is the fairness evidence available to you without historical outcomes.

The interim fairness sign-off owner is named, so this phase is no longer blocked. Record the owner in `Fairness Review.reviewer_id` — and note that an interim owner who is also the project lead is a conflict worth resolving before scale, since reviewing your own system is a weak control.

**Exit:** no output surfaces without an approved review on its model version; activating a new version hides output without touching historical rows.

---

#### Phase 10 — Hardening & go-live · 4 weeks

Penetration test and remediation, load test to the volume assumptions, DR failover drill, retention dry-run in production, accessibility pass on the candidate portal, runbooks, UAT with one pilot organisation, phased rollout.

Security sign-off items: incident response runbook rehearsed, DPDP breach-notification path with a named owner and a clock, vulnerability disclosure contact published before the public form goes live, and a final threat-model review against the built system rather than the design.

**Exit:** DR drill completed with a measured RTO/RPO; all high and critical pen test findings closed, mediums triaged with owners and dates.

---

### Timeline

| Phase | Weeks | Cumulative |
|---|---|---|
| 0 — Foundations | 2 | 2 |
| 1 — Platform core | 4 | 6 |
| 2 — Jobs & JD | 3 | 9 |
| 3 — Candidates & intake | 4 | 13 |
| 4 — Interviews | 4 | 17 |
| 5 — Screening | 1 | 18 |
| 6 — Offer & compensation | 5 | 23 |
| 7 — Documents, BGV, dispatch | 4 | 27 |
| 8 — Data lifecycle & reporting | 4 | 31 |
| 9 — AI Copilot | 2 | 33 |
| 10 — Hardening & go-live | 4 | **37** |

**Roughly 8.5 months to production**, with two qualifications. Phases 2 through 5 overlap meaningfully once the frontend engineer is on — realistically 8 months. And the estimate assumes the CTC session lands by week 18; if it slips to week 26, Phase 6 slips with it and everything downstream moves. That is the single schedule risk worth tracking on a wall.

**Earliest demonstrable slice:** end of Phase 2, week 9 — a real job published to a real board, taking real applications.

---

## Part 3. Sequencing rationale

Three ordering choices worth understanding, because they'll look wrong at some point and someone will propose changing them:

**Platform core before any module.** Approvals, events, audit and identity are used by every module. Building Module 1 first and retrofitting approvals is how you end up with three nullable `approver_id` columns — which is precisely the defect SDD 2.0 exists to fix.

**Screening after interviews**, despite screening coming first in the candidate journey. Interviews depend only on internal capability; screening depends on an unselected vendor, DLT registration, and a pilot outcome. Sequencing by dependency risk beats sequencing by narrative order.

**Offer late, despite being the highest-value module.** It's the only phase with a hard external blocker. Everything before it is unblocked work, which maximises the runway for the CTC session to land.

---

## Part 4. Cost shape

Not a quote — the inputs are blocked on volume assumptions. But the shape is worth knowing before sign-off:

| Category | Notes |
|---|---|
| AWS (non-prod + prod) | Modest at this scale. RDS Multi-AZ and Fargate dominate; expect low tens of thousands ₹/month until volume grows |
| Bedrock inference | Per JD generated, per resume parsed, per summary. **Scales with application volume, not headcount** — the one line that surprises people |
| Textract | Only for scanned resumes; a meaningful fraction in Tier II/III |
| Exotel | Per minute plus DID rental plus SMS. DLT registration is one-time |
| Voice AI | Per minute, volume-tiered, unknown until pilot |
| Digio | ₹3–₹25 per signature |
| AuthBridge | ₹500–₹8,000 per candidate by check depth |
| Naukri RMS | Annual subscription |

Bedrock, Exotel and voice all scale with **applications**, not hires. A 5% offer-acceptance funnel means you pay inference and telephony on the 95% too.

**At the confirmed 500–1,000 applications/month, the picture is clearer and mostly reassuring:**

| Line | At this volume |
|---|---|
| Bedrock inference | 500–1,000 parses plus scoring and summaries per month. Small — expect low thousands of ₹/month |
| Textract | Only scanned resumes. Negligible |
| Infrastructure | Well under any sizing that needs thought. A single Multi-AZ RDS instance and small Fargate tasks carry this comfortably for years |
| Postgres FTS for talent pool | Confirmed correct. 6–12k profiles/year is three orders of magnitude below where a search cluster becomes necessary |
| Digio | Roughly one signature per hire — perhaps 10–25/month |
| AuthBridge | Same count. **Tens of checks per month, not thousands** |

**The finding worth acting on:** at these volumes you have essentially no leverage with volume-tiered vendors. Ten to twenty-five BGV checks a month puts you at the top of the published ₹500–₹8,000 band, and any minimum monthly commitment will likely exceed actual usage. Negotiate for **no minimum commitment and no annual lock-in** rather than for a lower unit rate — the flexibility is worth more than the discount at this stage, and it's what you'll want when volumes change after a raise.

This also confirms the Copilot scoring deferral. At roughly 100–200 hires a year, subgroup sizes for a credible disparate-impact analysis are years away, not months.

---

## Part 5. Capacity assumptions

Staffing is owned outside this document. What follows is only the capacity the phase durations are indexed to, so that if actual capacity differs the timeline can be rescaled rather than silently missed.

| Capability | Assumed | From |
|---|---|---|
| Backend (Python) | 3 | Phase 0 |
| Frontend (React/TS) | 1 | Phase 2 |
| DevOps / platform | 1 | Phase 0, ~50% thereafter |
| QA / automation | 1 | Phase 1 |
| Tech lead | 1 | Throughout |
| Product | 1 | Throughout, heavily on Track B |

Two capability notes that are technical rather than organisational:

**React capability is needed from Phase 2**, and it's the one skill the rest of the stack doesn't supply. The internal SPA is substantial — pipeline views, timeline, scheduling, dashboards — and it is not a weekend for a backend engineer.

**QA capability from Phase 1, not Phase 8.** The tenant-isolation, audit-completeness, idempotency and token-security suites are cross-cutting and run continuously from the moment the platform core exists. Introducing them late means they arrive after the invariants have already been violated somewhere.

Scaling note: below this capacity the timeline stretches roughly linearly; above it, it does not compress, because the phases have hard sequential dependencies.

---

## Part 6. Decisions to sign off

Tick, strike, or defer each. The ones marked **hard to reverse** are the ones worth arguing about now. Security rows are decisions in the same sense as the rest — each has a cost and a phase, and deferring one is a choice rather than an omission.

### Stack

| # | Decision | Reversibility |
|---|---|---|
| 1 | Python 3.12 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 | **Hard to reverse** |
| 2 | PostgreSQL 16 with RLS as the tenancy mechanism | **Hard to reverse** |
| 3 | Modular monolith, not microservices | **Hard to reverse** |
| 4 | Outbox → EventBridge → per-consumer SQS | Moderate |
| 5 | Celery on SQS (vs Dramatiq) | Easy |
| 6 | Postgres FTS for talent pool search, no OpenSearch | Easy — revisit at ~500k profiles |
| 7 | Direct SAML/OIDC SP implementation (vs Keycloak in-region) | Moderate |
| 8 | React + TypeScript for the internal app | **Hard to reverse** |
| 9 | Jinja2 + HTMX for the candidate portal (vs React for both) | Moderate |
| 10 | No LLM orchestration framework — direct Bedrock SDK | Easy |
| 11 | Terraform, with a self-managed in-region state backend | **Hard to reverse** — settled |
| 12 | ECS Fargate (vs EKS) | Moderate |
| 13 | Self-hosted Sentry/GlitchTip in-region | Easy |
| 14 | Own feature-flag table, no third-party service | Easy |
| 15 | AWS WAF at the edge with OWASP managed rules and bot control | Easy |
| 16 | ClamAV scan-on-upload with a quarantine bucket (vs no AV scanning) | Easy |
| 17 | User files served from a separate S3 domain, never the app origin | Moderate |
| 18 | Portal token exchanged on first use for a scoped session cookie | **Hard to reverse** |
| 19 | Penetration test vendor engaged by Phase 8, annually thereafter | Easy |

### Scope and process

| # | Decision |
|---|---|
| 20 | Copilot ships narrative outputs only; `salary_fit_score` and `offer_confidence_score` deferred |
| 21 | Shadow-mode Copilot generation from Phase 3, disclosed in the candidate privacy notice |
| 22 | Voice AI pilot runs on a throwaway harness from week 1, ahead of the adapter |
| 23 | Document-phase ordering default — determines whether Branch B is in Phase 6 or retrofitted |
| 24 | Frontend engineer hired before Phase 2 |
| 25 | S1–S7 go through spec change control; S1 and S3 with counsel |

### Business decisions — resolved

Five of the seven blockers are now closed. Recorded here as the working set; each still needs a formal change-control entry against V3.2.

| Item | Decision | Effect |
|---|---|---|
| **CTC rules** | **Finalised** against the Labour Codes: Basic 50% of CTC, HRA, balancing Special Allowance, employer PF, gratuity, conditional ESI. Full structure in SDD §4.1 | **Phase 6 unblocked** |
| **Monthly volumes** | **500–1,000 applications/month** at launch | Confirms Postgres FTS, sizes infrastructure, changes vendor negotiating position (see Part 4) |
| **Retention** | **12 months** for non-joiners; joiners get an **Employment Record Pack handoff at +90 days, then purge** | Three-clock model in SDD §4.6. Removes the multi-year obligation entirely |
| **Fairness sign-off owner** | Named interim owner (project lead), pending a permanent appointment | **Phase 9 unblocked** |
| **Default pipeline templates** | Proposed below; HR to confirm | Phase 4 seeding |

#### Proposed default pipeline templates

You asked for a recommendation. These are starting points sized for a company hiring at 500–1,000 applications/month — deliberately short, because long pipelines are the main driver of candidate drop-off at this stage and rounds are cheap to add later.

| Job family | Rounds |
|---|---|
| **Default (fallback)** | Screening → Functional → Hiring Manager |
| **Engineering** | Screening → Technical 1 → Technical 2 → Hiring Manager |
| **Sales / Business Development** | Screening → Hiring Manager → Case or role-play → Leadership |
| **Operations / Support** | Screening → Functional → Hiring Manager |
| **Leadership / Senior (band-triggered)** | Screening → Hiring Manager → Panel → Founder/CXO |
| **Intern / Entry level** | Screening → Functional → Hiring Manager |

Three notes. Keep the **Default** template genuinely generic — it's what every organisation falls back to when the Configurable Pipelines flag is off, so it should never be engineering-shaped. Panel rounds are supported from Phase 4, so the Leadership template needs no extra build. And since templates are versioned and snapshotted at shortlist, HR can revise these freely without touching in-flight candidates — which means these only need to be *reasonable*, not *right*.

### Still open

| Item | Status |
|---|---|
| **Approval band thresholds** | Still undecided. **Interim default in place:** every offer routes to approval until bands are set. Safe, configurable, and off the critical path |
| **Document-phase ordering** | Branch A (default) or Branch B (post-signature). Affects Phase 6 — see Part 8 |

### Two decisions that need a second look

**"Cess" in the CTC structure.** In Indian payroll, cess is Health & Education Cess — a surcharge on income tax, deducted from the employee, not a CTC component. If you mean employer statutory contributions, that's a different line. Worth pinning down before the calculator is built, because the offer letter is a legal document and the breakdown appears on it. The engine handles either; only the component definition changes.

**Retention — resolved as three clocks.** Non-joiners at **12 months**. Joiners get an **Employment Record Pack exported to the customer's system of record at Onboarded +90 days, then purged here** — the platform never inherits the multi-year employment-record obligation. Full model in SDD §4.6.

| Track | Trigger | Retention |
|---|---|---|
| **A — Non-joiner** | Rejected, withdrawn, declined, no-show | 12 months from terminal state |
| **B — Joiner** | Onboarded | Handoff at +90 days, then purge. Nothing destroyed without confirmed export |
| **C — Talent pool** | Rejected with consent | 24 months consent validity; extends Track A |

A useful side effect: the longest clock in the system is now 24 months rather than a multi-year employment period, which shortens backup retention correspondingly.

**CTC — finalised against the Labour Codes.** The structure you proposed is superseded; the reason is worth knowing. The four Labour Codes came into force on 21 November 2025, and the Code on Wages now folds excluded allowances back into "wages" for PF, gratuity and bonus if they exceed 50% of total remuneration. Structures that kept basic at 30–40% of CTC no longer work. V1 is: **Basic at 50% of CTC**, HRA at 50%/40% of basic by metro status, Special Allowance as the balancing figure, employer PF at 12% of basic capped at the statutory ceiling, gratuity at 4.81%, and employer ESI conditionally. Statutory parameters are dated config values, not constants — the EPF ceiling in particular has a deferred increase pending. Full rule set, worked example and validation gates in SDD §4.1.

### Still open

| Item | Status |
|---|---|
| **Approval band thresholds** | Still undecided. **Interim default in place:** every offer routes to approval until bands are set. Safe, configurable, and off the critical path |
| **Document-phase ordering** | Branch A (default) or Branch B (post-signature). Affects Phase 6 — see Part 8 |

### Two decisions that need a second look

**"Cess" in the CTC structure.** In Indian payroll, cess is Health & Education Cess — a surcharge on income tax, deducted from the employee, not a CTC component. If you mean employer statutory contributions, that's a different line. Worth pinning down before the calculator is built, because the offer letter is a legal document and the breakdown appears on it. The engine handles either; only the component definition changes.

**Retention — resolved as three clocks.** Set to **12 months** for candidates who don't join. The full model is now specified in SDD §4.6; the summary:

| Track | Trigger | Retention |
|---|---|---|
| **A — Non-joiner** | Rejected, withdrawn, declined, no-show | **12 months** from terminal state |
| **B — Joiner** | Onboarded | Statutory period from end of employment — **counsel to set the figure** |
| **C — Talent pool** | Rejected with consent | 24 months consent validity; **extends** Track A |

The precedence rules matter more than the numbers, because they're where a single-clock implementation quietly does the wrong thing: longest applicable clock wins; reaching `Onboarded` moves an Application out of the candidate retention regime entirely; consent revocation collapses Track C back to Track A rather than triggering immediate deletion; and pool consent never extends document retention, since consenting to be considered for future roles is not consenting to keep your Aadhaar on file.

**One figure still needs counsel: Track B.** I've left `retention_months_joiner` configured high rather than set to a year. A year would not be compliant — tax-linked employment records run well beyond that, and over-retention is a correctable error while premature destruction is not. Until counsel gives you the number, the joiner track simply retains, and nothing about the build is blocked.

---

## Part 7. What to do this week

1. **Decide items 1, 2, 3, 8 and 18** — the remaining hard-to-reverse rows. Item 11 is settled.
2. **Start DLT registration.** Longest external lead time in the project and it gates all SMS testing — and it's needed whether or not voice happens, since candidate SMS runs through the same registration.
3. **Settle the voice question** — build, buy, or defer. Part 8 sets out why deferring is the cheapest of the three. This is the largest single scope decision left.
4. **One question to counsel:** whether the Wage Code 50% denominator is total CTC or gross excluding employer PF and gratuity. The engine computes against CTC (conservative) and the denominator is a config value, so this is a confirmation, not a blocker.
5. **Open the frontend role.**
6. **Kick off Phase 0.** It has no external dependencies and can start the moment items 1, 2 and 11 are decided.

---

---

## Part 8. Voice: deferred, seam kept open

**Decision: defer.** The platform launches with HR-performed screening writing to the same Screening Call Record, emitting the same events, driving the same state transition. Build-versus-buy is not decided against — it is deliberately reopened for later, once there is evidence to decide on.

What deferral buys: two weeks off Phase 5, one fewer vendor in the DPA and contracting queue, no per-minute cost before revenue, and — most usefully — a corpus of real screening transcripts and HR judgements. That corpus is both the evidence for whether automation is worth paying for and the specification for what the conversation graph should actually do. A later vendor evaluation runs against your own recorded calls rather than a demo script.

**How the seam stays open.** Layer 1 (telephony) and Layer 2 (voice AI) remain distinct adapter interfaces behind an `AIScreening` feature flag. Reintroduction is an adapter implementation and a flag flip. Nothing in the state machine, the data model, or the candidate experience changes.

### The generalisation worth adopting

The same pattern applies to every vendor-dependent stage, and adopting it deliberately turns scope decisions into configuration rather than rework:

| Stage | Vendor | Skippable? |
|---|---|---|
| AI screening | Exotel + Layer 2 | Flag — **off at launch** |
| Background verification | AuthBridge | Flag stays on; **manual-entry mode** pre-contract |
| Onboarding kit dispatch | Gifteko (**first-party**) | Flag exists for customers who opt out — **on at launch**. Gated on Kit Profile readiness |
| Job board posting | Naukri | Per-board, already modelled |
| E-signature | Digio | **Not skippable** — core to the offer flow |

When a stage is flagged off, the Application transitions straight past it with the skip recorded on the timeline. That is a small amount of build in Phases 4–7 and it removes the need to make scope decisions permanently.

---

## Part 9. Pre-raise scope — open for decision

The full roadmap is correct as the enterprise product. What is undecided is how much of it ships before the raise. Four questions, with a recommendation on each.

### 9.1 What can never be cut

Whatever else shrinks, three things are obligations from the moment the platform holds one real candidate's data, not features to prioritise:

1. **Retention and purge** — the three-clock model. DPDP applies the day you hold data, not the day you launch.
2. **Consent lifecycle** — grant, revoke, expire, and the audit trail behind it.
3. **Security baseline and tenant isolation** — Phase 0 and the cross-cutting suites.

Everything else is negotiable. Worth stating explicitly because these are the items that look like infrastructure and get cut first.

### 9.2 Which vendor integrations ship pre-raise

Each carries a contract, a DPA, a residency attestation, and per-unit cost.

**Gifteko is first-party and ships at launch.** My earlier recommendation to defer it was wrong — it treated Gifteko as a third-party vendor carrying a contract and a per-unit cost. It carries neither. More importantly, kit dispatch is not a post-offer convenience in this product; it is the existing business the platform extends. Deferring it would ship the generic half of the system and leave out the part that distinguishes it from every other ATS. It moves to launch scope, and the Dispatch Record needs a design pass against Gifteko's actual catalogue rather than the generic `kit_type` string currently modelled (SDD §3.8).

**Digio ships — not skippable.** Aadhaar eSign is what makes the offer flow real rather than a PDF attachment.

**AuthBridge: build the module, defer the contract.** The functional objection is right — an ATS without background verification is visibly incomplete to any HR buyer, and BGV sits on the critical path between offer and dispatch. So the module ships in full: state machine, three flag resolutions, consent gate, conditional deadlines, events.

What defers is the *vendor*, not the *function*. Phase 7 ships a **manual-entry mode** where HR runs verification through whatever agency they use today and records the outcome — identical states, identical events, identical downstream behaviour. The AuthBridge adapter is built to the same interface and plugs in when the contract and the parallel SpringVerify pilot are done. That pilot is a procurement exercise, not a build task, and it is the part genuinely worth deferring: 20–30 candidates through two vendors takes weeks of coordination and produces no code.

This is the same pattern as the voice deferral, applied to preserve functional completeness rather than to cut it.

### 9.3 Design partner with real hires, or controlled demo

This determines whether the §9.1 floor applies in full or whether the first version can run on synthetic data. A demo defers the compliance work; a design partner running real hires does not.

**Recommendation: design partner.** A demo tells you the product works. A partner hiring through it tells you whether it's worth paying for — which is the thing a seed round is actually evaluating. It also produces the screening corpus that informs the voice decision. Accept that this means the §9.1 floor ships in full.

### 9.4 Document-phase ordering

Still open, and it is the one remaining decision that changes the build rather than the config. Branch A (documents before offer letter) is the default and the simpler path. Branch B (post-signature) requires the Aadhaar-capture step ahead of signing.

**Recommendation: Branch A only, pre-raise.** Build the ordering as configuration from the start so Branch B is additive later, but do not build the second branch until a customer asks for it.

### Resulting pre-raise scope

Phases 0–7 in full, plus the §9.1 compliance floor pulled forward from Phase 8. The complete hiring journey: job published, applications received and scored, interviews scheduled with panel feedback, offer generated with a compliant CTC breakdown, signed via Aadhaar eSign, documents collected and verified, background verification resolved, **onboarding kit dispatched through Gifteko**.

Deferred behind flags: talent pool, candidate merge, reporting and dashboards, AI Copilot, AI screening, and the AuthBridge adapter (manual BGV entry until contracted).

Roughly **seven months** at the assumed capacity, against 8.5 for the full build. The saving is smaller than the earlier six-month figure because BGV and dispatch have moved back into scope — which is the right trade, since a demonstrably incomplete product is worth less at a raise than six weeks of runway.

---

*Companion to Build Spec V3.2 (sealed) and SDD 2.0. Stack decisions recorded here should become ADRs in `docs/` once signed off, so the reasoning survives the people who made it.*

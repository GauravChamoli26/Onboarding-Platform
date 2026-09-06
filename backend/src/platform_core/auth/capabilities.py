"""
Capabilities — the unit of authorisation.

THE MODEL
    Capabilities are the enforcement primitive; roles are bundles of them. Every
    endpoint declares the capability it requires, and a user holds a capability
    if any of their unexpired role assignments grants it.

WHY NOT CHECK ROLES DIRECTLY
    Two reasons, both from the spec.

    First, S4: Module 5 routes above-band CTC approval to "Finance or HR Head",
    but the roles list contains no Finance role. Checking `role == "HR"` forces
    you to either invent a Finance role or widen HR. Checking
    `has_capability(APPROVE_CTC_ABOVE_BAND)` lets that one permission be granted
    to a named Finance stakeholder without touching anything else.

    Second, the permission matrix has entries like "designated HR only" for
    unmasked PII. That is not a role — it is a subset of a role, and it only
    expresses cleanly as a capability.

RELATIONSHIP TO ROW-LEVEL SECURITY
    Two independent boundaries answering different questions. RLS answers
    "whose data is this?" and is enforced by the database. Capabilities answer
    "may this person do this?" and are enforced by the application.

    Neither substitutes for the other. A user with every capability still sees
    only their own organisation's rows.
"""

from enum import StrEnum


class Capability(StrEnum):
    """
    Every action the platform authorises.

    Derived directly from the permission matrix in Build Spec V3.3. Adding one
    means adding it to the matrix first — the spec is the source of truth, and a
    capability that exists in code but not in the matrix is a permission nobody
    agreed to.
    """

    # --- Job descriptions and postings (Module 1) --------------------------
    CREATE_JD = "create_jd"
    APPROVE_JOB = "approve_job"
    EDIT_JD_TEMPLATES = "edit_jd_templates"

    # --- Candidates and applications (Module 2) ----------------------------
    ADD_RESUME_MANUALLY = "add_resume_manually"
    SHORTLIST = "shortlist"

    # --- Interviews (Module 3) ---------------------------------------------
    SCHEDULE_INTERVIEW = "schedule_interview"
    SUBMIT_FEEDBACK = "submit_feedback"
    VIEW_ALL_ROUND_FEEDBACK = "view_all_round_feedback"
    DECIDE_ROUND = "decide_round"

    # --- Offers and compensation (Modules 4, 5, 7) -------------------------
    MARK_NEGOTIATION_COMPLETE = "mark_negotiation_complete"
    APPROVE_CTC_ABOVE_BAND = "approve_ctc_above_band"  # grantable to Finance (S4)
    GENERATE_OFFER = "generate_offer"
    APPROVE_OFFER = "approve_offer"

    # --- Documents and verification (Modules 6, 8) -------------------------
    VERIFY_DOCUMENTS = "verify_documents"
    SUBMIT_DOCUMENTS_ON_BEHALF = "submit_documents_on_behalf"
    VIEW_UNMASKED_PII = "view_unmasked_pii"  # designated HR only
    RESOLVE_BGV_FLAG = "resolve_bgv_flag"

    # --- Onboarding kit (Module 9) -----------------------------------------
    CONFIGURE_KIT_PROFILE = "configure_kit_profile"

    # --- Talent pool and merge (Module 10, cross-cutting) ------------------
    SEARCH_TALENT_POOL = "search_talent_pool"
    REACTIVATE_CANDIDATE = "reactivate_candidate"
    MERGE_PROFILES = "merge_profiles"

    # --- AI Copilot (Module 11) --------------------------------------------
    VIEW_AI_COPILOT = "view_ai_copilot"

    # --- Notes -------------------------------------------------------------
    MANAGE_NOTES = "manage_notes"

    # --- Administration ----------------------------------------------------
    CONFIGURE_CTC_RULES = "configure_ctc_rules"
    CONFIGURE_PIPELINES = "configure_pipelines"
    MANAGE_FEATURE_FLAGS = "manage_feature_flags"
    MANAGE_ROLES = "manage_roles"
    DELEGATE_APPROVAL = "delegate_approval"

    # --- Audit and export --------------------------------------------------
    VIEW_AUDIT_LOG_FULL = "view_audit_log_full"
    EXPORT_PII = "export_pii"


class RoleKey(StrEnum):
    """
    The named roles from Build Spec V3.3 §Roles & Permissions.

    Candidate is absent deliberately: candidates hold no account and no role.
    They act through expiring portal tokens scoped to a single Application
    (ADR-010), which is a different mechanism entirely.
    """

    HR = "HR"
    HIRING_MANAGER = "HiringManager"
    INTERVIEWER = "Interviewer"
    EMPLOYEE = "Employee"  # referrers
    ADMIN = "Admin"


# ---------------------------------------------------------------------------
# Default role definitions
# ---------------------------------------------------------------------------
# Seeded for each new organisation. Admins may edit them afterwards — the spec
# makes roles Admin-managed — so these are starting points, not constants.
#
# Transcribed from the permission matrix. Where the matrix says "configurable"
# the capability is granted here and gated by a feature flag at the point of
# use, rather than being silently omitted.
DEFAULT_ROLE_CAPABILITIES: dict[RoleKey, frozenset[Capability]] = {
    RoleKey.HR: frozenset(
        {
            Capability.CREATE_JD,
            Capability.APPROVE_JOB,  # default approver
            Capability.EDIT_JD_TEMPLATES,
            Capability.ADD_RESUME_MANUALLY,
            Capability.SHORTLIST,
            Capability.SCHEDULE_INTERVIEW,
            Capability.VIEW_ALL_ROUND_FEEDBACK,
            Capability.DECIDE_ROUND,
            Capability.MARK_NEGOTIATION_COMPLETE,
            Capability.GENERATE_OFFER,
            Capability.APPROVE_OFFER,
            Capability.VERIFY_DOCUMENTS,
            Capability.SUBMIT_DOCUMENTS_ON_BEHALF,
            Capability.RESOLVE_BGV_FLAG,
            Capability.CONFIGURE_KIT_PROFILE,
            Capability.SEARCH_TALENT_POOL,
            Capability.REACTIVATE_CANDIDATE,
            Capability.VIEW_AI_COPILOT,
            Capability.MANAGE_NOTES,
            Capability.DELEGATE_APPROVAL,
        }
    ),
    # NOTE: VIEW_UNMASKED_PII, EXPORT_PII and APPROVE_CTC_ABOVE_BAND are NOT in
    # the HR default. The matrix restricts them to "designated HR" and to a
    # Finance or HR Head approver. They are granted individually, per person,
    # which is the whole reason capabilities are the primitive rather than roles.
    RoleKey.HIRING_MANAGER: frozenset(
        {
            Capability.CREATE_JD,
            Capability.SHORTLIST,
            Capability.SCHEDULE_INTERVIEW,
            Capability.SUBMIT_FEEDBACK,  # when assigned to a round
            Capability.VIEW_ALL_ROUND_FEEDBACK,
            Capability.DECIDE_ROUND,
            Capability.VIEW_AI_COPILOT,
            Capability.MANAGE_NOTES,
            Capability.SEARCH_TALENT_POOL,  # own requisitions only — scoped
            Capability.DELEGATE_APPROVAL,
        }
    ),
    # Minimal privilege by design: sees only what is needed to interview, and
    # submits only their own feedback.
    RoleKey.INTERVIEWER: frozenset(
        {
            Capability.SUBMIT_FEEDBACK,
            Capability.MANAGE_NOTES,  # own round only — scoped
        }
    ),
    RoleKey.EMPLOYEE: frozenset(),  # referral actions only, no capabilities
    RoleKey.ADMIN: frozenset(
        {
            Capability.CREATE_JD,
            Capability.APPROVE_JOB,
            Capability.EDIT_JD_TEMPLATES,
            Capability.ADD_RESUME_MANUALLY,
            Capability.SCHEDULE_INTERVIEW,
            Capability.VIEW_ALL_ROUND_FEEDBACK,
            Capability.APPROVE_CTC_ABOVE_BAND,
            Capability.APPROVE_OFFER,
            Capability.VERIFY_DOCUMENTS,
            Capability.SUBMIT_DOCUMENTS_ON_BEHALF,
            Capability.VIEW_UNMASKED_PII,
            Capability.RESOLVE_BGV_FLAG,
            Capability.CONFIGURE_KIT_PROFILE,
            Capability.CONFIGURE_CTC_RULES,
            Capability.CONFIGURE_PIPELINES,
            Capability.MANAGE_FEATURE_FLAGS,
            Capability.MANAGE_ROLES,
            Capability.MANAGE_NOTES,
            Capability.MERGE_PROFILES,
            Capability.SEARCH_TALENT_POOL,
            Capability.REACTIVATE_CANDIDATE,
            Capability.VIEW_AI_COPILOT,
            Capability.VIEW_AUDIT_LOG_FULL,
            Capability.EXPORT_PII,
            Capability.DELEGATE_APPROVAL,
        }
    ),
    # Admin is deliberately NOT a superuser. It lacks SHORTLIST, DECIDE_ROUND,
    # MARK_NEGOTIATION_COMPLETE and GENERATE_OFFER — hiring decisions belong to
    # the people accountable for them, not to whoever administers the system.
    # That separation of duties is in the matrix and is preserved here.
}

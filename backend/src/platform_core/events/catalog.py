"""
Domain event catalogue.

WHAT THIS IS
    Every event type the platform emits, transcribed from Build Spec V3.3
    §Domain Event Catalog.

WHY AN ENUM RATHER THAN FREE STRINGS
    A typo in an event name is invisible: the event publishes, no consumer
    matches it, and nothing fails. The Timeline is simply missing an entry that
    nobody notices until a candidate asks why their history has a gap.

    An enum turns that into an import error at the call site.

ADDING AN EVENT
    Add it to the spec first. An event that exists in code but not in the
    catalogue is a contract nobody agreed to, and consumers cannot subscribe to
    something they do not know about.
"""

from enum import StrEnum


class EventType(StrEnum):
    """Every domain event. Grouped as in the spec."""

    # --- Job lifecycle (Module 1) ------------------------------------------
    JD_DRAFTED = "JDDrafted"
    JD_APPROVAL_REQUESTED = "JDApprovalRequested"
    JD_PUBLISHED = "JDPublished"
    JD_VERSION_UPDATED = "JDVersionUpdated"
    JOB_ON_HOLD = "JobOnHold"
    JOB_CLOSED = "JobClosed"
    JOB_BOARD_POSTING_SUCCEEDED = "JobBoardPostingSucceeded"
    JOB_BOARD_POSTING_FAILED = "JobBoardPostingFailed"
    JOB_BOARD_MANUALLY_POSTED = "JobBoardManuallyPosted"

    # --- Application intake (Module 2) -------------------------------------
    CANDIDATE_APPLIED = "CandidateApplied"
    REFERRAL_SUBMITTED = "ReferralSubmitted"
    APPLICATION_PARSED = "ApplicationParsed"
    APPLICATION_SCORED = "ApplicationScored"
    APPLICATION_PARSE_FAILED = "ApplicationParseFailed"
    APPLICATION_SCORING_FAILED = "ApplicationScoringFailed"
    DUPLICATE_DETECTED = "DuplicateDetected"
    DUPLICATE_RESOLVED = "DuplicateResolved"

    # --- Screening and interviews (Module 3) -------------------------------
    SHORTLISTED = "Shortlisted"
    SCREENING_CALL_ATTEMPTED = "ScreeningCallAttempted"
    SCREENING_COMPLETED = "ScreeningCompleted"
    SCREENING_ESCALATED = "ScreeningEscalated"
    SCREENING_CALL_BLOCKED_BY_DND = "ScreeningCallBlockedByDND"
    SCREENING_CONSENT_DECLINED = "ScreeningConsentDeclined"
    INTERVIEWER_ASSIGNED = "InterviewerAssigned"
    INTERVIEW_SCHEDULED = "InterviewScheduled"
    INTERVIEW_RESCHEDULED = "InterviewRescheduled"
    INTERVIEW_CANCELLED = "InterviewCancelled"
    INTERVIEW_COMPLETED = "InterviewCompleted"
    INTERVIEW_NO_SHOW = "InterviewNoShow"
    ROUND_FEEDBACK_SUBMITTED = "RoundFeedbackSubmitted"
    ROUND_DECISION_RECORDED = "RoundDecisionRecorded"
    FEEDBACK_SLA_BREACHED = "FeedbackSLABreached"

    # --- Approvals ---------------------------------------------------------
    # The spec promised escalation across three modules but provided only
    # FeedbackSLABreached. The escalation service had nothing to emit.
    APPROVAL_REQUESTED = "ApprovalRequested"
    APPROVAL_GRANTED = "ApprovalGranted"
    APPROVAL_REJECTED = "ApprovalRejected"
    APPROVAL_DELEGATED = "ApprovalDelegated"
    APPROVAL_ESCALATED = "ApprovalEscalated"
    APPROVAL_REMINDER_SENT = "ApprovalReminderSent"
    APPROVAL_EXPIRED = "ApprovalExpired"

    # --- Offer and compensation (Modules 4, 5, 7) --------------------------
    OFFER_RECOMMENDED = "OfferRecommended"
    NEGOTIATION_COMPLETE = "NegotiationComplete"
    CTC_APPROVAL_REQUESTED = "CTCApprovalRequested"
    CTC_APPROVAL_GRANTED = "CTCApprovalGranted"
    OFFER_LETTER_DRAFTED = "OfferLetterDrafted"
    OFFER_LETTER_APPROVED = "OfferLetterApproved"
    OFFER_LETTER_SENT = "OfferLetterSent"
    OFFER_VIEWED = "OfferViewed"
    OFFER_SIGNED = "OfferSigned"
    OFFER_DECLINED = "OfferDeclined"
    OFFER_EXPIRED = "OfferExpired"
    OFFER_EXPIRY_REMINDER_SENT = "OfferExpiryReminderSent"
    OFFER_REVOKED = "OfferRevoked"
    OFFER_REISSUED = "OfferReissued"
    JOINING_DATE_CONFIRMED = "JoiningDateConfirmed"

    # --- Documents (Module 6) ----------------------------------------------
    DOCUMENTS_REQUESTED = "DocumentsRequested"
    DOCUMENT_SUBMITTED = "DocumentSubmitted"
    DOCUMENT_SUBMITTED_ON_BEHALF = "DocumentSubmittedOnBehalf"
    DOCUMENTS_PARTIALLY_SUBMITTED = "DocumentsPartiallySubmitted"
    DOCUMENT_REJECTED = "DocumentRejected"
    DOCUMENTS_VERIFIED = "DocumentsVerified"
    DOCUMENT_REMINDER_SENT = "DocumentReminderSent"

    # --- BGV and onboarding (Modules 8, 9) ---------------------------------
    BGV_INITIATED = "BGVInitiated"
    BGV_CLEARED = "BGVCleared"
    BGV_FLAGGED = "BGVFlagged"
    BGV_FLAG_RESOLVED = "BGVFlagResolved"
    BGV_INCOMPLETE_AT_JOINING = "BGVIncompleteAtJoining"
    BGV_VENDOR_ERROR = "BGVVendorError"
    KIT_DISPATCH_AWAITING_READINESS = "KitDispatchAwaitingReadiness"
    KIT_PROFILE_READINESS_CHANGED = "KitProfileReadinessChanged"
    DISPATCH_ADDRESS_RECONFIRMED = "DispatchAddressReconfirmed"
    KIT_DISPATCHED = "KitDispatched"
    KIT_DELIVERED = "KitDelivered"
    KIT_DISPATCH_FAILED = "KitDispatchFailed"
    ONBOARDED = "Onboarded"
    JOINING_NO_SHOW = "JoiningNoShow"

    # --- Candidate and data lifecycle --------------------------------------
    CANDIDATE_REJECTED = "CandidateRejected"
    CANDIDATE_WITHDRAWN = "CandidateWithdrawn"
    CONSENT_GRANTED = "ConsentGranted"
    CONSENT_REVOKED = "ConsentRevoked"
    CONSENT_EXPIRED = "ConsentExpired"
    CONSENT_REASK_SENT = "ConsentReaskSent"
    TALENT_POOL_ADDED = "TalentPoolAdded"
    TALENT_POOL_REACTIVATED = "TalentPoolReactivated"
    PROFILES_MERGED = "ProfilesMerged"
    SENSITIVE_DATA_ACCESSED = "SensitiveDataAccessed"
    PII_EXPORTED = "PIIExported"
    PORTAL_TOKEN_ISSUED = "PortalTokenIssued"
    PORTAL_TOKEN_REVOKED = "PortalTokenRevoked"
    RETENTION_PURGE_EXECUTED = "RetentionPurgeExecuted"
    EMPLOYMENT_RECORD_HANDED_OFF = "EmploymentRecordHandedOff"
    EMPLOYMENT_HANDOFF_FAILED = "EmploymentHandoffFailed"

    # --- Platform ----------------------------------------------------------
    FEATURE_FLAG_CHANGED = "FeatureFlagChanged"
    MODEL_VERSION_ACTIVATED = "ModelVersionActivated"
    FAIRNESS_REVIEW_RECORDED = "FairnessReviewRecorded"
    VENDOR_WEBHOOK_VERIFICATION_FAILED = "VendorWebhookVerificationFailed"


class ActorType(StrEnum):
    """Who caused an event."""

    USER = "User"  # an authenticated internal user
    SYSTEM = "System"  # a scheduled job or automatic transition
    CANDIDATE = "Candidate"  # acting through a portal token
    VENDOR = "Vendor"  # an inbound webhook from Digio, Exotel, Gifteko

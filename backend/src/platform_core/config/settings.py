"""
Application configuration.

WHAT THIS MODULE DOES
    Reads every configuration value the application needs from the environment,
    validates it at startup, and exposes it as a single typed object.

WHY IT LOOKS LIKE THIS
    Configuration errors should crash the process at boot, loudly, rather than
    surfacing as a confusing failure three hours into a batch job. Pydantic
    validates on instantiation, so a missing or malformed variable stops the
    application before it accepts a single request.

GOVERNED BY
    ADR-001 (Pydantic as the single schema layer)
    ADR-014 (residency enforced as a runtime control, not documentation)
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Residency allowlist
# ---------------------------------------------------------------------------
# ADR-014 commits us to India-region infrastructure. This tuple is the machine
# -readable form of that commitment: any region outside it is rejected at boot.
#
# ap-south-1 = Mumbai (primary)
# ap-south-2 = Hyderabad (disaster recovery)
#
# If someone ever needs to add a region here, that is a Decision Log entry and
# an ADR superseding 014 — not a quiet edit to this line.
ALLOWED_REGIONS: tuple[str, ...] = ("ap-south-1", "ap-south-2")


class Settings(BaseSettings):
    """
    Every environment-backed configuration value, in one validated object.

    Instantiated once per process via `get_settings()`. Do not construct this
    directly in application code — use the cached accessor so that all callers
    share the same validated instance.
    """

    model_config = SettingsConfigDict(
        env_file=".env",  # local development convenience
        env_file_encoding="utf-8",
        case_sensitive=False,  # DATABASE_URL and database_url both work
        extra="forbid",  # an unrecognised variable is a typo — fail loudly
    )

    # --- Environment --------------------------------------------------------
    app_env: Literal["local", "dev", "staging", "production"] = "local"

    # --- Database -----------------------------------------------------------
    # PostgresDsn validates the URL shape at boot rather than at first connection.
    database_url: PostgresDsn

    # Pool sizing. `pool_size` is the steady-state connection count; overflow is
    # the burst headroom. Kept small by default — see the note in session.py
    # about why connection reuse interacts with tenant context.
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=100)

    # --- Region / residency -------------------------------------------------
    aws_region: str = "ap-south-1"

    # --- Logging ------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # JSON in deployed environments so CloudWatch Logs Insights can query
    # fields directly; console locally because JSON is painful to read by eye.
    log_json: bool = False

    # --- Application --------------------------------------------------------
    default_timezone: str = "Asia/Kolkata"

    @field_validator("aws_region")
    @classmethod
    def region_must_be_in_india(cls, v: str) -> str:
        """
        Reject any region outside the residency allowlist.

        This is the first of several fail-closed residency checks. The others
        live in the LLM and vendor adapters (Phase 3 onward). The pattern is
        deliberate and consistent: residency violations raise, they never warn.

        Raises:
            ValueError: if the configured region is outside India.
        """
        if v not in ALLOWED_REGIONS:
            raise ValueError(
                f"Region {v!r} is outside the residency boundary. "
                f"Allowed: {', '.join(ALLOWED_REGIONS)}. See ADR-014."
            )
        return v

    @property
    def is_production(self) -> bool:
        """True in production. Use to gate debug endpoints and verbose logging."""
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the validated settings object, constructing it on first call.

    Cached because reading and validating the environment on every access would
    be wasteful, and because every caller must see the same values. The cache
    also means a configuration error surfaces exactly once, at startup.

    Returns:
        Settings: the validated configuration for this process.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment

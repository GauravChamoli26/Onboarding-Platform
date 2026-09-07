"""
Business-day arithmetic for approval and feedback deadlines.

WHY THIS IS NOT A ONE-LINER
    "Two business days" looks trivial until you deploy it in India. Diwali alone
    can swallow a two-day window; add a regional holiday either side and a
    calendar-day implementation escalates every pending approval in the company
    while nobody is at work to see it.

    Worse, it fails silently in the direction that looks like the system
    working: deadlines pass, escalations fire, and the only symptom is HR
    complaining that the platform is impatient.

TWO KINDS OF EXCEPTION, NOT ONE
    A holiday calendar that only records non-working days is insufficient here.
    Many Indian employers work alternate Saturdays, so the calendar has to be
    able to express both directions:

        - Diwali falls on a Tuesday and is NOT a working day.
        - The second Saturday IS a working day, despite being a weekend.

    Hence two sets: `holidays` for dates that are not working days, and
    `working_exceptions` for dates that are, despite falling on a weekend.

    Only `holidays` is wired to the database today (the Holiday model).
    `working_exceptions` is supported here so that adding it later is a data
    change rather than a rewrite of the deadline logic.

TIMEZONES
    Whether a moment falls on a holiday depends on the local date, so the
    calculation runs in the organisation's timezone and converts back to UTC at
    the end. Doing the arithmetic in UTC would put an evening deadline in
    Asia/Kolkata on the wrong calendar day.
"""

from collections.abc import Collection
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Fallback when an organisation has no timezone configured. Every deadline is
# computed in local time, so this must never be UTC — a UTC default would put
# end-of-day deadlines five and a half hours early for an Indian customer.
DEFAULT_TIMEZONE = "Asia/Kolkata"

# Python's date.weekday(): Monday is 0, Sunday is 6.
#
# A frozenset rather than a tuple: membership is what every caller tests, and it
# is the type the engine's signatures declare. Immutable so a shared default
# cannot be mutated by a caller.
DEFAULT_WEEKEND_DAYS: frozenset[int] = frozenset({5, 6})  # Saturday, Sunday

# Guard against a runaway loop if a calendar somehow marks every day non-working.
# 400 days is far beyond any legitimate SLA and cheap to check.
_MAX_ITERATIONS = 400


class NoWorkingDaysError(RuntimeError):
    """Raised when a deadline cannot be reached — the calendar has no working days."""


def is_business_day(
    day: date,
    *,
    weekend_days: Collection[int] = DEFAULT_WEEKEND_DAYS,
    holidays: Collection[date] = (),
    working_exceptions: Collection[date] = (),
) -> bool:
    """
    Whether a given date is a working day for an organisation.

    Args:
        day: the date to test, in the organisation's local timezone.
        weekend_days: weekday numbers treated as non-working by default
            (Monday is 0). Configurable because a six-day working week is
            common in India.
        holidays: dates that are not working days regardless of weekday.
        working_exceptions: dates that ARE working days despite falling on a
            weekend — an alternate Saturday, most often.

    Returns:
        bool: True if work happens on this date.

    Precedence: a holiday always wins. A date listed as both is treated as a
    holiday, on the principle that the more restrictive entry is the safer
    reading — an SLA that runs slightly long is a nuisance, one that expires
    while nobody is at work escalates to a person who is not there.
    """
    if day in holidays:
        return False
    if day in working_exceptions:
        return True
    return day.weekday() not in weekend_days


def add_business_days(
    start: datetime,
    business_days: int,
    *,
    timezone: str = "Asia/Kolkata",
    weekend_days: Collection[int] = DEFAULT_WEEKEND_DAYS,
    holidays: Collection[date] = (),
    working_exceptions: Collection[date] = (),
    end_of_day: bool = True,
) -> datetime:
    """
    Add a number of business days to a moment, returning a UTC deadline.

    Args:
        start: when the clock starts. Any timezone; converted internally.
        business_days: how many working days to add. Must be >= 0. Zero returns
            the end of the current working day, or of the next one if `start`
            falls on a non-working day.
        timezone: the organisation's IANA timezone. Holidays are local dates, so
            this determines which day a moment belongs to.
        weekend_days: weekday numbers that are non-working by default.
        holidays: dates that are not working days.
        working_exceptions: weekend dates that are working days anyway.
        end_of_day: if True the deadline is 23:59:59 local on the target date,
            which is what "two business days to approve" means in practice —
            not the same clock time two days later. If False, the original time
            of day is preserved.

    Returns:
        datetime: the deadline, in UTC.

    Raises:
        ValueError: if business_days is negative.
        NoWorkingDaysError: if no working day can be found within a year, which
            means the calendar is misconfigured.

    Counting rule: the start date is not counted, whether or not it is a working
    day. One business day from a Friday afternoon is the end of Monday, not the
    end of Friday. This matches how people read "you have one day to respond".
    """
    if business_days < 0:
        raise ValueError(f"business_days must be non-negative, got {business_days}")

    tz = ZoneInfo(timezone)
    local_start = start.astimezone(tz)
    current = local_start.date()

    if business_days == 0:
        # Zero days means "by the end of the current working day". If the clock
        # started on a holiday, roll forward to the next working day rather than
        # producing a deadline that has already passed.
        iterations = 0
        while not is_business_day(
            current,
            weekend_days=weekend_days,
            holidays=holidays,
            working_exceptions=working_exceptions,
        ):
            current += timedelta(days=1)
            iterations += 1
            if iterations > _MAX_ITERATIONS:
                raise NoWorkingDaysError(
                    f"No working day found within {_MAX_ITERATIONS} days of "
                    f"{local_start.date()}. Check the business calendar and "
                    f"weekend configuration for this organisation."
                )
    else:
        remaining = business_days
        iterations = 0
        while remaining > 0:
            current += timedelta(days=1)
            iterations += 1
            if iterations > _MAX_ITERATIONS:
                raise NoWorkingDaysError(
                    f"Could not add {business_days} business days to "
                    f"{local_start.date()} within {_MAX_ITERATIONS} calendar "
                    f"days. Check the business calendar and weekend "
                    f"configuration for this organisation."
                )
            if is_business_day(
                current,
                weekend_days=weekend_days,
                holidays=holidays,
                working_exceptions=working_exceptions,
            ):
                remaining -= 1

    if end_of_day:
        deadline_local = datetime.combine(current, time(23, 59, 59), tzinfo=tz)
    else:
        deadline_local = datetime.combine(current, local_start.timetz())

    return deadline_local.astimezone(UTC)


def business_days_between(
    start: date,
    end: date,
    *,
    weekend_days: Collection[int] = DEFAULT_WEEKEND_DAYS,
    holidays: Collection[date] = (),
    working_exceptions: Collection[date] = (),
) -> int:
    """
    Count working days between two dates, exclusive of start, inclusive of end.

    Used for reporting — feedback turnaround, time-to-hire — where "three days"
    should mean three working days rather than three calendar days.

    Args:
        start: the earlier date, not counted.
        end: the later date, counted if it is a working day.
        weekend_days: weekday numbers that are non-working by default.
        holidays: dates that are not working days.
        working_exceptions: weekend dates that are working days anyway.

    Returns:
        int: number of working days. Zero if end is on or before start.
    """
    if end <= start:
        return 0

    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if is_business_day(
            current,
            weekend_days=weekend_days,
            holidays=holidays,
            working_exceptions=working_exceptions,
        ):
            count += 1
    return count

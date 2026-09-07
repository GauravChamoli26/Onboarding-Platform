"""
Business-day arithmetic tests.

WHY THESE MATTER
    Every approval deadline and every feedback SLA is computed here. A
    calendar-day implementation looks correct in development and then, during
    Diwali, escalates every pending approval in the company while nobody is at
    work to see it. The failure is silent and it looks like the system working.

    These tests are pure functions with no container, so they run on every push
    in under a second.

DATES USED
    2026-09-04 is a Friday. Every case below is anchored to it so the weekday
    arithmetic is checkable by eye rather than by trusting the test.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from platform_core.approvals.business_days import (
    NoWorkingDaysError,
    add_business_days,
    business_days_between,
    is_business_day,
)

IST = ZoneInfo("Asia/Kolkata")

FRIDAY = datetime(2026, 9, 4, 14, 0, tzinfo=IST)
SATURDAY = date(2026, 9, 5)
SUNDAY = date(2026, 9, 6)
MONDAY = date(2026, 9, 7)
TUESDAY = date(2026, 9, 8)
WEDNESDAY = date(2026, 9, 9)
THURSDAY = date(2026, 9, 10)


def _local_date(moment: datetime) -> date:
    """The local date of a UTC deadline, in the organisation's timezone."""
    return moment.astimezone(IST).date()


# ===========================================================================
# is_business_day
# ===========================================================================


def test_weekdays_are_working_days_by_default() -> None:
    """Monday to Friday are working days with no calendar configured."""
    assert is_business_day(MONDAY)
    assert is_business_day(date(2026, 9, 4))  # Friday


def test_weekends_are_not_working_days_by_default() -> None:
    """Saturday and Sunday are not, absent any override."""
    assert not is_business_day(SATURDAY)
    assert not is_business_day(SUNDAY)


def test_holiday_overrides_a_weekday() -> None:
    """A holiday on a Tuesday is not a working day."""
    assert not is_business_day(TUESDAY, holidays={TUESDAY})


def test_working_exception_overrides_a_weekend() -> None:
    """
    A working Saturday is a working day.

    Alternate-Saturday working is common in India, and a holiday-only calendar
    cannot express it — which would make every deadline computed across such a
    Saturday one day too generous.
    """
    assert is_business_day(SATURDAY, working_exceptions={SATURDAY})


def test_holiday_beats_working_exception() -> None:
    """
    A date listed as both is treated as a holiday.

    The more restrictive reading is the safer one: a deadline that runs
    slightly long is a nuisance, one that expires while nobody is at work
    escalates to a person who is not there to receive it.
    """
    assert not is_business_day(SATURDAY, holidays={SATURDAY}, working_exceptions={SATURDAY})


def test_six_day_week_treats_saturday_as_working() -> None:
    """Configuring Sunday as the only weekend day makes Saturday working."""
    assert is_business_day(SATURDAY, weekend_days={6})


# ===========================================================================
# add_business_days
# ===========================================================================


def test_one_business_day_from_friday_lands_on_monday() -> None:
    """The weekend is skipped."""
    assert _local_date(add_business_days(FRIDAY, 1)) == MONDAY


def test_two_business_days_from_friday_lands_on_tuesday() -> None:
    """Counting resumes after the weekend rather than restarting."""
    assert _local_date(add_business_days(FRIDAY, 2)) == TUESDAY


def test_deadline_skips_a_multi_day_holiday_cluster() -> None:
    """
    A three-day festival cluster pushes a one-day deadline out to Thursday.

    This is the case that motivates the whole module. With calendar days, this
    approval would have expired on Monday with the office closed.
    """
    diwali = {MONDAY, TUESDAY, WEDNESDAY}
    assert _local_date(add_business_days(FRIDAY, 1, holidays=diwali)) == THURSDAY


def test_working_saturday_shortens_the_deadline() -> None:
    """With Saturday declared a working day, one business day is Saturday."""
    result = add_business_days(FRIDAY, 1, working_exceptions={SATURDAY})
    assert _local_date(result) == SATURDAY


def test_six_day_week_shortens_the_deadline() -> None:
    """A six-day working week reaches the same answer by configuration."""
    assert _local_date(add_business_days(FRIDAY, 1, weekend_days={6})) == SATURDAY


def test_deadline_is_end_of_day_local() -> None:
    """
    Deadlines land at 23:59:59 local, not at the same clock time.

    "Two business days to approve" means by the end of that day. Preserving the
    original time would give an approver raised at 09:00 four fewer working
    hours than one raised at 17:00, for the same stated SLA.
    """
    local = add_business_days(FRIDAY, 1).astimezone(IST)
    assert (local.hour, local.minute, local.second) == (23, 59, 59)


def test_deadline_is_returned_in_utc() -> None:
    """Storage is UTC throughout; only the calculation is local."""
    assert add_business_days(FRIDAY, 1).tzinfo == UTC


def test_start_date_is_not_counted() -> None:
    """
    One business day from Friday is Monday, not Friday.

    Matches how people read "you have one day to respond" — the clock starts
    now and you get a full day.
    """
    assert _local_date(add_business_days(FRIDAY, 1)) != date(2026, 9, 4)


def test_zero_days_means_end_of_the_current_working_day() -> None:
    """Zero business days is a same-day deadline."""
    assert _local_date(add_business_days(FRIDAY, 0)) == date(2026, 9, 4)


def test_zero_days_starting_on_a_holiday_rolls_forward() -> None:
    """
    A same-day deadline raised on a holiday moves to the next working day.

    Otherwise the deadline would be in the past the moment it was created, and
    the sweeper would escalate it on its first run.
    """
    monday_morning = datetime(2026, 9, 7, 10, 0, tzinfo=IST)
    result = add_business_days(monday_morning, 0, holidays={MONDAY, TUESDAY, WEDNESDAY})
    assert _local_date(result) == THURSDAY


def test_negative_days_is_rejected() -> None:
    """A negative SLA is a programming error, not a deadline in the past."""
    with pytest.raises(ValueError, match="non-negative"):
        add_business_days(FRIDAY, -1)


def test_calendar_with_no_working_days_raises_rather_than_hanging() -> None:
    """
    A misconfigured calendar fails loudly instead of looping.

    Marking every weekday a holiday is a data-entry mistake that would
    otherwise spin until something times out, with no indication of the cause.
    """
    every_day = {date(2026, 9, 4) + __import__("datetime").timedelta(days=n) for n in range(500)}
    with pytest.raises(NoWorkingDaysError, match="business calendar"):
        add_business_days(FRIDAY, 1, holidays=every_day)


def test_timezone_determines_which_date_a_holiday_falls_on() -> None:
    """
    The calculation runs in the organisation's timezone.

    A late-evening moment in Asia/Kolkata is the previous day in UTC. Doing the
    arithmetic in UTC would compare against the wrong calendar date and skip or
    apply a holiday incorrectly.
    """
    late_friday_ist = datetime(2026, 9, 4, 23, 30, tzinfo=IST)
    assert late_friday_ist.astimezone(UTC).date() == date(2026, 9, 4)
    assert _local_date(add_business_days(late_friday_ist, 1)) == MONDAY


# ===========================================================================
# business_days_between
# ===========================================================================


def test_counts_working_days_excluding_start_including_end() -> None:
    """Friday to the following Friday is five working days."""
    assert business_days_between(date(2026, 9, 4), date(2026, 9, 11)) == 5


def test_count_excludes_holidays() -> None:
    """Holidays in the range are not counted."""
    assert (
        business_days_between(date(2026, 9, 4), date(2026, 9, 11), holidays={MONDAY, TUESDAY}) == 3
    )


def test_count_is_zero_when_end_precedes_start() -> None:
    """An inverted range is zero, not negative."""
    assert business_days_between(date(2026, 9, 11), date(2026, 9, 4)) == 0

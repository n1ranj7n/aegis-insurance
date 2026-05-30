"""Business logic for the Aegis demo.

This module is the single source of truth for two concerns:

1. The **dynamic premium engine** — a No-Claim-Bonus (NCB) recalculation that
   rewards claim-free renewal periods with a tiered discount off the base
   premium, and resets when an approved/settled claim occurs.
2. **Demo-safety guards** — a row cap that keeps a publicly deployed demo from
   filling up the database.

Keeping this logic out of models/views means the same code path is exercised by
the dashboard button, the admin action, and the management command.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    CLAIM_AGAINST_STREAK,
    Claim,
    Policy,
    Policyholder,
    PremiumHistory,
)

# --------------------------------------------------------------------------- #
# No-Claim-Bonus discount tiers
# --------------------------------------------------------------------------- #
# streak 1 -> 5%, 2 -> 10%, 3 -> 15%, 4 -> 20%, 5+ -> 25% (hard cap).
NCB_STEP_PCT = Decimal("5")
NCB_MAX_PCT = Decimal("25")


def discount_for_streak(streak: int) -> Decimal:
    """Return the NCB discount percentage for a given claim-free streak."""
    if streak <= 0:
        return Decimal("0")
    return min(NCB_STEP_PCT * streak, NCB_MAX_PCT)


def premium_for(base_premium: Decimal, streak: int) -> Decimal:
    """Compute the discounted premium for a base premium and streak."""
    pct = discount_for_streak(streak)
    factor = (Decimal("100") - pct) / Decimal("100")
    return (base_premium * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Premium recalculation + renewal simulation
# --------------------------------------------------------------------------- #
def recalculate_premium(
    policy: Policy,
    *,
    reason: str = "Premium recalculation",
    effective_date: dt.date | None = None,
) -> PremiumHistory:
    """Recompute ``policy.current_premium`` from its base premium and streak.

    Persists the new premium on the policy and writes an append-only
    :class:`~insurance.models.PremiumHistory` row. Returns that row.
    """
    effective_date = effective_date or timezone.localdate()
    previous = policy.current_premium
    pct = discount_for_streak(policy.no_claim_streak)
    new_premium = premium_for(policy.base_premium, policy.no_claim_streak)

    policy.current_premium = new_premium
    policy.save()

    return PremiumHistory.objects.create(
        policy=policy,
        effective_date=effective_date,
        previous_premium=previous,
        new_premium=new_premium,
        discount_pct_applied=pct,
        reason=reason,
    )


def _shift_year(d: dt.date, delta: int) -> dt.date:
    """Shift a date by whole years, clamping a Feb-29 source to Feb-28."""
    try:
        return d.replace(year=d.year + delta)
    except ValueError:
        return d.replace(year=d.year + delta, day=28)


@transaction.atomic
def run_renewal(policy: Policy) -> PremiumHistory:
    """Simulate advancing ``policy`` to its next renewal period.

    Closes the 12-month period ending on the current ``renewal_date``:

    * If any **approved or settled** claim falls in that window, the NCB streak
      resets to 0 and the premium returns to base.
    * Otherwise the streak increments and the next NCB discount tier applies.

    The renewal date then advances by one year and a PremiumHistory row is
    written. This lets the NCB logic be demonstrated instantly instead of
    waiting a real year.
    """
    effective = policy.renewal_date
    period_start = _shift_year(effective, -1)

    blocking = policy.claims.filter(
        status__in=CLAIM_AGAINST_STREAK,
        date_of_service__gt=period_start,
        date_of_service__lte=effective,
    )
    blocking_count = blocking.count()

    if blocking_count:
        policy.no_claim_streak = 0
        reason = (
            f"Renewal {effective:%d %b %Y}: {blocking_count} approved/settled "
            f"claim(s) in period — NCB reset, premium returns to base."
        )
    else:
        policy.no_claim_streak += 1
        pct = discount_for_streak(policy.no_claim_streak)
        reason = (
            f"Renewal {effective:%d %b %Y}: claim-free period — NCB streak "
            f"{policy.no_claim_streak} ({pct}% discount)."
        )

    # Open the new term.
    policy.renewal_date = _shift_year(effective, 1)

    return recalculate_premium(policy, reason=reason, effective_date=effective)


# --------------------------------------------------------------------------- #
# Demo-safety: per-table row cap
# --------------------------------------------------------------------------- #
DOMAIN_MODELS = (Policyholder, Policy, Claim)


class DemoLimitReached(Exception):
    """Raised when a write would exceed the configured demo row cap."""


def demo_capacity(model) -> tuple[int, int]:
    """Return ``(rows_used, limit)`` for a domain model."""
    return model.objects.count(), settings.DEMO_ROW_LIMIT


def check_demo_limit(model) -> None:
    """Raise :class:`DemoLimitReached` if ``model`` is at or over the cap."""
    used, limit = demo_capacity(model)
    if used >= limit:
        name = model._meta.verbose_name_plural.title()
        raise DemoLimitReached(
            f"Demo limit reached for {name} ({limit} rows). "
            f"This is a public demo — data resets nightly, so try again later."
        )


def truncate_domain_data() -> None:
    """Wipe all domain rows. Used by the seed/reset management commands.

    On PostgreSQL this uses ``TRUNCATE ... RESTART IDENTITY CASCADE`` so primary
    keys (and therefore the generated policy/claim numbers) start clean again.
    Falls back to ORM deletes on other backends (e.g. the sqlite fallback).
    """
    from django.db import connection

    from .models import Claim, PremiumHistory  # local import avoids cycles

    ordered = [PremiumHistory, Claim, Policy, Policyholder]
    if connection.vendor == "postgresql":
        table_list = ", ".join(f'"{m._meta.db_table}"' for m in ordered)
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE;")
    else:
        for model in ordered:
            model.objects.all().delete()

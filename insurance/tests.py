"""Tests for the premium engine, validation and demo-safety guards."""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings

from .forms import ClaimForm
from .models import (
    Claim,
    ClaimStatus,
    ClaimType,
    Gender,
    PlanType,
    Policy,
    Policyholder,
    PolicyStatus,
    PremiumHistory,
)
from .services import (
    DemoLimitReached,
    check_demo_limit,
    discount_for_streak,
    premium_for,
    recalculate_premium,
    run_renewal,
)


def make_holder(**kw):
    defaults = dict(
        name="Test Holder",
        email="t@example.in",
        date_of_birth=date(1990, 1, 1),
        gender=Gender.MALE,
        phone="+91 9000000000",
    )
    defaults.update(kw)
    return Policyholder.objects.create(**defaults)


def make_policy(streak=0, base=Decimal("20000"), **kw):
    holder = kw.pop("holder", None) or make_holder(email=f"h{Policyholder.objects.count()}@x.in")
    today = date.today()
    defaults = dict(
        policyholder=holder,
        plan_type=PlanType.INDIVIDUAL,
        sum_insured=Decimal("500000"),
        base_premium=base,
        current_premium=premium_for(base, streak),
        no_claim_streak=streak,
        status=PolicyStatus.ACTIVE,
        start_date=today - timedelta(days=400),
        renewal_date=today + timedelta(days=30),
    )
    defaults.update(kw)
    return Policy.objects.create(**defaults)


class DiscountTierTests(TestCase):
    def test_tiers(self):
        self.assertEqual(discount_for_streak(0), Decimal("0"))
        self.assertEqual(discount_for_streak(1), Decimal("5"))
        self.assertEqual(discount_for_streak(2), Decimal("10"))
        self.assertEqual(discount_for_streak(3), Decimal("15"))
        self.assertEqual(discount_for_streak(4), Decimal("20"))
        self.assertEqual(discount_for_streak(5), Decimal("25"))

    def test_cap_at_25(self):
        self.assertEqual(discount_for_streak(6), Decimal("25"))
        self.assertEqual(discount_for_streak(99), Decimal("25"))

    def test_premium_for(self):
        self.assertEqual(premium_for(Decimal("20000"), 0), Decimal("20000.00"))
        self.assertEqual(premium_for(Decimal("20000"), 2), Decimal("18000.00"))
        self.assertEqual(premium_for(Decimal("20000"), 5), Decimal("15000.00"))


class NumberGenerationTests(TestCase):
    def test_policy_and_claim_numbers(self):
        policy = make_policy()
        self.assertTrue(policy.policy_number.startswith("POL-"))
        claim = Claim.objects.create(
            policy=policy,
            claim_amount=Decimal("1000"),
            claim_type=ClaimType.OUTPATIENT,
            date_of_service=date.today(),
        )
        self.assertTrue(claim.claim_number.startswith("CLM-"))


class RecalculateTests(TestCase):
    def test_writes_history_and_updates_premium(self):
        policy = make_policy(streak=2, base=Decimal("20000"))
        policy.current_premium = Decimal("20000")  # pretend no discount applied yet
        policy.save()
        history = recalculate_premium(policy, reason="manual")
        policy.refresh_from_db()
        self.assertEqual(policy.current_premium, Decimal("18000.00"))
        self.assertEqual(history.new_premium, Decimal("18000.00"))
        self.assertEqual(history.discount_pct_applied, Decimal("10"))
        self.assertEqual(PremiumHistory.objects.filter(policy=policy).count(), 1)


class RunRenewalTests(TestCase):
    def test_clean_period_increments_streak(self):
        policy = make_policy(streak=2, base=Decimal("20000"))
        run_renewal(policy)
        policy.refresh_from_db()
        self.assertEqual(policy.no_claim_streak, 3)
        self.assertEqual(policy.current_premium, Decimal("17000.00"))  # 15% off 20000

    def test_approved_claim_in_period_resets_streak(self):
        policy = make_policy(streak=4, base=Decimal("20000"))
        Claim.objects.create(
            policy=policy,
            claim_amount=Decimal("50000"),
            claim_type=ClaimType.HOSPITALIZATION,
            date_of_service=date.today() - timedelta(days=10),
            status=ClaimStatus.APPROVED,
        )
        run_renewal(policy)
        policy.refresh_from_db()
        self.assertEqual(policy.no_claim_streak, 0)
        self.assertEqual(policy.current_premium, Decimal("20000.00"))  # back to base

    def test_submitted_or_rejected_claim_does_not_break_streak(self):
        policy = make_policy(streak=2, base=Decimal("20000"))
        for status in (ClaimStatus.SUBMITTED, ClaimStatus.REJECTED):
            Claim.objects.create(
                policy=policy,
                claim_amount=Decimal("50000"),
                claim_type=ClaimType.DAY_CARE,
                date_of_service=date.today() - timedelta(days=20),
                status=status,
            )
        run_renewal(policy)
        policy.refresh_from_db()
        self.assertEqual(policy.no_claim_streak, 3)  # streak survived

    def test_renewal_date_advances_one_year(self):
        policy = make_policy(streak=0)
        original = policy.renewal_date
        run_renewal(policy)
        policy.refresh_from_db()
        self.assertEqual(policy.renewal_date.year, original.year + 1)

    def test_cap_holds_across_many_renewals(self):
        policy = make_policy(streak=0, base=Decimal("20000"))
        for _ in range(8):
            run_renewal(policy)
            policy.refresh_from_db()
        self.assertEqual(policy.current_premium, Decimal("15000.00"))  # never below 25% off


class ClaimValidationTests(TestCase):
    def test_claim_amount_cannot_exceed_sum_insured(self):
        policy = make_policy(streak=0)  # sum_insured 500000
        form = ClaimForm(
            data={
                "policy": policy.pk,
                "claim_amount": "600000",
                "claim_type": ClaimType.HOSPITALIZATION,
                "hospital_name": "Apollo",
                "date_of_service": date.today().isoformat(),
                "status": ClaimStatus.SUBMITTED,
                "notes": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("claim_amount", form.errors)

    def test_negative_claim_amount_rejected(self):
        policy = make_policy(streak=0)
        form = ClaimForm(
            data={
                "policy": policy.pk,
                "claim_amount": "-100",
                "claim_type": ClaimType.OUTPATIENT,
                "hospital_name": "",
                "date_of_service": date.today().isoformat(),
                "status": ClaimStatus.SUBMITTED,
                "notes": "",
            }
        )
        self.assertFalse(form.is_valid())


@override_settings(DEMO_ROW_LIMIT=2)
class DemoLimitTests(TestCase):
    def test_check_demo_limit_raises_at_cap(self):
        make_holder(email="a@x.in")
        make_holder(email="b@x.in")
        with self.assertRaises(DemoLimitReached):
            check_demo_limit(Policyholder)

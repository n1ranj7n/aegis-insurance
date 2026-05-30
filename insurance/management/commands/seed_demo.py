"""Seed the demo database with realistic, populated sample data.

Run after migrations:  python manage.py seed_demo

Creates the demo staff user, ~15 policyholders, ~20 policies spanning every NCB
tier, and ~25 claims across statuses — so the dashboard and premium logic look
alive immediately. Idempotent: it wipes domain tables first, so re-running is
safe.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from insurance.models import (
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
from insurance.services import premium_for, truncate_domain_data

# Realistic Indian sample data ------------------------------------------------
HOLDERS = [
    ("Aarav Sharma", "M"), ("Diya Patel", "F"), ("Vihaan Reddy", "M"),
    ("Ananya Iyer", "F"), ("Kabir Nair", "M"), ("Saanvi Gupta", "F"),
    ("Arjun Menon", "M"), ("Ishita Banerjee", "F"), ("Reyansh Joshi", "M"),
    ("Myra Desai", "F"), ("Aditya Rao", "M"), ("Kiara Kapoor", "F"),
    ("Vivaan Malhotra", "M"), ("Aadhya Krishnan", "F"), ("Rohan Mehta", "M"),
]

CITIES = [
    "MG Road, Bengaluru 560001", "Andheri West, Mumbai 400053",
    "Banjara Hills, Hyderabad 500034", "Salt Lake, Kolkata 700091",
    "Anna Nagar, Chennai 600040", "Koregaon Park, Pune 411001",
    "Vasant Kunj, New Delhi 110070", "Satellite, Ahmedabad 380015",
]

HOSPITALS = [
    "Apollo Hospitals", "Fortis Healthcare", "Max Super Speciality",
    "Manipal Hospital", "Narayana Health", "Medanta - The Medicity",
    "Kokilaben Dhirubhai Ambani Hospital", "AIIMS",
]

# Sum-insured tiers (₹3L – ₹50L) paired with a realistic annual base premium.
PLAN_FIGURES = {
    PlanType.INDIVIDUAL: [
        (Decimal("300000"), Decimal("8200")),
        (Decimal("500000"), Decimal("11500")),
        (Decimal("1000000"), Decimal("16800")),
    ],
    PlanType.FAMILY_FLOATER: [
        (Decimal("1000000"), Decimal("21000")),
        (Decimal("2000000"), Decimal("28500")),
        (Decimal("5000000"), Decimal("39500")),
    ],
    PlanType.SENIOR_CITIZEN: [
        (Decimal("500000"), Decimal("18500")),
        (Decimal("1000000"), Decimal("27000")),
        (Decimal("2000000"), Decimal("36000")),
    ],
}

# 20 policies; explicit streaks chosen so every NCB tier (0–25%) is visible.
POLICY_PLAN_STREAK = [
    (PlanType.INDIVIDUAL, 0), (PlanType.INDIVIDUAL, 1), (PlanType.INDIVIDUAL, 3),
    (PlanType.INDIVIDUAL, 5), (PlanType.FAMILY_FLOATER, 0), (PlanType.FAMILY_FLOATER, 2),
    (PlanType.FAMILY_FLOATER, 4), (PlanType.FAMILY_FLOATER, 6), (PlanType.SENIOR_CITIZEN, 1),
    (PlanType.SENIOR_CITIZEN, 2), (PlanType.SENIOR_CITIZEN, 3), (PlanType.INDIVIDUAL, 2),
    (PlanType.FAMILY_FLOATER, 5), (PlanType.SENIOR_CITIZEN, 4), (PlanType.INDIVIDUAL, 4),
    (PlanType.FAMILY_FLOATER, 1), (PlanType.SENIOR_CITIZEN, 0), (PlanType.INDIVIDUAL, 6),
    (PlanType.FAMILY_FLOATER, 3), (PlanType.SENIOR_CITIZEN, 5),
]


class Command(BaseCommand):
    help = "Seed the demo database with sample policyholders, policies and claims."

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(42)  # deterministic, repeatable demo data
        today = timezone.localdate()

        self.stdout.write("Wiping existing domain data...")
        truncate_domain_data()

        # --- Demo staff user -------------------------------------------------
        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username=settings.DEMO_USERNAME,
            defaults={"email": "demo@aegis.example", "is_staff": True, "is_superuser": True},
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password(settings.DEMO_PASSWORD)
        user.save()
        self.stdout.write(
            f"Demo user ready: {settings.DEMO_USERNAME} / {settings.DEMO_PASSWORD}"
        )

        # --- Policyholders ---------------------------------------------------
        holders = []
        for i, (name, gender) in enumerate(HOLDERS):
            is_senior = i % 5 == 0
            age = rng.randint(58, 74) if is_senior else rng.randint(24, 52)
            dob = today - timedelta(days=age * 365 + rng.randint(0, 364))
            first = name.split()[0].lower()
            holder = Policyholder.objects.create(
                name=name,
                email=f"{first}.{i+1}@example.in",
                date_of_birth=dob,
                gender=gender,
                phone=f"+91 9{rng.randint(100000000, 999999999)}",
                address=rng.choice(CITIES),
                created_at=timezone.now() - timedelta(days=rng.randint(30, 400)),
            )
            holders.append(holder)
        self.stdout.write(f"Created {len(holders)} policyholders.")

        # --- Policies (every NCB tier represented) ---------------------------
        policies = []
        for idx, (plan, streak) in enumerate(POLICY_PLAN_STREAK):
            sum_insured, base_premium = rng.choice(PLAN_FIGURES[plan])
            holder = holders[idx % len(holders)]
            current = premium_for(base_premium, streak)
            # Renewal due soon so "Run Renewal" is meaningful; term began streak+1 years ago.
            renewal_date = today + timedelta(days=rng.randint(8, 90))
            start_date = renewal_date.replace(year=renewal_date.year - (streak + 1))
            policy = Policy.objects.create(
                policyholder=holder,
                plan_type=plan,
                sum_insured=sum_insured,
                base_premium=base_premium,
                current_premium=current,
                no_claim_streak=streak,
                status=PolicyStatus.ACTIVE if rng.random() > 0.1 else PolicyStatus.LAPSED,
                start_date=start_date,
                renewal_date=renewal_date,
            )
            policies.append(policy)

            # Baseline audit row so the premium-history table is populated.
            if streak > 0:
                pct = (Decimal("100") - (current / base_premium * Decimal("100"))).quantize(
                    Decimal("0.01")
                )
                PremiumHistory.objects.create(
                    policy=policy,
                    effective_date=start_date,
                    previous_premium=base_premium,
                    new_premium=current,
                    discount_pct_applied=pct,
                    reason=f"Opening NCB position — {streak} claim-free period(s).",
                )
        self.stdout.write(f"Created {len(policies)} policies across all plan types & NCB tiers.")

        # --- Claims ----------------------------------------------------------
        # Keep it coherent: approved/settled claims (which break the streak) only
        # land on low-streak policies; non-breaking claims can go anywhere.
        low_streak = [p for p in policies if p.no_claim_streak <= 1]
        breaking_specs = [
            (ClaimStatus.APPROVED, ClaimType.HOSPITALIZATION),
            (ClaimStatus.SETTLED, ClaimType.CRITICAL_ILLNESS),
            (ClaimStatus.APPROVED, ClaimType.DAY_CARE),
            (ClaimStatus.SETTLED, ClaimType.HOSPITALIZATION),
            (ClaimStatus.APPROVED, ClaimType.HOSPITALIZATION),
            (ClaimStatus.SETTLED, ClaimType.DAY_CARE),
            (ClaimStatus.APPROVED, ClaimType.CRITICAL_ILLNESS),
            (ClaimStatus.SETTLED, ClaimType.HOSPITALIZATION),
        ]
        nonbreaking_specs = [
            (ClaimStatus.SUBMITTED, ClaimType.OUTPATIENT),
            (ClaimStatus.REJECTED, ClaimType.OUTPATIENT),
            (ClaimStatus.SUBMITTED, ClaimType.DAY_CARE),
            (ClaimStatus.REJECTED, ClaimType.HOSPITALIZATION),
            (ClaimStatus.SUBMITTED, ClaimType.HOSPITALIZATION),
            (ClaimStatus.SUBMITTED, ClaimType.OUTPATIENT),
            (ClaimStatus.REJECTED, ClaimType.DAY_CARE),
        ]

        claim_count = 0

        def make_claim(policy, status, ctype):
            nonlocal claim_count
            cap = policy.sum_insured
            if ctype == ClaimType.OUTPATIENT:
                amount = Decimal(rng.randint(2000, 25000))
            elif ctype == ClaimType.DAY_CARE:
                amount = Decimal(rng.randint(15000, 90000))
            else:
                amount = Decimal(rng.randint(60000, int(min(cap, Decimal("900000")))))
            amount = min(amount, cap - Decimal("1"))
            Claim.objects.create(
                policy=policy,
                claim_amount=amount,
                claim_type=ctype,
                hospital_name=rng.choice(HOSPITALS),
                date_of_service=today - timedelta(days=rng.randint(20, 320)),
                status=status,
                notes=rng.choice(
                    ["Cashless approved at network hospital.", "Reimbursement claim.",
                     "Pre-authorisation processed.", "Documents under review.", ""]
                ),
                created_at=timezone.now() - timedelta(days=rng.randint(5, 60)),
            )
            claim_count += 1

        targets = low_streak or policies
        for status, ctype in breaking_specs:
            make_claim(rng.choice(targets), status, ctype)
        for status, ctype in nonbreaking_specs:
            make_claim(rng.choice(policies), status, ctype)
        # A few extra varied claims to reach ~25, keeping NCB state coherent:
        # streak-breaking statuses only land on low-streak policies.
        for _ in range(10):
            status = rng.choice(
                [ClaimStatus.SUBMITTED, ClaimStatus.APPROVED, ClaimStatus.SETTLED, ClaimStatus.REJECTED]
            )
            if status in (ClaimStatus.APPROVED, ClaimStatus.SETTLED):
                policy = rng.choice(targets)
            else:
                policy = rng.choice(policies)
            make_claim(policy, status, ClaimType(rng.choice(ClaimType.values)))

        self.stdout.write(f"Created {claim_count} claims across all statuses & types.")
        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))

"""Views for the Aegis dashboard and CRUD flows.

Write views are wrapped by :func:`write_guard`, which combines login, per-IP
POST rate limiting (django-ratelimit), and a friendly throttle message.
"""

from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .forms import ClaimForm, PolicyForm, PolicyholderForm
from .models import (
    Claim,
    ClaimStatus,
    ClaimType,
    Policy,
    Policyholder,
    PolicyStatus,
)
from .services import (
    DemoLimitReached,
    check_demo_limit,
    demo_capacity,
    run_renewal,
)


# --------------------------------------------------------------------------- #
# Write guard: auth + per-IP rate limit + friendly throttle message
# --------------------------------------------------------------------------- #
def _write_rate(group, request):
    """Rate string for django-ratelimit, sourced from settings/env."""
    return settings.DEMO_WRITE_RATE


def write_guard(view_func):
    @wraps(view_func)
    @login_required
    @ratelimit(key="ip", rate=_write_rate, method="POST", block=False)
    def _wrapped(request, *args, **kwargs):
        if getattr(request, "limited", False):
            messages.error(
                request,
                "Too many submissions from your network — this demo throttles "
                "writes. Please slow down and try again in a moment.",
            )
            back = request.META.get("HTTP_REFERER") or reverse("dashboard")
            return redirect(back)
        return view_func(request, *args, **kwargs)

    return _wrapped


def _guard_create(request, model):
    """Return True (and queue a message) if the model is at its demo row cap."""
    try:
        check_demo_limit(model)
    except DemoLimitReached as exc:
        messages.warning(request, str(exc))
        return True
    return False


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@login_required
def dashboard(request):
    active_policies = Policy.objects.filter(status=PolicyStatus.ACTIVE)

    premium_pool = active_policies.aggregate(total=Sum("current_premium"))["total"] or 0

    # Average applied discount across active policies (property → computed in
    # Python; the dataset is small and bounded by the demo row cap).
    discounts = [p.discount_pct_applied for p in active_policies]
    avg_discount = round(sum(discounts) / len(discounts), 1) if discounts else 0

    kpis = {
        "total_policyholders": Policyholder.objects.count(),
        "active_policies": active_policies.count(),
        "total_claims": Claim.objects.count(),
        "premium_pool": premium_pool,
        "avg_discount": avg_discount,
    }

    # Chart 1: claims by type.
    type_counts = dict(
        Claim.objects.values_list("claim_type")
        .annotate(n=Count("id"))
        .values_list("claim_type", "n")
    )
    claims_by_type = {
        "labels": [label for _, label in ClaimType.choices],
        "data": [type_counts.get(value, 0) for value, _ in ClaimType.choices],
    }

    # Chart 2: premium-discount distribution (policies bucketed by NCB tier).
    tiers = [0, 5, 10, 15, 20, 25]
    bucket = {t: 0 for t in tiers}
    for p in Policy.objects.all():
        pct = int(round(float(p.discount_pct_applied)))
        nearest = min(tiers, key=lambda t: abs(t - pct))
        bucket[nearest] += 1
    discount_distribution = {
        "labels": [f"{t}%" for t in tiers],
        "data": [bucket[t] for t in tiers],
    }

    context = {
        "kpis": kpis,
        "recent_claims": Claim.objects.select_related(
            "policy", "policy__policyholder"
        )[:6],
        "top_streaks": Policy.objects.select_related("policyholder").order_by(
            "-no_claim_streak", "policy_number"
        )[:6],
        # Passed as Python dicts; the template's {{ ...|json_script }} serializes them.
        "claims_by_type": claims_by_type,
        "discount_distribution": discount_distribution,
    }
    return render(request, "insurance/dashboard.html", context)


# --------------------------------------------------------------------------- #
# Policyholders
# --------------------------------------------------------------------------- #
@login_required
def policyholder_list(request):
    qs = Policyholder.objects.annotate(policy_count=Count("policies"))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "insurance/policyholder_list.html", {"page_obj": page})


@login_required
def policyholder_detail(request, pk):
    holder = get_object_or_404(Policyholder, pk=pk)
    return render(
        request,
        "insurance/policyholder_detail.html",
        {"holder": holder, "policies": holder.policies.select_related("policyholder")},
    )


@write_guard
def policyholder_create(request):
    used, limit = demo_capacity(Policyholder)
    at_capacity = used >= limit

    if request.method == "POST":
        if _guard_create(request, Policyholder):
            return redirect("policyholder_list")
        form = PolicyholderForm(request.POST)
        if form.is_valid():
            holder = form.save()
            messages.success(request, f"Policyholder “{holder.name}” added.")
            return redirect("policyholder_detail", pk=holder.pk)
    else:
        form = PolicyholderForm()

    return render(
        request,
        "insurance/policyholder_form.html",
        {"form": form, "at_capacity": at_capacity, "used": used, "limit": limit},
    )


# --------------------------------------------------------------------------- #
# Policies
# --------------------------------------------------------------------------- #
@login_required
def policy_list(request):
    qs = Policy.objects.select_related("policyholder").annotate(
        claim_count=Count("claims")
    )
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "insurance/policy_list.html", {"page_obj": page})


@login_required
def policy_detail(request, pk):
    policy = get_object_or_404(Policy.objects.select_related("policyholder"), pk=pk)
    return render(
        request,
        "insurance/policy_detail.html",
        {
            "policy": policy,
            "claims": policy.claims.all(),
            "history": policy.premium_history.all(),
        },
    )


@write_guard
def policy_create(request):
    used, limit = demo_capacity(Policy)
    at_capacity = used >= limit

    if request.method == "POST":
        if _guard_create(request, Policy):
            return redirect("policy_list")
        form = PolicyForm(request.POST)
        if form.is_valid():
            policy = form.save()
            messages.success(request, f"Policy {policy.policy_number} created.")
            return redirect("policy_detail", pk=policy.pk)
    else:
        form = PolicyForm()

    return render(
        request,
        "insurance/policy_form.html",
        {"form": form, "at_capacity": at_capacity, "used": used, "limit": limit},
    )


@write_guard
@require_POST
def policy_run_renewal(request, pk):
    policy = get_object_or_404(Policy, pk=pk)
    history = run_renewal(policy)
    messages.success(
        request,
        f"Renewal run for {policy.policy_number}: premium "
        f"₹{history.previous_premium:,.0f} → ₹{history.new_premium:,.0f} "
        f"({history.discount_pct_applied:g}% NCB discount, streak {policy.no_claim_streak}).",
    )
    return redirect("policy_detail", pk=policy.pk)


# --------------------------------------------------------------------------- #
# Claims
# --------------------------------------------------------------------------- #
@login_required
def claim_list(request):
    qs = Claim.objects.select_related("policy", "policy__policyholder")
    status = request.GET.get("status")
    if status in ClaimStatus.values:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "insurance/claim_list.html",
        {"page_obj": page, "statuses": ClaimStatus.choices, "active_status": status},
    )


@write_guard
def claim_create(request):
    used, limit = demo_capacity(Claim)
    at_capacity = used >= limit

    if request.method == "POST":
        if _guard_create(request, Claim):
            return redirect("claim_list")
        form = ClaimForm(request.POST)
        if form.is_valid():
            claim = form.save()
            messages.success(request, f"Claim {claim.claim_number} recorded.")
            return redirect("claim_list")
    else:
        initial = {}
        if request.GET.get("policy"):
            initial["policy"] = request.GET["policy"]
        form = ClaimForm(initial=initial)

    return render(
        request,
        "insurance/claim_form.html",
        {
            "form": form,
            "at_capacity": at_capacity,
            "used": used,
            "limit": limit,
            "editing": False,
        },
    )


@write_guard
def claim_edit(request, pk):
    claim = get_object_or_404(Claim, pk=pk)
    if request.method == "POST":
        form = ClaimForm(request.POST, instance=claim)
        if form.is_valid():
            form.save()
            messages.success(request, f"Claim {claim.claim_number} updated.")
            return redirect("claim_list")
    else:
        form = ClaimForm(instance=claim)
    return render(
        request,
        "insurance/claim_form.html",
        {"form": form, "editing": True, "claim": claim},
    )


@write_guard
@require_POST
def claim_set_status(request, pk, new_status):
    claim = get_object_or_404(Claim, pk=pk)
    if new_status not in ClaimStatus.values:
        messages.error(request, "Unknown claim status.")
        return redirect("claim_list")
    claim.status = new_status
    claim.save(update_fields=["status"])
    messages.success(
        request, f"Claim {claim.claim_number} marked {claim.get_status_display()}."
    )
    back = request.META.get("HTTP_REFERER") or reverse("claim_list")
    return redirect(back)

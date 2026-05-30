"""Django admin registration with the Run-Renewal action."""

from django.contrib import admin, messages

from .models import Claim, Policy, Policyholder, PremiumHistory
from .services import run_renewal


@admin.action(description="Run renewal (advance NCB period)")
def run_renewal_action(modeladmin, request, queryset):
    """Admin action: simulate a renewal for each selected policy."""
    count = 0
    for policy in queryset:
        run_renewal(policy)
        count += 1
    modeladmin.message_user(
        request,
        f"Ran renewal for {count} policy(ies). Premiums and NCB streaks updated.",
        level=messages.SUCCESS,
    )


class PolicyInline(admin.TabularInline):
    model = Policy
    extra = 0
    fields = ("policy_number", "plan_type", "sum_insured", "current_premium", "status")
    readonly_fields = ("policy_number",)
    show_change_link = True


class ClaimInline(admin.TabularInline):
    model = Claim
    extra = 0
    fields = ("claim_number", "claim_type", "claim_amount", "status", "date_of_service")
    readonly_fields = ("claim_number",)
    show_change_link = True


class PremiumHistoryInline(admin.TabularInline):
    model = PremiumHistory
    extra = 0
    can_delete = False
    fields = ("effective_date", "previous_premium", "new_premium", "discount_pct_applied", "reason")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Policyholder)
class PolicyholderAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "gender", "age", "phone", "created_at")
    list_filter = ("gender", "created_at")
    search_fields = ("name", "email", "phone")
    date_hierarchy = "created_at"
    inlines = [PolicyInline]


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = (
        "policy_number",
        "policyholder",
        "plan_type",
        "sum_insured",
        "base_premium",
        "current_premium",
        "discount_pct_applied",
        "no_claim_streak",
        "status",
        "renewal_date",
    )
    list_filter = ("plan_type", "status", "no_claim_streak")
    search_fields = ("policy_number", "policyholder__name", "policyholder__email")
    autocomplete_fields = ("policyholder",)
    readonly_fields = ("policy_number", "current_premium", "discount_pct_applied")
    date_hierarchy = "renewal_date"
    actions = [run_renewal_action]
    inlines = [ClaimInline, PremiumHistoryInline]

    @admin.display(description="Discount")
    def discount_pct_applied(self, obj):
        return f"{obj.discount_pct_applied}%"


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = (
        "claim_number",
        "policy",
        "claim_type",
        "claim_amount",
        "hospital_name",
        "status",
        "date_of_service",
    )
    list_filter = ("status", "claim_type", "date_of_service")
    search_fields = ("claim_number", "policy__policy_number", "hospital_name")
    autocomplete_fields = ("policy",)
    date_hierarchy = "date_of_service"


@admin.register(PremiumHistory)
class PremiumHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "policy",
        "effective_date",
        "previous_premium",
        "new_premium",
        "discount_pct_applied",
        "reason",
    )
    list_filter = ("effective_date",)
    search_fields = ("policy__policy_number", "reason")
    date_hierarchy = "effective_date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

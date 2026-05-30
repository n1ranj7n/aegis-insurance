from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Policyholders
    path("policyholders/", views.policyholder_list, name="policyholder_list"),
    path("policyholders/add/", views.policyholder_create, name="policyholder_create"),
    path("policyholders/<int:pk>/", views.policyholder_detail, name="policyholder_detail"),
    # Policies
    path("policies/", views.policy_list, name="policy_list"),
    path("policies/add/", views.policy_create, name="policy_create"),
    path("policies/<int:pk>/", views.policy_detail, name="policy_detail"),
    path("policies/<int:pk>/run-renewal/", views.policy_run_renewal, name="policy_run_renewal"),
    # Claims
    path("claims/", views.claim_list, name="claim_list"),
    path("claims/add/", views.claim_create, name="claim_create"),
    path("claims/<int:pk>/edit/", views.claim_edit, name="claim_edit"),
    path("claims/<int:pk>/status/<str:new_status>/", views.claim_set_status, name="claim_set_status"),
]

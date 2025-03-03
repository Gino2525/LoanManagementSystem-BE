from django.urls import path
from .views import (
    RegisterView, VerifyOTPView, CustomLoginView,
    LoanCreateView, LoanListView, LoanDetailView, LoanForeclosureView,
    AdminLoanListView, LoanDeleteView
)

urlpatterns = [
    # ✅ Authentication Endpoints
    path("register/", RegisterView.as_view(), name="register"),
    path("verify-email/", VerifyOTPView.as_view(), name="verify-email"),
    path("login/", CustomLoginView.as_view(), name="token_obtain_pair"),

    # ✅ Loan Management (User)
    path("loans/add/", LoanCreateView.as_view(), name="add-loan"),
    path("loans/", LoanListView.as_view(), name="list-loans"),
    path("loans/<int:id>/", LoanDetailView.as_view(), name="loan-detail"),
    path("loans/<int:id>/foreclose/", LoanForeclosureView.as_view(), name="loan-foreclosure"),

    # ✅ Loan Management (Admin)
    path("admin/loans/", AdminLoanListView.as_view(), name="admin-loan-list"),
    path("admin/loans/<int:id>/delete/", LoanDeleteView.as_view(), name="admin-loan-delete"),
]

from rest_framework.permissions import BasePermission

class IsAdminUser(BasePermission):
    """Allows access only to admin users"""
    def has_permission(self, request, view):
        return request.user and request.user.is_staff  # ✅ Admin users only

class IsLoanOwner(BasePermission):
    """Allows access only to loan owners or admins"""
    def has_object_permission(self, request, view, obj):
        return request.user == obj.user or request.user.is_staff  # ✅ Loan owner or admin

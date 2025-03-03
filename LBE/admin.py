from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Loan

# ✅ CustomUserAdmin with better filtering & ordering
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('id', 'username', 'email', 'is_verified', 'is_staff', 'is_superuser', 'date_joined')
    list_filter = ('is_verified', 'is_staff', 'is_superuser', 'date_joined')
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Permissions', {'fields': ('is_verified', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'is_verified', 'is_staff', 'is_superuser')}
        ),
    )
    search_fields = ('username', 'email')
    ordering = ('date_joined',)
    filter_horizontal = ('groups', 'user_permissions')

# ✅ LoanAdmin with better filtering & searching
class LoanAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'amount', 'tenure', 'interest_rate', 'monthly_installment', 'total_amount', 'status', 'created_at')
    search_fields = ('user__username', 'user__email')
    list_filter = ('status', 'created_at', 'tenure')
    ordering = ('-created_at',)  # Show latest loans first
    readonly_fields = ('monthly_installment', 'total_interest', 'total_amount', 'next_due_date')

# ✅ Register models correctly
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Loan, LoanAdmin)  # ✅ LoanAdmin now shows extra details

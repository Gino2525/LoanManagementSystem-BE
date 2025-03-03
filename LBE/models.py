from django.contrib.auth.models import AbstractUser
from django.db import models
import datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta  # ✅ Fixes incorrect date handling
from decimal import Decimal

class CustomUser(AbstractUser):
    is_verified = models.BooleanField(default=False)
    otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)

    USERNAME_FIELD = 'username'  # ✅ Use username for login
    REQUIRED_FIELDS = ['email']  # ✅ Email is required but not used for login

    def is_otp_valid(self):
        """Check if OTP is valid (e.g., not older than 5 minutes)"""
        if self.otp_created_at:
            now = datetime.datetime.now(datetime.timezone.utc)
            return (now - self.otp_created_at).total_seconds() < 300  # 5 min expiry
        return False

    def __str__(self):
        return self.username


# ✅ Loan Model with Corrected Compound Interest & Foreclosure Handling
class Loan(models.Model):
    user = models.ForeignKey('CustomUser', on_delete=models.CASCADE, related_name="loans")
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # Loan amount
    tenure = models.IntegerField()  # Loan tenure in months
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2)  # Yearly interest rate
    monthly_installment = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total_interest = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)  # Amount paid so far
    created_at = models.DateTimeField(auto_now_add=True)
    next_due_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=[('ACTIVE', 'Active'), ('CLOSED', 'Closed')], default='ACTIVE')

    def calculate_loan(self):
        """Calculate monthly installment and total amount payable using compound interest formula"""
        yearly_rate = Decimal(self.interest_rate) / 100
        monthly_rate = yearly_rate / 12
        months = self.tenure

        if monthly_rate > 0:
            emi = (self.amount * monthly_rate * ((1 + monthly_rate) ** months)) / (((1 + monthly_rate) ** months) - 1)
        else:
            emi = self.amount / months  # ✅ Handles 0% interest case properly

        self.monthly_installment = round(emi, 2)
        self.total_interest = round((self.monthly_installment * months) - self.amount, 2)
        self.total_amount = round(self.amount + self.total_interest, 2)
        self.next_due_date = datetime.date.today() + relativedelta(months=1)  # ✅ Fix: Uses relativedelta for correct monthly intervals
        self.save()

    def foreclose_loan(self):
        """Foreclose loan with adjusted interest calculation"""
        if self.status == "CLOSED":
            return {"error": "Loan is already closed."}

        remaining_months = max(Decimal(self.tenure) - (self.amount_paid / self.monthly_installment), 0)  # ✅ Fix: Ensures non-negative values

        remaining_interest = (self.total_interest / self.tenure) * remaining_months
        discount = remaining_interest * Decimal(0.05)  # ✅ Fix: Ensures Decimal precision
        final_settlement = (self.total_amount - self.amount_paid) - discount

        self.status = "CLOSED"
        self.amount_paid = self.total_amount
        self.save()

        return {
            "foreclosure_discount": round(discount, 2),
            "final_settlement_amount": round(final_settlement, 2),
            "status": self.status
        }

    def generate_payment_schedule(self):
        """Generate a detailed payment schedule with due dates and EMI amounts."""
        schedule = []
        current_due_date = datetime.date.today()
        
        for i in range(1, self.tenure + 1):
            schedule.append({
                "installment_no": i,
                "due_date": current_due_date.strftime('%Y-%m-%d'),
                "amount": self.monthly_installment
            })
            current_due_date += relativedelta(months=1)  # ✅ Fix: Uses correct month-based intervals
        
        return schedule

    def __str__(self):
        return f"Loan {self.id} - {self.user.username} ({self.status})"

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
import random
import datetime
from decimal import Decimal

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password')

    def create(self, validated_data):
        user = User(
            username=validated_data["username"],
            email=validated_data["email"]
        )
        user.set_password(validated_data["password"])  # ✅ Hash password properly
        user.is_active = False  # ✅ Prevent login until email verification
        user.save()
        return user


class VerifyOTPSerializer(serializers.Serializer):
    username_or_email = serializers.CharField(required=True)  # ✅ Accept both username and email
    otp = serializers.CharField(max_length=6, required=True)

    def validate(self, data):
        """Check if the OTP is correct and valid."""
        username_or_email = data.get("username_or_email")
        otp = data.get("otp")

        user = User.objects.filter(username=username_or_email).first() or User.objects.filter(email=username_or_email).first()

        if not user:
            raise serializers.ValidationError({"username_or_email": "User not found!"})

        if user.otp != otp:
            raise serializers.ValidationError({"otp": "Invalid OTP!"})

        if not user.is_otp_valid():
            raise serializers.ValidationError({"otp": "OTP has expired!"})

        return data

    
# class LoginSerializer(serializers.Serializer):
#     email = serializers.EmailField()
#     password = serializers.CharField(write_only=True)

#     def validate(self, data):
#         email = data.get("email")
#         password = data.get("password")

#         user = authenticate(username=email, password=password)

#         if user is None:
#             raise serializers.ValidationError("Invalid email or password.")

#         if not user.is_verified:  # ✅ Block unverified users
#             raise serializers.ValidationError("Your email is not verified. Please verify your email.")

#         # Generate JWT token
#         refresh = RefreshToken.for_user(user)
#         return {
#             "refresh": str(refresh),
#             "access": str(refresh.access_token),
#         }


from rest_framework import serializers
from .models import Loan

class LoanSerializer(serializers.ModelSerializer):
    loan_id = serializers.SerializerMethodField()
    amount_remaining = serializers.SerializerMethodField()
    payment_schedule = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            'loan_id', 'amount', 'tenure', 'interest_rate', 'monthly_installment',
            'total_interest', 'total_amount', 'amount_paid', 'amount_remaining',
            'next_due_date', 'status', 'created_at', 'payment_schedule'
        ]
        read_only_fields = ['monthly_installment', 'total_interest', 'total_amount', 
                            'next_due_date', 'status', 'amount_paid', 'amount_remaining', 'payment_schedule']

    def get_loan_id(self, obj):
        return f"LOAN{obj.id:03}"  # Example: LOAN001, LOAN002

    def get_amount_remaining(self, obj):
        """Ensure both values are Decimal before subtraction"""
        return round(Decimal(obj.total_amount) - Decimal(obj.amount_paid), 2)

    def get_payment_schedule(self, obj):
        return obj.generate_payment_schedule()

    
    def validate_interest_rate(self, value):
        """Ensure interest rate is a positive number"""
        if value <= 0:
            raise serializers.ValidationError("Interest rate must be a positive value.")
        return value
    
    def validate_tenure(self, value):
        """Validate tenure is between 3 and 24 months"""
        if value < 3 or value > 24:
            raise serializers.ValidationError("Loan tenure must be between 3 and 24 months.")
        return value
    
    def validate_amount(self, value):
        """Validate loan amount is between ₹1,000 and ₹100,000"""
        if value < 1000 or value > 100000:
            raise serializers.ValidationError("Loan amount must be between ₹1,000 and ₹100,000.")
        return value
    
    def create(self, validated_data):
        loan = Loan.objects.create(**validated_data)
        loan.calculate_loan()  # Auto-calculate loan details
        return loan
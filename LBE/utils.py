import random
from django.core.mail import send_mail
from django.utils.timezone import now

def generate_otp():
    """Generate a 6-digit OTP."""
    return str(random.randint(100000, 999999))

def send_otp_email(user):
    """Generate and send OTP to the user's email."""
    otp = generate_otp()
    user.otp = otp
    user.otp_created_at = now()
    user.save()

    send_mail(
        subject="Your OTP Code",
        message=f"Your OTP code is {otp}. It expires in 5 minutes.",
        from_email="noreply@yourdomain.com",
        recipient_list=[user.email],
    )

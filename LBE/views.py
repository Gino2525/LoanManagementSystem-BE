from rest_framework.response import Response
from rest_framework import status, generics
from django.contrib.auth import get_user_model
from .serializers import RegisterSerializer, VerifyOTPSerializer, LoanSerializer
from .utils import send_otp_email
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from .models import Loan
from .permissions import IsAdminUser, IsLoanOwner

User = get_user_model()


# ✅ Custom Login View
class CustomLoginView(APIView):
    def post(self, request, *args, **kwargs):
        username = request.data.get("username")
        password = request.data.get("password")

        print(f"🔍 Authenticating user: {username}")  
        user = authenticate(username=username, password=password)

        if not user:
            print("❌ Authentication failed!")  
            return Response({"error": "Invalid username or password"}, status=status.HTTP_401_UNAUTHORIZED)
        if not user.is_verified:
            return Response({"error": "Verify email"}, status=status.HTTP_401_UNAUTHORIZED)
        if not user.is_active:
            return Response({"error": "Your account is inactive. Please verify your email."}, status=status.HTTP_403_FORBIDDEN)

        print("✅ Authentication successful!")  

        refresh = RefreshToken.for_user(user)
        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "message": "Login successful"
        }, status=status.HTTP_200_OK)


# ✅ User Registration API
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        user = User(
            username=validated_data["username"],
            email=validated_data["email"]
        )
        user.set_password(validated_data["password"])  
        user.save()

        send_otp_email(user)  

        return Response({"message": "User registered successfully! OTP sent to email."}, status=status.HTTP_201_CREATED)


# ✅ OTP Verification API
class VerifyOTPView(generics.GenericAPIView):
    serializer_class = VerifyOTPSerializer  

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username_or_email = serializer.validated_data.get("username_or_email")  
        otp = serializer.validated_data.get("otp")

        user = User.objects.filter(username=username_or_email).first() or User.objects.filter(email=username_or_email).first()

        if not user:
            return Response({"error": "User not found!"}, status=status.HTTP_404_NOT_FOUND)

        if user.otp == otp and user.is_otp_valid():
            user.is_verified = True
            user.otp = None  
            user.otp_created_at = None
            user.save()

            return Response({"message": "Account verified successfully!"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Invalid or expired OTP!"}, status=status.HTTP_400_BAD_REQUEST)


# ✅ Add Loan (User Only)
class LoanCreateView(generics.CreateAPIView):
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)  


# ✅ List Active & Past Loans (User Only)
class LoanListView(generics.ListAPIView):
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Loan.objects.filter(user=self.request.user)


# ✅ View Loan Details (User or Admin)
class LoanDetailView(generics.RetrieveAPIView):
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated, IsLoanOwner]
    lookup_field = "id"

    def get_queryset(self):
        return Loan.objects.all()  


# ✅ Foreclose Loan (User Only)
class LoanForeclosureView(generics.UpdateAPIView):
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated, IsLoanOwner]
    lookup_field = "id"

    def get_queryset(self):
        return Loan.objects.filter(user=self.request.user, status="ACTIVE")  

    def update(self, request, *args, **kwargs):
        loan = self.get_object()  
        if loan.status == "CLOSED":
            return Response({"error": "Loan is already closed"}, status=status.HTTP_400_BAD_REQUEST)

        foreclosure_result = loan.foreclose_loan()
        return Response({
            "status": "success",
            "message": "Loan foreclosed successfully.",
            "data": {
                "loan_id": f"LOAN{loan.id:03}",
                "amount_paid": loan.amount_paid,
                "foreclosure_discount": foreclosure_result["foreclosure_discount"],
                "final_settlement_amount": foreclosure_result["final_settlement_amount"],
                "status": loan.status
            }
        }, status=status.HTTP_200_OK)


# ✅ Admin: View All Loans
class AdminLoanListView(generics.ListAPIView):
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get_queryset(self):
        return Loan.objects.all()  


# ✅ Admin: Delete Loan
class LoanDeleteView(generics.DestroyAPIView):
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    lookup_field = "id"

    def get_queryset(self):
        return Loan.objects.all()  

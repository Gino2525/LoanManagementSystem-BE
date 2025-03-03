# LoanManagementSystem-BE

Loan Management System API 🚀
A Django REST Framework-based Loan Management System that allows users to apply for loans, track payments, and foreclose loans early.

This API includes JWT authentication, role-based access, and email verification via OTP.


📌 Features
✅ User Registration & Email Verification (OTP)
✅ JWT Authentication (Simple JWT)
✅ Loan CRUD Operations (Add, List, Retrieve, Foreclose)
✅ Automatic Loan Calculation (Compound Interest, EMI, Foreclosure Discounts)
✅ Admin Features (View & Manage Loans, Delete Loans)
✅ Deployed on Render (PostgreSQL & Gunicorn)


🔧 Tech Stack
Backend: Django, Django REST Framework (DRF)
Database: PostgreSQL (Render Cloud)
Authentication: JWT (Simple JWT)
Deployment: Render (Gunicorn)


🚀 Getting Started
1️⃣ Clone the Repository

git clone https://github.com/Gino2525/LoanManagementSystem-BE.git
cd LoanManagementSystem-BE
2️⃣ Set Up Virtual Environment

python -m venv env
source env/bin/activate  # macOS/Linux
env\Scripts\activate  # Windows
3️⃣ Install Dependencies

pip install -r requirements.txt
4️⃣ Configure Environment Variables
Create a .env file and add:
DATABASE_URL=<your-render-postgresql-url>
SECRET_KEY=<your-secret-key>
DEBUG=False
⚙️ Running the Project Locally
Apply Migrations & Create Superuser
python manage.py migrate
python manage.py createsuperuser
Run Development Server
python manage.py runserver
Your API will be available at: http://127.0.0.1:8000/

🛠️ API Endpoints & Usage
1️⃣ Authentication
🔹 Register User


POST /api/register/
Request:

json

{
  "username": "johndoe",
  "email": "john@example.com",
  "password": "securepassword"
}
Response:


{
  "message": "User registered successfully! OTP sent to email."
}
🔹 Verify Email OTP


POST /api/verify-email/
Request:


{
  "username_or_email": "johndoe",
  "otp": "123456"
}
Response:


{
  "message": "Account verified successfully!"
}
🔹 Login

POST /api/login/
Request:


{
  "username": "johndoe",
  "password": "securepassword"
}
Response:


{
  "access": "<jwt-token>",
  "refresh": "<refresh-token>",
  "message": "Login successful"
}
2️⃣ Loan Management
🔹 Create Loan


POST /api/loans/add/
Request:


{
    "amount": 10000,
    "tenure": 12,
    "interest_rate": 10
}
Response:

{
    "status": "success",
    "data": {
        "loan_id": "LOAN001",
        "amount": 10000,
        "tenure": 12,
        "interest_rate": "10% yearly",
        "monthly_installment": 879.16,
        "total_interest": 1549.92,
        "total_amount": 11549.92,
        "payment_schedule": [
            {
                "installment_no": 1,
                "due_date": "2025-03-24",
                "amount": 879.16
            }
        ]
    }
}
🔹 List Loans


GET /api/loans/
Response:


{
    "status": "success",
    "data": {
        "loans": [
            {
                "loan_id": "LOAN001",
                "amount": 10000,
                "tenure": 12,
                "monthly_installment": 879.16,
                "total_amount": 11549.92,
                "amount_paid": 1758.32,
                "amount_remaining": 9791.60,
                "next_due_date": "2025-04-24",
                "status": "ACTIVE",
                "created_at": "2025-02-24T10:30:00Z"
            }
        ]
    }
}
🔹 Retrieve Loan Details


GET /api/loans/{id}/
Response:


{
    "loan_id": "LOAN001",
    "amount": 10000,
    "tenure": 12,
    "monthly_installment": 879.16,
    "total_amount": 11549.92,
    "amount_paid": 0,
    "amount_remaining": 11549.92,
    "next_due_date": "2025-04-24",
    "status": "ACTIVE"
}
🔹 Foreclose Loan


PUT /api/loans/{id}/foreclose/
Request:


{
  "loan_id": "LOAN001"
}
Response:


{
    "status": "success",
    "message": "Loan foreclosed successfully.",
    "data": {
        "loan_id": "LOAN001",
        "amount_paid": 11000.00,
        "foreclosure_discount": 500.00,
        "final_settlement_amount": 10500.00,
        "status": "CLOSED"
    }
}
🔹 Admin Loan Management

View all user loans: GET /api/admin/loans/
Delete loan record: DELETE /api/admin/loans/{id}/




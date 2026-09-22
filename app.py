from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash
)

from flask_sqlalchemy import SQLAlchemy

from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from google import genai
from dotenv import load_dotenv

import os
import json
import re
from datetime import datetime


# ==================================================
# ENVIRONMENT VARIABLES
# ==================================================

load_dotenv()


# ==================================================
# FLASK APP
# ==================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY",
    "dev-secret-change-this"
)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///finance.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


# ==================================================
# DATABASE
# ==================================================

db = SQLAlchemy(app)


# ==================================================
# FLASK LOGIN
# ==================================================

login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = "login"

login_manager.login_message = (
    "Please login to access your finance dashboard."
)


# ==================================================
# GEMINI CONFIGURATION
# ==================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    client = genai.Client(
        api_key=GEMINI_API_KEY
    )
else:
    client = None

MODEL_NAME = "gemini-3.6-flash"


# ==================================================
# USER MODEL
# ==================================================

class User(UserMixin, db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    full_name = db.Column(
        db.String(120),
        nullable=False
    )

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    financial_records = db.relationship(
        "FinancialRecord",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )


# ==================================================
# FINANCIAL RECORD MODEL
# ==================================================

class FinancialRecord(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    income = db.Column(
        db.Float,
        nullable=False
    )

    expenses = db.Column(
        db.Text,
        nullable=False
    )

    goal = db.Column(
        db.Text,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# ==================================================
# FLASK LOGIN USER LOADER
# ==================================================

@login_manager.user_loader
def load_user(user_id):

    return db.session.get(
        User,
        int(user_id)
    )


# ==================================================
# CREATE DATABASE
# ==================================================

with app.app_context():
    db.create_all()


# ==================================================
# BUILD GEMINI PROMPT
# ==================================================

def build_prompt(income, expenses, goal):

    return f"""
You are an expert Personal Finance Advisor.

Analyze the following monthly financial information.

Monthly Income:
₹{income}

Expenses:
{json.dumps(expenses, indent=2)}

Financial Goal:
{goal}

Your tasks:

1. Create a personalized monthly budget.
2. Separate expenses into fixed and variable expenses.
3. Calculate the percentage of income spent on each expense category.
4. Analyze every expense category.
5. Mark each category as either:
   - "On Track"
   - "Overspending"
6. Provide a clear message explaining the spending status.
7. Provide a realistic monthly saving target.
8. Provide 3 to 5 actionable saving suggestions.
9. Each saving suggestion should include an estimated saving amount and target.
10. Consider the user's financial goal.

Return ONLY valid JSON.

Use EXACTLY this structure:

{{
    "budget_plan": {{
        "fixed_expenses": [],
        "variable_expenses": [],
        "saving_target": 0
    }},

    "spending_analysis": [],

    "saving_suggestions": []
}}

IMPORTANT RULES:

- Percentage must be calculated using monthly income.
- Amount must be numeric only.
- Percentage must be numeric only.
- Do NOT put ₹ inside numeric values.
- Status must be exactly "On Track" or "Overspending".
- spending_analysis must contain an entry for every expense category.
- saving_suggestions must contain 3 to 5 suggestions.
- Keep saving suggestions realistic.
- Consider the user's financial goal.
- Return ONLY JSON.
- Do NOT return markdown.
"""


# ==================================================
# EXTRACT JSON
# ==================================================

def extract_json(text):

    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(text)

    except json.JSONDecodeError:
        pass

    match = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        re.DOTALL | re.IGNORECASE
    )

    if match:

        try:
            return json.loads(
                match.group(1)
            )

        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1:

        try:
            return json.loads(
                text[start:end + 1]
            )

        except json.JSONDecodeError:
            pass

    return None


# ==================================================
# LOCAL FALLBACK ANALYSIS
# ==================================================

def create_fallback_analysis(
    income,
    expenses,
    goal
):

    total_expenses = sum(
        expenses.values()
    )

    actual_savings = max(
        income - total_expenses,
        0
    )

    saving_target = round(
        income * 0.20,
        2
    )

    fixed_categories = [
        "Housing",
        "Rent",
        "EMI",
        "Insurance"
    ]

    fixed_expenses = []
    variable_expenses = []

    spending_analysis = []

    for category, amount in expenses.items():

        percentage = round(
            (amount / income) * 100,
            2
        )

        category_lower = category.lower()

        if any(
            word.lower() in category_lower
            for word in fixed_categories
        ):
            fixed_expenses.append({
                "category": category,
                "amount": round(amount, 2),
                "percentage": percentage
            })

        else:
            variable_expenses.append({
                "category": category,
                "amount": round(amount, 2),
                "percentage": percentage
            })

        if percentage <= 15:

            status = "On Track"

            message = (
                "Spending is within a reasonable range."
            )

        else:

            status = "Overspending"

            message = (
                "Consider reducing this expense "
                "to improve your monthly savings."
            )

        spending_analysis.append({

            "category": category,

            "amount": round(
                amount,
                2
            ),

            "percentage": percentage,

            "status": status,

            "message": message
        })

    saving_suggestions = []

    suggestions = [
        (
            "Reduce unnecessary food expenses",
            500
        ),
        (
            "Reduce transportation costs",
            300
        ),
        (
            "Limit dining and entertainment expenses",
            500
        ),
        (
            "Transfer savings immediately after receiving income",
            1000
        )
    ]

    for suggestion, amount in suggestions:

        saving_suggestions.append({

            "suggestion": suggestion,

            "amount": amount,

            "target": (
                goal
                if goal
                else "Monthly savings"
            )
        })

    return {

        "budget_plan": {

            "fixed_expenses":
                fixed_expenses,

            "variable_expenses":
                variable_expenses,

            "saving_target":
                saving_target
        },

        "spending_analysis":
            spending_analysis,

        "saving_suggestions":
            saving_suggestions,

        "actual_savings":
            actual_savings,

        "analysis_source":
            "Local financial analysis"
    }


# ==================================================
# HOME
# ==================================================

@app.route("/")
@login_required
def home():

    return render_template(
        "index.html"
    )


# ==================================================
# REGISTER
# ==================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if not full_name:

            flash(
                "Full name is required.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if not email:

            flash(
                "Email is required.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if len(password) < 6:

            flash(
                "Password must be at least 6 characters.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            flash(
                "An account with this email already exists.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        password_hash = generate_password_hash(
            password
        )

        user = User(
            full_name=full_name,
            email=email,
            password_hash=password_hash
        )

        try:

            db.session.add(user)

            db.session.commit()

        except Exception as e:

            db.session.rollback()

            print(
                "REGISTER DATABASE ERROR:",
                repr(e)
            )

            flash(
                "Could not create account.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        flash(
            "Account created successfully. Please login.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# ==================================================
# LOGIN
# ==================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if current_user.is_authenticated:

        return redirect(
            url_for("home")
        )

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        user = User.query.filter_by(
            email=email
        ).first()

        if user and check_password_hash(
            user.password_hash,
            password
        ):

            login_user(user)

            return redirect(
                url_for("home")
            )

        flash(
            "Invalid email or password.",
            "error"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "login.html"
    )


# ==================================================
# LOGOUT
# ==================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect(
        url_for("login")
    )


# ==================================================
# HISTORY API
# ==================================================

@app.route("/history")
@login_required
def history():

    records = FinancialRecord.query.filter_by(
        user_id=current_user.id
    ).order_by(
        FinancialRecord.created_at.desc()
    ).all()

    history_data = []

    for record in records:

        try:

            expenses = json.loads(
                record.expenses
            )

        except (
            TypeError,
            json.JSONDecodeError
        ):

            expenses = {}

        total_expenses = sum(
            expenses.values()
        )

        history_data.append({

            "id": record.id,

            "income": record.income,

            "expenses": expenses,

            "total_expenses":
                total_expenses,

            "goal": record.goal,

            "created_at":
                record.created_at.strftime(
                    "%d %b %Y, %I:%M %p"
                )
        })

    return jsonify(
        history_data
    )


# ==================================================
# HISTORY PAGE
# ==================================================

@app.route("/history-page")
@login_required
def history_page():

    return render_template(
        "history.html"
    )


# ==================================================
# FINANCIAL ANALYSIS
# ==================================================

@app.route(
    "/analyse",
    methods=["POST"]
)
@login_required
def analyse():

    data = request.get_json()

    if not data:

        return jsonify({
            "error": "No data received"
        }), 400

    income = data.get("income")

    expenses = data.get("expenses")

    goal = data.get(
        "goal",
        ""
    )

    # --------------------------------------------------
    # VALIDATE INCOME
    # --------------------------------------------------

    try:

        income = float(
            income
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "error": "Invalid income"
        }), 400

    if income <= 0:

        return jsonify({
            "error":
                "Income must be greater than zero"
        }), 400

    # --------------------------------------------------
    # VALIDATE EXPENSES
    # --------------------------------------------------

    if (
        not expenses
        or not isinstance(expenses, dict)
    ):

        return jsonify({
            "error":
                "At least one expense is required"
        }), 400

    cleaned_expenses = {}

    for category, value in expenses.items():

        try:

            amount = float(
                value
            )

        except (
            TypeError,
            ValueError
        ):

            amount = 0

        if amount < 0:

            return jsonify({
                "error":
                    f"Invalid expense amount for {category}"
            }), 400

        cleaned_expenses[
            category
        ] = amount

    # --------------------------------------------------
    # TOTAL EXPENSE
    # --------------------------------------------------

    total_expenses = sum(
        cleaned_expenses.values()
    )

    if total_expenses <= 0:

        return jsonify({
            "error":
                "Please enter at least one expense greater than zero"
        }), 400

    # --------------------------------------------------
    # SAVE RECORD
    # --------------------------------------------------

    try:

        record = FinancialRecord(

            user_id=current_user.id,

            income=income,

            expenses=json.dumps(
                cleaned_expenses
            ),

            goal=goal

        )

        db.session.add(record)

        db.session.commit()

    except Exception as e:

        db.session.rollback()

        print(
            "DATABASE ERROR:",
            repr(e)
        )

        return jsonify({
            "error":
                "Could not save financial data"
        }), 500

    # --------------------------------------------------
    # LOCAL FALLBACK
    # --------------------------------------------------

    fallback_result = create_fallback_analysis(
        income,
        cleaned_expenses,
        goal
    )

    # --------------------------------------------------
    # GEMINI ANALYSIS
    # --------------------------------------------------

    if client is not None:

        prompt = build_prompt(
            income,
            cleaned_expenses,
            goal
        )

        try:

            response = client.models.generate_content(

                model=MODEL_NAME,

                contents=prompt

            )

            response_text = response.text

            result = extract_json(
                response_text
            )

            if result is not None:

                if (
                    "budget_plan" in result
                    and
                    "spending_analysis" in result
                    and
                    "saving_suggestions" in result
                ):

                    result["actual_savings"] = (
                        income - total_expenses
                    )

                    result["analysis_source"] = (
                        "Gemini AI"
                    )

                    return jsonify(
                        result
                    )

        except Exception as e:

            print(
                "GEMINI ERROR:",
                repr(e)
            )

            print(
                "Using local fallback analysis."
            )

    # --------------------------------------------------
    # RETURN FALLBACK
    # --------------------------------------------------

    return jsonify(
        fallback_result
    )


# ==================================================
# RUN APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )
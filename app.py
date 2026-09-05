from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from google import genai
import json
import re
from datetime import datetime


# ==================================================
# FLASK APP
# ==================================================

app = Flask(__name__)


# ==================================================
# DATABASE CONFIGURATION
# ==================================================

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///finance.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ==================================================
# GEMINI API CONFIGURATION
# ==================================================

client = genai.Client(
    api_key="enter api key "
)

MODEL_NAME = "gemini-3.6-flash"


# ==================================================
# DATABASE MODEL
# ==================================================

class FinancialRecord(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
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
# CREATE DATABASE
# ==================================================

with app.app_context():
    db.create_all()


# ==================================================
# BUILD FINANCIAL ANALYSIS PROMPT
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

Return ONLY valid JSON.

Use EXACTLY this structure:

{{
    "budget_plan": {{
        "fixed_expenses": [
            {{
                "category": "Housing",
                "amount": 0,
                "percentage": 0
            }}
        ],

        "variable_expenses": [
            {{
                "category": "Food",
                "amount": 0,
                "percentage": 0
            }}
        ],

        "saving_target": 0
    }},

    "spending_analysis": [
        {{
            "category": "Food",
            "amount": 0,
            "percentage": 0,
            "status": "On Track",
            "message": "Spending is within a reasonable range."
        }}
    ],

    "saving_suggestions": [
        {{
            "suggestion": "Reduce unnecessary food expenses",
            "amount": 500,
            "target": "Monthly savings"
        }}
    ]
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
- Do NOT return ```json.
- Do NOT add any explanation outside JSON.
"""


# ==================================================
# EXTRACT JSON FROM GEMINI RESPONSE
# ==================================================

def extract_json(text):

    if not text:
        return None

    text = text.strip()

    # ----------------------------------------------
    # 1. Direct JSON
    # ----------------------------------------------

    try:

        return json.loads(text)

    except json.JSONDecodeError:

        pass


    # ----------------------------------------------
    # 2. JSON inside markdown code block
    # ----------------------------------------------

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


    # ----------------------------------------------
    # 3. Find JSON object inside response
    # ----------------------------------------------

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1:

        json_text = text[
            start:end + 1
        ]

        try:

            return json.loads(
                json_text
            )

        except json.JSONDecodeError:

            pass


    return None


# ==================================================
# HOME ROUTE
# ==================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ==================================================
# HISTORY API ROUTE
# ==================================================

@app.route("/history")
def history():

    records = FinancialRecord.query.order_by(
        FinancialRecord.created_at.desc()
    ).all()

    history_data = []

    for record in records:

        expenses = json.loads(
            record.expenses
        )

        total_expenses = sum(
            expenses.values()
        )

        history_data.append({

            "id": record.id,

            "income": record.income,

            "expenses": expenses,

            "total_expenses": total_expenses,

            "goal": record.goal,

            "created_at": record.created_at.strftime(
                "%d %b %Y, %I:%M %p"
            )

        })

    return jsonify(
        history_data
    )


# ==================================================
# HISTORY PAGE ROUTE
# ==================================================

@app.route("/history-page")
def history_page():

    return render_template(
        "history.html"
    )


# ==================================================
# FINANCIAL ANALYSIS ROUTE
# ==================================================

@app.route(
    "/analyse",
    methods=["POST"]
)
def analyse():

    # ----------------------------------------------
    # Get JSON data from frontend
    # ----------------------------------------------

    data = request.get_json()


    if not data:

        return jsonify({

            "error":
                "No data received"

        }), 400


    # ----------------------------------------------
    # Get user information
    # ----------------------------------------------

    income = data.get(
        "income"
    )

    expenses = data.get(
        "expenses"
    )

    goal = data.get(
        "goal",
        ""
    )


    # ==================================================
    # VALIDATE INCOME
    # ==================================================

    try:

        income = float(
            income
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({

            "error":
                "Invalid income"

        }), 400


    if income <= 0:

        return jsonify({

            "error":
                "Income must be greater than zero"

        }), 400


    # ==================================================
    # VALIDATE EXPENSES
    # ==================================================

    if (
        not expenses
        or not isinstance(expenses, dict)
    ):

        return jsonify({

            "error":
                "At least one expense is required"

        }), 400


    # ----------------------------------------------
    # Convert expense values to numbers
    # ----------------------------------------------

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


    # ==================================================
    # CHECK TOTAL EXPENSE
    # ==================================================

    total_expenses = sum(
        cleaned_expenses.values()
    )


    if total_expenses <= 0:

        return jsonify({

            "error":
                "Please enter at least one expense greater than zero"

        }), 400


    # ==================================================
    # SAVE DATA TO SQLITE
    # ==================================================

    try:

        record = FinancialRecord(

            income=income,

            expenses=json.dumps(
                cleaned_expenses
            ),

            goal=goal

        )

        db.session.add(
            record
        )

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


    # ==================================================
    # BUILD GEMINI PROMPT
    # ==================================================

    prompt = build_prompt(

        income,

        cleaned_expenses,

        goal

    )


    # ==================================================
    # GEMINI API CALL
    # ==================================================

    try:

        response = client.models.generate_content(

            model=MODEL_NAME,

            contents=prompt

        )


        # ----------------------------------------------
        # Get Gemini response text
        # ----------------------------------------------

        response_text = response.text


        # ----------------------------------------------
        # Extract JSON
        # ----------------------------------------------

        result = extract_json(
            response_text
        )


        if result is None:

            return jsonify({

                "error":
                    "Could not parse Gemini response",

                "raw_response":
                    response_text

            }), 500


        # ==================================================
        # BASIC RESPONSE VALIDATION
        # ==================================================

        if "budget_plan" not in result:

            return jsonify({

                "error":
                    "Invalid response: budget_plan missing"

            }), 500


        if "spending_analysis" not in result:

            return jsonify({

                "error":
                    "Invalid response: spending_analysis missing"

            }), 500


        if "saving_suggestions" not in result:

            return jsonify({

                "error":
                    "Invalid response: saving_suggestions missing"

            }), 500


        # ==================================================
        # RETURN RESULT TO FRONTEND
        # ==================================================

        return jsonify(
            result
        )


    # ==================================================
    # GEMINI ERROR
    # ==================================================

    except Exception as e:

        print(
            "GEMINI ERROR:",
            repr(e)
        )

        return jsonify({

            "error":
                "Gemini API request failed",

            "details":
                str(e)

        }), 500


# ==================================================
# RUN FLASK APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )
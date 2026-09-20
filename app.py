from flask import Flask, render_template, redirect, url_for, request, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from config import Config
from models import db, User, FinancialAssessment, CalculationHistory, Expense
from datetime import datetime, date
from sqlalchemy import extract
import json
import logging
import secrets
import requests
from urllib.parse import urlencode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Support both common RAG file layouts.
build_rag_context = None
for _rag_import in (
    "rag.rag_service",
    "rag_service",
    "services.rag_service",
):
    try:
        _module = __import__(_rag_import, fromlist=["build_rag_context"])
        build_rag_context = getattr(_module, "build_rag_context", None)
        if build_rag_context is not None:
            break
    except (ImportError, ModuleNotFoundError):
        continue
RAG_ENABLED = build_rag_context is not None

app = Flask(__name__)
app.config.from_object(Config)

# -------------------- Helpers --------------------
def json_body():
    return request.get_json(silent=True) or {}


def number(data, key, default=0.0, minimum=None, maximum=None):
    value = data.get(key, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{key} must be at most {maximum}")
    return value


def latest_assessment():
    return (FinancialAssessment.query
            .filter_by(user_id=current_user.id)
            .order_by(FinancialAssessment.assessment_date.desc())
            .first())


def personal_context():
    """Human-readable string for report / legacy prompts."""
    assessment = latest_assessment()
    if not assessment:
        return f"User name: {current_user.name}\nNo financial assessment has been submitted."
    income = float(assessment.monthly_income or 0)
    expenses = float(assessment.monthly_expenses or 0)
    emi = sum(float(getattr(assessment, field, 0) or 0)
              for field in ('home_loan_emi', 'personal_loan_emi', 'education_loan_emi'))
    return "\n".join([
        f"User name: {current_user.name}",
        f"Age: {assessment.age}",
        f"Monthly income: ₹{income:,.0f}",
        f"Monthly expenses: ₹{expenses:,.0f}",
        f"Monthly surplus before other items: ₹{income - expenses:,.0f}",
        f"Emergency fund: ₹{float(assessment.emergency_fund or 0):,.0f}",
        f"Total reported EMI: ₹{emi:,.0f}",
        f"Credit score: {assessment.credit_score or 'Not provided'}",
        f"Stored health score: {assessment.financial_health_score or 'Not calculated'}",
    ])


def stored_profile_dict():
    """Structured facts from the latest assessment for mentor merge logic.

    Keys align with AIService extract_from_message / merge_facts.
    """
    assessment = latest_assessment()
    if not assessment:
        return {}
    profile = {}
    if assessment.monthly_income is not None:
        profile["monthly_income"] = float(assessment.monthly_income or 0)
    if assessment.monthly_expenses is not None:
        profile["monthly_expenses"] = float(assessment.monthly_expenses or 0)
    emi = sum(float(getattr(assessment, field, 0) or 0)
              for field in ('home_loan_emi', 'personal_loan_emi', 'education_loan_emi'))
    if emi > 0:
        profile["existing_emi"] = emi
    if assessment.emergency_fund is not None:
        profile["emergency_fund"] = float(assessment.emergency_fund or 0)
    if assessment.credit_score is not None:
        profile["credit_score"] = int(assessment.credit_score)

    # Include additional stored facts so the mentor can personalize answers.
    for field in (
        "age", "dependents", "gold_holdings", "home_loan",
        "education_loan", "personal_loan", "health_cover",
        "life_cover", "sip_amount", "ppf_amount",
        "stocks_amount", "fd_amount"
    ):
        value = getattr(assessment, field, None)
        if value is not None:
            profile[field] = float(value) if isinstance(value, (int, float)) else value

    for field in ("health_insurance", "life_insurance", "income_source",
                  "short_term_goals", "long_term_goals"):
        value = getattr(assessment, field, None)
        if value:
            profile[field] = value

    return profile


def calculate_health_score(assessment):
    """A transparent educational indicator, not a bank or regulatory score.

    Maximum: 100 points. The weights are product design choices and should not
    be represented as an official institutional methodology.
    """
    income = max(float(assessment.monthly_income or 0), 0)
    expenses = max(float(assessment.monthly_expenses or 0), 0)
    emergency = max(float(assessment.emergency_fund or 0), 0)
    emi = sum(max(float(getattr(assessment, field, 0) or 0), 0)
              for field in ('home_loan_emi', 'personal_loan_emi', 'education_loan_emi'))

    score = 0
    if income > 0 and expenses <= income:
        score += 25
    elif income > 0 and expenses <= income * 1.10:
        score += 12

    months = emergency / expenses if expenses > 0 else 0
    if months >= 6:
        score += 25
    elif months >= 3:
        score += 15
    elif months >= 1:
        score += 7

    dti = (emi / income) if income > 0 else 1
    if income > 0 and dti <= 0.20:
        score += 25
    elif income > 0 and dti <= 0.40:
        score += 15
    elif income > 0 and dti <= 0.50:
        score += 7

    credit = assessment.credit_score
    if credit is not None:
        if credit >= 750:
            score += 25
        elif credit >= 700:
            score += 18
        elif credit >= 650:
            score += 10

    return max(0, min(100, int(score)))


def rag_context(query):
    """Combine the logged-in user's data with general RAG knowledge."""
    user_data = personal_context()

    if not RAG_ENABLED or not build_rag_context:
        return (
            "PERSONAL USER CONTEXT:\\n"
            + user_data
            + "\\n\\nGENERAL FINANCIAL KNOWLEDGE:\\n"
            "No knowledge-base context is available."
        )

    try:
        knowledge_context = build_rag_context(
            user_id=current_user.id,
            query=query,
        )

        return (
            "PERSONAL USER CONTEXT:\\n"
            + user_data
            + "\\n\\nRETRIEVED GENERAL FINANCIAL KNOWLEDGE:\\n"
            + (knowledge_context or "No relevant knowledge was retrieved.")
        )

    except Exception:
        logger.exception("RAG retrieval failed")
        return (
            "PERSONAL USER CONTEXT:\\n"
            + user_data
            + "\\n\\nGENERAL FINANCIAL KNOWLEDGE:\\n"
            "Knowledge retrieval failed. Do not invent missing information."
        )


def ai_answer(instruction, context, max_tokens=700, temperature=0.2):
    if not groq_client:
        return None
    prompt = f"""You are a cautious financial-education assistant for users in India.
Use only the supplied context for factual financial claims. If the context does
not contain enough information, say that verification is required. Do not invent
sources, rates, tax rules, eligibility rules, product recommendations, or returns.
Separate general education from observations about the user. Never promise profit.
For rules/rates that can change, tell the user to verify the latest official source.
Do not present the application's health score as a bank, credit bureau, or
regulatory score.

CONTEXT:\n{context}\n\nTASK:\n{instruction}"""
    response = groq_client.chat.completions.create(
        model=(getattr(Config, 'GROQ_MODEL', None) if getattr(Config, 'GROQ_MODEL', None) not in (None, '', 'llama-3.3-70b-versatile') else 'openai/gpt-oss-120b'),
        messages=[
            {"role": "system", "content": "Give clear, concise, safety-conscious financial education."},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()

# -------------------- Extensions --------------------
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=Config.GOOGLE_CLIENT_ID,
    client_secret=Config.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

groq_client = None
if Config.GROQ_API_KEY and Config.GROQ_API_KEY.startswith('gsk_'):
    try:
        from groq import Groq
        groq_client = Groq(api_key=Config.GROQ_API_KEY)
        logger.info("Groq client configured")
    except Exception:
        logger.exception("Groq configuration failed")
else:
    logger.warning("No valid Groq API key configured")

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None

with app.app_context():
    db.create_all()

@app.template_filter('nl2br')
def nl2br_filter(text):
    return (text or '').replace('\n', '<br>')

@app.template_filter('format_currency')
def format_currency(value):
    return f"₹{float(value or 0):,.0f}"

# -------------------- Authentication --------------------
@app.route('/')
def index():
    return redirect(url_for('dashboard')) if current_user.is_authenticated else render_template('index.html')

@app.route('/login')
def login():
    nonce = secrets.token_urlsafe(24)
    session['oauth_nonce'] = nonce
    redirect_uri = url_for('authorize', _external=True)
    params = {
        'response_type': 'code', 'client_id': Config.GOOGLE_CLIENT_ID,
        'redirect_uri': redirect_uri, 'scope': 'openid email profile',
        'nonce': nonce, 'access_type': 'offline', 'prompt': 'consent'
    }
    return redirect('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params))

@app.route('/authorize')
def authorize():
    try:
        code = request.args.get('code')
        if not code:
            return "Authorization code missing", 400
        redirect_uri = url_for('authorize', _external=True)
        token_response = requests.post('https://oauth2.googleapis.com/token', data={
            'code': code, 'client_id': Config.GOOGLE_CLIENT_ID,
            'client_secret': Config.GOOGLE_CLIENT_SECRET,
            'redirect_uri': redirect_uri, 'grant_type': 'authorization_code'
        }, timeout=15)
        token_response.raise_for_status()
        token_data = token_response.json()
        access_token = token_data.get('access_token')
        if not access_token:
            return "Google token was not returned", 400
        user_response = requests.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {access_token}'}, timeout=15
        )
        user_response.raise_for_status()
        info = user_response.json()
        if not info.get('email') or not info.get('sub'):
            return "Google account information is incomplete", 400
        user = User.query.filter_by(email=info['email']).first()
        if not user:
            user = User(email=info['email'], name=info.get('name', ''),
                        picture=info.get('picture', ''), google_id=info['sub'])
            db.session.add(user)
        else:
            user.name = info.get('name', user.name)
            user.picture = info.get('picture', user.picture)
            user.google_id = info.get('sub', user.google_id)
        db.session.commit()
        login_user(user)
        return redirect(url_for('dashboard'))
    except Exception:
        logger.exception("Google authorization failed")
        return "Authentication failed. Please try again.", 400

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# -------------------- Pages --------------------
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user, assessment=latest_assessment())

@app.route('/assessment')
@login_required
def assessment_page():
    return render_template('assessment.html')

@app.route('/expenses')
@login_required
def expenses_page():
    return render_template('expenses.html', user=current_user)

@app.route('/reset-data', methods=['POST'])
@login_required
def reset_data():
    try:
        for collection in (current_user.assessments, current_user.calculations, current_user.expenses):
            for item in list(collection):
                db.session.delete(item)
        current_user.set_financial_profile({})
        db.session.commit()
        return jsonify(success=True)
    except Exception:
        db.session.rollback()
        logger.exception("Reset data failed")
        return jsonify(success=False, error='Could not reset data'), 500


def parse_credit_score(raw_value):
    """Return a validated integer credit score, or None when not supplied."""
    if raw_value in (None, "", "null"):
        return None
    try:
        score = int(float(raw_value))
    except (TypeError, ValueError):
        raise ValueError("credit_score must be a whole number")
    if not 300 <= score <= 900:
        raise ValueError("credit_score must be between 300 and 900")
    return score


def credit_score_category(score):
    """Educational score bands; not an official lender decision rule."""
    if score >= 750:
        return "Strong"
    if score >= 700:
        return "Good"
    if score >= 650:
        return "Fair"
    if score >= 550:
        return "Needs improvement"
    return "Low"


def credit_score_points(score):
    """Return exactly five clean, deterministic points for the supplied score."""
    category = credit_score_category(score)

    if score >= 750:
        outlook = "Your score is in a strong range."
        priority = "Continue protecting your payment history and avoid unnecessary new credit applications."
    elif score >= 700:
        outlook = "Your score is in a good range, with room to strengthen it."
        priority = "Focus on consistent repayments and keeping credit utilisation controlled."
    elif score >= 650:
        outlook = "Your score is in a fair range and may benefit from improvement."
        priority = "Prioritise on-time payments, lower outstanding balances, and review your credit report."
    elif score >= 550:
        outlook = "Your score indicates that improvement should be a priority."
        priority = "Build a consistent repayment record and reduce overdue or high outstanding balances."
    else:
        outlook = "Your score indicates that focused credit-repair habits may be helpful."
        priority = "Check your credit report for errors, address overdue accounts, and avoid taking on unnecessary debt."

    return [
        f"1. Score: {score}/900 — {outlook}",
        f"2. Category: {category}. This is an educational interpretation, not a lender approval decision.",
        "3. Payment history: Pay every loan and credit-card bill on time; missed payments can negatively affect credit history.",
        "4. Credit utilisation: Keep revolving credit balances manageable and avoid using your full available limit.",
        f"5. Next step: {priority}",
    ]

# -------------------- Assessment --------------------
@app.route('/api/submit-assessment', methods=['POST'])
@login_required
def submit_assessment():
    try:
        data = json_body()
        income = number(data, 'monthly_income', minimum=0)
        expenses = number(data, 'monthly_expenses', minimum=0)
        credit_score = parse_credit_score(data.get('credit_score'))
        assessment = FinancialAssessment(
            user_id=current_user.id, age=data.get('age'), income_source=data.get('income_source'),
            monthly_income=income, monthly_expenses=expenses,
            credit_score=credit_score, emergency_fund=number(data, 'emergency_fund', minimum=0),
            gold_holdings=number(data, 'gold_holdings', minimum=0), home_loan=number(data, 'home_loan', minimum=0),
            home_loan_emi=number(data, 'home_loan_emi', minimum=0), education_loan=number(data, 'education_loan', minimum=0),
            education_loan_emi=number(data, 'education_loan_emi', minimum=0), personal_loan=number(data, 'personal_loan', minimum=0),
            personal_loan_emi=number(data, 'personal_loan_emi', minimum=0), health_insurance=data.get('health_insurance'),
            health_cover=number(data, 'health_cover', minimum=0), life_insurance=data.get('life_insurance'),
            life_cover=number(data, 'life_cover', minimum=0), dependents=data.get('dependents', 0),
            sip_amount=number(data, 'sip_amount', minimum=0), ppf_amount=number(data, 'ppf_amount', minimum=0),
            stocks_amount=number(data, 'stocks_amount', minimum=0), fd_amount=number(data, 'fd_amount', minimum=0),
            short_term_goals=data.get('short_term_goals'), long_term_goals=data.get('long_term_goals')
        )
        assessment.financial_health_score = calculate_health_score(assessment)
        db.session.add(assessment)
        db.session.commit()
        report = generate_report(assessment)
        assessment.ai_report = report
        db.session.commit()
        return jsonify(success=True, assessment_id=assessment.id,
                       health_score=assessment.financial_health_score, report=report)
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        return jsonify(success=False, error=str(exc)), 400
    except Exception:
        db.session.rollback()
        logger.exception("Assessment submission failed")
        return jsonify(success=False, error='Could not save assessment'), 500

# -------------------- Calculators --------------------
@app.route('/api/calculate', methods=['POST'])
@login_required
def calculate():
    try:
        data = json_body()
        calc_type = data.get('type')
        if calc_type == 'investment':
            principal = number(data, 'principal', minimum=0)
            annual_rate = number(data, 'profit_rate', minimum=-100, maximum=1000) / 100
            years = number(data, 'time_years', minimum=0.01, maximum=100)
            monthly = number(data, 'monthly_contribution', minimum=0)
            months = round(years * 12)
            monthly_rate = annual_rate / 12
            fv = principal * ((1 + annual_rate) ** years)
            if monthly:
                fv += monthly * months if monthly_rate == 0 else monthly * (((1 + monthly_rate) ** months - 1) / monthly_rate)
            invested = principal + monthly * months
            result = {'future_value': round(fv, 2), 'total_invested': round(invested, 2), 'net_profit': round(fv - invested, 2)}
        elif calc_type == 'emi':
            loan = number(data, 'loan_amount', minimum=0)
            annual = number(data, 'interest_rate', minimum=0, maximum=100) / 100 / 12
            months = int(number(data, 'tenure_months', minimum=1, maximum=600))
            emi = loan / months if annual == 0 else loan * annual * (1 + annual) ** months / ((1 + annual) ** months - 1)
            result = {'emi': round(emi, 2), 'total_payment': round(emi * months, 2), 'total_interest': round(emi * months - loan, 2)}
        elif calc_type == 'goal':
            goal = number(data, 'goal_amount', minimum=0)
            years = number(data, 'time_years', minimum=0.01, maximum=100)
            current = number(data, 'current_savings', minimum=0)
            annual = number(data, 'expected_return', minimum=-99.9, maximum=1000) / 100
            months = round(years * 12)
            current_future = current * ((1 + annual) ** years)
            remaining = max(0, goal - current_future)
            monthly_rate = annual / 12
            monthly = remaining / months if monthly_rate == 0 else remaining * monthly_rate / (((1 + monthly_rate) ** months) - 1)
            result = {'monthly_savings': round(max(monthly, 0), 2), 'total_savings': round(max(monthly, 0) * months, 2),
                      'is_achievable': None, 'note': 'Achievability requires your verified monthly surplus; this calculator does not assume it.'}
        else:
            return jsonify(error='Invalid calculation type'), 400
        db.session.add(CalculationHistory(user_id=current_user.id, calc_type=calc_type,
                                          input_data=json.dumps(data), result_data=json.dumps(result)))
        db.session.commit()
        return jsonify(result)
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        db.session.rollback()
        logger.exception("Calculation failed")
        return jsonify(error='Calculation failed'), 500

# -------------------- Chat --------------------
@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    message = (json_body().get('message') or '').strip()
    if not message:
        return jsonify(response='Please enter a question.'), 400
    try:
        # Prefer mentor pipeline: extract numbers → merge (latest wins) → calculate → explain
        # Support both layouts: ai_service.py in project root or services/ai_service.py.
        service = None
        import_error = None
        for _ai_import in ("services.ai_service", "ai_service"):
            try:
                _module = __import__(_ai_import, fromlist=["get_ai_service"])
                service = _module.get_ai_service()
                if service is not None:
                    break
            except (ImportError, ModuleNotFoundError) as exc:
                import_error = exc
                continue
            except Exception as exc:
                logger.exception("AI service loading failed: %s", exc)
                import_error = exc
                break

        if service is not None:
            answer = service.chat_response(
                user_message=message,
                user_context=stored_profile_dict(),
                user_id=current_user.id,
            )
            if answer:
                return jsonify(response=answer, rag_enabled=RAG_ENABLED)

        # Safe fallback when the dedicated mentor service is unavailable.
        logger.error("AI service unavailable. Import/initialization detail: %s", import_error)
        return jsonify(
            response=(
                "The AI service is not available right now. Please check the Flask "
                "terminal for the exact configuration or import error, then restart "
                "the application."
            ),
            rag_enabled=RAG_ENABLED,
        ), 503
    except Exception:
        logger.exception("Chat failed")
        return jsonify(response='I could not complete that answer safely right now. Please try again.'), 503

# -------------------- Expenses --------------------
@app.route('/api/expenses', methods=['GET'])
@login_required
def get_expenses():
    try:
        query = Expense.query.filter_by(user_id=current_user.id)
        start_date, end_date = request.args.get('start_date'), request.args.get('end_date')
        year, month = request.args.get('year', type=int), request.args.get('month', type=int)
        if start_date and end_date:
            start, end = datetime.strptime(start_date, '%Y-%m-%d').date(), datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(Expense.date >= start, Expense.date <= end)
        elif year and month:
            start = date(year, month, 1)
            end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            query = query.filter(Expense.date >= start, Expense.date < end)
        elif request.args.get('filter') == 'year':
            yr = year or datetime.now().year
            query = query.filter(Expense.date >= date(yr, 1, 1), Expense.date < date(yr + 1, 1, 1))
        else:
            now = datetime.now()
            start = date(now.year, now.month, 1)
            end = date(now.year + 1, 1, 1) if now.month == 12 else date(now.year, now.month + 1, 1)
            query = query.filter(Expense.date >= start, Expense.date < end)
        expenses = query.order_by(Expense.date.desc()).all()
        categories = {}
        for item in expenses:
            categories[item.category] = categories.get(item.category, 0) + float(item.amount or 0)
        return jsonify(expenses=[e.to_dict() for e in expenses], total=sum(float(e.amount or 0) for e in expenses), category_breakdown=categories)
    except Exception:
        logger.exception("Expense retrieval failed")
        return jsonify(error='Could not retrieve expenses'), 500

@app.route('/api/expenses', methods=['POST'])
@login_required
def add_expense():
    try:
        data = json_body()
        amount = number(data, 'amount', minimum=0.01)
        category = (data.get('category') or '').strip()
        if not category or len(category) > 80:
            return jsonify(success=False, error='A valid category is required'), 400
        expense_date = datetime.strptime(data.get('date', ''), '%Y-%m-%d').date()
        item = Expense(user_id=current_user.id, amount=amount, category=category,
                       description=(data.get('description') or '')[:500], date=expense_date)
        db.session.add(item)
        db.session.commit()
        return jsonify(success=True, id=item.id)
    except (ValueError, TypeError):
        db.session.rollback()
        return jsonify(success=False, error='Invalid expense data'), 400
    except Exception:
        db.session.rollback()
        logger.exception("Expense creation failed")
        return jsonify(success=False, error='Could not save expense'), 500

@app.route('/api/expenses/<int:expense_id>', methods=['DELETE'])
@login_required
def delete_expense(expense_id):
    item = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    return jsonify(success=True)

@app.route('/api/expenses/summary')
@login_required
def get_expense_summary():
    now = datetime.now()
    month_start = date(now.year, now.month, 1)
    month_end = date(now.year + 1, 1, 1) if now.month == 12 else date(now.year, now.month + 1, 1)
    year_start, year_end = date(now.year, 1, 1), date(now.year + 1, 1, 1)
    monthly = Expense.query.filter_by(user_id=current_user.id).filter(Expense.date >= month_start, Expense.date < month_end).all()
    yearly = Expense.query.filter_by(user_id=current_user.id).filter(Expense.date >= year_start, Expense.date < year_end).all()
    categories = {}
    for item in yearly:
        categories[item.category] = categories.get(item.category, 0) + float(item.amount or 0)
    return jsonify(monthly_total=sum(float(x.amount or 0) for x in monthly), yearly_total=sum(float(x.amount or 0) for x in yearly), category_breakdown=categories)

@app.route('/api/credit-tips')
@login_required
def credit_tips():
    """Return a clean five-point, score-specific credit education result."""
    assessment = latest_assessment()

    if not assessment or assessment.credit_score is None:
        return jsonify(
            success=False,
            credit_score=None,
            points=[],
            error='Please submit an assessment with a valid credit score between 300 and 900.'
        ), 400

    score = int(assessment.credit_score)
    points = credit_score_points(score)

    query = (
        "India credit score education, payment history, credit utilisation, "
        "credit report errors, responsible credit use and official guidance"
    )
    context = rag_context(query)

    instruction = f"""Create a concise explanation for a user whose stored credit score is {score}/900.

The application has already generated these five rule-based points:
{chr(10).join(points)}

Return exactly five numbered points. Preserve the score, category, and meaning
of the supplied points. Use the retrieved context only to clarify the education.
Do not invent thresholds, guarantee approval, recommend products, or change the
number of points. Keep the language professional and easy to understand."""

    try:
        answer = ai_answer(instruction, context, max_tokens=650, temperature=0.2)
    except Exception:
        logger.exception("Credit guidance generation failed")
        answer = None

    return jsonify(
        success=True,
        credit_score=score,
        category=credit_score_category(score),
        points=points,
        explanation=answer or " ".join(points),
        rag_enabled=RAG_ENABLED
    )

# -------------------- Reports and fallback --------------------
def generate_report(assessment):
    context = rag_context('Create a personalized financial education report using emergency funds, budgeting, debt affordability, insurance and investing risk concepts.')
    instruction = f"""Prepare a practical report from this assessment:
Age: {assessment.age}
Monthly income: ₹{float(assessment.monthly_income or 0):,.0f}
Monthly expenses: ₹{float(assessment.monthly_expenses or 0):,.0f}
Emergency fund: ₹{float(assessment.emergency_fund or 0):,.0f}
Application health indicator: {assessment.financial_health_score}/100

Include: (1) observations, (2) strengths, (3) risks or missing information, and
(4) three realistic next actions. Do not use hype, guarantees, fixed SIP amounts,
fixed credit-score targets, or named financial products. Explain that the score
is an application indicator, not an official score."""
    try:
        answer = ai_answer(instruction, context, max_tokens=900, temperature=0.3)
        return answer or get_fallback_report(assessment)
    except Exception:
        logger.exception("Report generation failed")
        return get_fallback_report(assessment)


def get_fallback_report(assessment):
    income = float(assessment.monthly_income or 0)
    expenses = float(assessment.monthly_expenses or 0)
    surplus = income - expenses
    return (f"Financial report\n\nApplication health indicator: {assessment.financial_health_score}/100\n"
            f"Monthly income: ₹{income:,.0f}\nMonthly expenses: ₹{expenses:,.0f}\n"
            f"Monthly difference: ₹{surplus:,.0f}\n\n"
            "Next steps: track expenses, review emergency savings, and verify debt/insurance needs using current official guidance. "
            "This is educational information, not individualized regulated advice.")


def get_chat_response(message):
    return ('I can help explain budgeting, emergency savings, loans, credit, insurance, investing and goals. '
            'For current rates, tax rules or product details, verify the latest official source before acting.')

if __name__ == '__main__':
    print('\nPERSONAL FINANCE MENTOR')
    print(f'URL: {Config.BASE_URL}')
    print(f'AI mode: {"enabled" if groq_client else "fallback"}')
    print(f'RAG mode: {"enabled" if RAG_ENABLED else "disabled"}')
    app.run(host='0.0.0.0', port=5000, debug=False)
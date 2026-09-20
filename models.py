from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100))
    picture = db.Column(db.String(500))
    google_id = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Financial Profile Data (stored as JSON for quick access)
    financial_profile = db.Column(db.Text, default='{}')
    
    # Relationships - This links to all assessments for this user
    assessments = db.relationship('FinancialAssessment', backref='user', lazy=True, cascade='all, delete-orphan')
    calculations = db.relationship('CalculationHistory', backref='user', lazy=True, cascade='all, delete-orphan')
    expenses = db.relationship('Expense', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def get_financial_profile(self):
        """Get user's financial profile as dict"""
        return json.loads(self.financial_profile) if self.financial_profile else {}
    
    def set_financial_profile(self, data):
        """Set user's financial profile"""
        self.financial_profile = json.dumps(data)
    
    def get_latest_assessment(self):
        """Get the most recent assessment"""
        return FinancialAssessment.query.filter_by(user_id=self.id).order_by(FinancialAssessment.assessment_date.desc()).first()
    
    def get_all_assessments(self):
        """Get all assessments for this user"""
        return FinancialAssessment.query.filter_by(user_id=self.id).order_by(FinancialAssessment.assessment_date.desc()).all()
    
    def get_calculation_history(self, calc_type=None):
        """Get calculation history for this user"""
        query = CalculationHistory.query.filter_by(user_id=self.id)
        if calc_type:
            query = query.filter_by(calc_type=calc_type)
        return query.order_by(CalculationHistory.created_at.desc()).all()
    
    def get_expenses_by_date_range(self, start_date, end_date):
        """Get expenses within date range"""
        return Expense.query.filter_by(user_id=self.id).filter(
            Expense.date >= start_date, Expense.date <= end_date
        ).order_by(Expense.date.desc()).all()
    
    def get_monthly_expense_total(self, year, month):
        """Get total expenses for a specific month"""
        start_date = datetime(year, month, 1).date()
        if month == 12:
            end_date = datetime(year + 1, 1, 1).date()
        else:
            end_date = datetime(year, month + 1, 1).date()
        
        expenses = Expense.query.filter_by(user_id=self.id).filter(
            Expense.date >= start_date, Expense.date < end_date
        ).all()
        return sum(e.amount for e in expenses)
    
    def reset_data(self):
        """Reset all user data"""
        # Delete all assessments
        for assessment in self.assessments:
            db.session.delete(assessment)
        # Delete all calculations
        for calculation in self.calculations:
            db.session.delete(calculation)
        # Delete all expenses
        for expense in self.expenses:
            db.session.delete(expense)
        # Reset financial profile
        self.financial_profile = '{}'
        db.session.commit()
        return True

class FinancialAssessment(db.Model):
    __tablename__ = 'financial_assessments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    assessment_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Personal Details
    age = db.Column(db.Integer)
    income_source = db.Column(db.String(50))
    monthly_income = db.Column(db.Float, default=0)
    monthly_expenses = db.Column(db.Float, default=0)
    
    # Financial Health
    credit_score = db.Column(db.Integer)
    emergency_fund = db.Column(db.Float, default=0)
    gold_holdings = db.Column(db.Float, default=0)
    
    # Loans
    home_loan = db.Column(db.Float, default=0)
    home_loan_emi = db.Column(db.Float, default=0)
    education_loan = db.Column(db.Float, default=0)
    education_loan_emi = db.Column(db.Float, default=0)
    personal_loan = db.Column(db.Float, default=0)
    personal_loan_emi = db.Column(db.Float, default=0)
    
    # Insurance
    health_insurance = db.Column(db.String(50))
    health_cover = db.Column(db.Float, default=0)
    life_insurance = db.Column(db.String(50))
    life_cover = db.Column(db.Float, default=0)
    dependents = db.Column(db.Integer, default=0)
    
    # Investments
    sip_amount = db.Column(db.Float, default=0)
    ppf_amount = db.Column(db.Float, default=0)
    stocks_amount = db.Column(db.Float, default=0)
    fd_amount = db.Column(db.Float, default=0)
    
    # Goals
    short_term_goals = db.Column(db.Text)
    long_term_goals = db.Column(db.Text)
    
    # AI Report
    ai_report = db.Column(db.Text)
    financial_health_score = db.Column(db.Integer)
    
    def to_dict(self):
        """Convert assessment to dictionary"""
        return {
            'id': self.id,
            'date': self.assessment_date.strftime('%Y-%m-%d %H:%M:%S'),
            'age': self.age,
            'income_source': self.income_source,
            'monthly_income': self.monthly_income,
            'monthly_expenses': self.monthly_expenses,
            'credit_score': self.credit_score,
            'emergency_fund': self.emergency_fund,
            'gold_holdings': self.gold_holdings,
            'home_loan': self.home_loan,
            'personal_loan': self.personal_loan,
            'education_loan': self.education_loan,
            'health_insurance': self.health_insurance,
            'life_insurance': self.life_insurance,
            'dependents': self.dependents,
            'sip_amount': self.sip_amount,
            'ppf_amount': self.ppf_amount,
            'stocks_amount': self.stocks_amount,
            'fd_amount': self.fd_amount,
            'financial_health_score': self.financial_health_score,
            'ai_report': self.ai_report
        }

class CalculationHistory(db.Model):
    __tablename__ = 'calculation_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    calc_type = db.Column(db.String(50))  # 'investment', 'emi', 'goal'
    input_data = db.Column(db.Text)  # JSON string of input parameters
    result_data = db.Column(db.Text)  # JSON string of results
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert history entry to dictionary"""
        return {
            'id': self.id,
            'type': self.calc_type,
            'input': json.loads(self.input_data) if self.input_data else {},
            'result': json.loads(self.result_data) if self.result_data else {},
            'date': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

# NEW: Expense Model for tracking daily expenses
class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert expense to dictionary"""
        return {
            'id': self.id,
            'amount': self.amount,
            'category': self.category,
            'description': self.description,
            'date': self.date.strftime('%Y-%m-%d')
        }
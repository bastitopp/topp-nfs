from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db

# Assoziationstabellen
card_tags = db.Table('card_tags', 
    db.Column('card_id', db.Integer, db.ForeignKey('card.id')), 
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'))
)

user_badges = db.Table('user_badges', 
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')), 
    db.Column('badge_id', db.Integer, db.ForeignKey('badge.id')), 
    db.Column('earned_at', db.DateTime, default=datetime.utcnow)
)

class UserGroup(db.Model):
    __tablename__ = 'user_group'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    users = db.relationship('User', backref='group', lazy=True)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class CardReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved = db.Column(db.Boolean, default=False)
    card = db.relationship('Card', backref='reports')
    user = db.relationship('User', backref='reports')

class Badge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    icon = db.Column(db.String(50), default='bi-trophy')

class DashboardMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean, default=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)
    real_name = db.Column(db.String(100), nullable=True)
    age = db.Column(db.Integer, nullable=True)
    bio = db.Column(db.Text, nullable=True)
    profile_image = db.Column(db.String(200), nullable=True)
    total_learning_time = db.Column(db.Integer, default=0)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    streak = db.Column(db.Integer, default=0)
    xp = db.Column(db.Integer, default=0)
    
    # --- NEU: Zähler für die historische Erfolgsquote ---
    total_reviews = db.Column(db.Integer, default=0)
    correct_reviews = db.Column(db.Integer, default=0)
    
    badges = db.relationship('Badge', secondary=user_badges, lazy='subquery', backref=db.backref('users', lazy=True))
    group_id = db.Column(db.Integer, db.ForeignKey('user_group.id'), nullable=True)
    
    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    
    def get_level(self): return int(self.xp / 500) + 1
    def get_level_progress(self):
        current_level_xp = (self.get_level() - 1) * 500
        xp_in_level = self.xp - current_level_xp
        return int((xp_in_level / 500) * 100)
        
    def is_online(self):
        from datetime import datetime, timedelta
        if not self.last_active:
            return False
        return datetime.utcnow() - self.last_active < timedelta(minutes=10)

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20))     
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    explanation = db.Column(db.Text, nullable=True)
    answer_lat = db.Column(db.Text, nullable=True) 
    options = db.Column(db.Text, nullable=True) 
    image_url = db.Column(db.String(200), nullable=True)
    audio_url = db.Column(db.String(200), nullable=True)
    tags = db.relationship('Tag', secondary=card_tags, lazy='subquery', backref=db.backref('cards', lazy=True))

class UserProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False)
    
    state = db.Column(db.Integer, default=0) 
    stability = db.Column(db.Float, default=0.0)
    difficulty = db.Column(db.Float, default=0.0)
    elapsed_days = db.Column(db.Integer, default=0)
    scheduled_days = db.Column(db.Integer, default=0)
    reps = db.Column(db.Integer, default=0)
    lapses = db.Column(db.Integer, default=0)
    last_review = db.Column(db.DateTime, nullable=True)
    
    next_review = db.Column(db.DateTime, default=datetime.utcnow)
    box = db.Column(db.Integer, default=0) 
    last_correct = db.Column(db.Boolean, default=False)
    
    easiness_factor = db.Column(db.Float, default=2.5)
    interval = db.Column(db.Integer, default=0)

    card = db.relationship('Card', backref='progress_records')
    user = db.relationship('User', backref='progress_records')

class ExamAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Integer, default=0)
    total_questions = db.Column(db.Integer, default=0)
    passed = db.Column(db.Boolean, default=False)
    details = db.relationship('ExamDetail', backref='attempt', cascade="all, delete-orphan")

class ExamDetail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('exam_attempt.id'), nullable=False)
    question_text = db.Column(db.Text)
    question_type = db.Column(db.String(20))
    is_correct = db.Column(db.Boolean, default=False)
    user_solution = db.Column(db.Text, nullable=True)
    correct_solution = db.Column(db.Text, nullable=True)

class Scenario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    dispatch_text = db.Column(db.String(255), nullable=False)
    first_node_id = db.Column(db.Integer)
    nodes = db.relationship('ScenarioNode', backref='scenario', lazy=True, cascade="all, delete-orphan")

class ScenarioNode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenario.id'), nullable=False)
    situation_text = db.Column(db.Text, nullable=False)
    vitals = db.Column(db.JSON, nullable=True) 
    is_endpoint = db.Column(db.Boolean, default=False)
    is_success = db.Column(db.Boolean, default=False)
    status_badge = db.Column(db.String(100), default="Unklare Diagnose")
    choices = db.relationship('ScenarioChoice', backref='node', lazy=True, cascade="all, delete-orphan", foreign_keys='ScenarioChoice.node_id')

class ScenarioChoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey('scenario_node.id'), nullable=False)
    action_text = db.Column(db.String(255), nullable=False)
    outcomes = db.relationship('ChoiceOutcome', backref='choice', lazy=True, cascade="all, delete-orphan")

class ChoiceOutcome(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    choice_id = db.Column(db.Integer, db.ForeignKey('scenario_choice.id'), nullable=False)
    next_node_id = db.Column(db.Integer, db.ForeignKey('scenario_node.id'), nullable=True)
    probability_weight = db.Column(db.Integer, default=100) 
    required_flags = db.Column(db.JSON, nullable=True) 
    set_flags = db.Column(db.JSON, nullable=True) 
    is_fatal_error = db.Column(db.Boolean, default=False)
    error_feedback = db.Column(db.Text, nullable=True)

class UserScenarioSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenario.id'), nullable=False)
    current_node_id = db.Column(db.Integer, db.ForeignKey('scenario_node.id'), nullable=True)
    state_flags = db.Column(db.JSON, default={}) 
    history_nodes = db.Column(db.JSON, default=[]) 
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed = db.Column(db.Boolean, default=False)
    success = db.Column(db.Boolean, default=False)

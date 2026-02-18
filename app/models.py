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
    
    badges = db.relationship('Badge', secondary=user_badges, lazy='subquery', backref=db.backref('users', lazy=True))
    group_id = db.Column(db.Integer, db.ForeignKey('user_group.id'), nullable=True)
    
    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    
    def get_level(self): return int(self.xp / 500) + 1
    def get_level_progress(self):
        current_level_xp = (self.get_level() - 1) * 500
        xp_in_level = self.xp - current_level_xp
        return int((xp_in_level / 500) * 100)

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
    box = db.Column(db.Integer, default=0)
    last_correct = db.Column(db.Boolean, default=False)
    next_review = db.Column(db.DateTime, default=datetime.utcnow)
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

# ==========================================
# --- NEU: BPR / SOP Szenario-Trainer ---
# ==========================================

class Scenario(db.Model):
    """Das übergeordnete Fallbeispiel (Der Einsatz)"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False) # z.B. "Einsatz 042: Unklarer Thoraxschmerz"
    dispatch_text = db.Column(db.String(255), nullable=False) # Einsatzstichwort: "Rett 1 - unklar intern"
    
    first_node_id = db.Column(db.Integer) # Welcher Schritt ist der Startpunkt?
    
    # Verknüpfung zu allen Knotenpunkten dieses Szenarios
    nodes = db.relationship('ScenarioNode', backref='scenario', lazy=True, cascade="all, delete-orphan")

class ScenarioNode(db.Model):
    """Ein einzelner Schritt / Zustand im Einsatz"""
    id = db.Column(db.Integer, primary_key=True)
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenario.id'), nullable=False)
    
    situation_text = db.Column(db.Text, nullable=False) # XABCDE Werte, Situation, etc.
    
    # Gamification & Status
    is_endpoint = db.Column(db.Boolean, default=False) # Ist das Szenario hier vorbei?
    is_success = db.Column(db.Boolean, default=False) # Hat der Nutzer bestanden?
    status_badge = db.Column(db.String(100), default="Unklare Diagnose") # Badge oben rechts
    
    # Verknüpfung zu den Antwortmöglichkeiten
    choices = db.relationship('ScenarioChoice', backref='node', lazy=True, cascade="all, delete-orphan", foreign_keys='ScenarioChoice.node_id')

class ScenarioChoice(db.Model):
    """Die Buttons / Entscheidungen, die der Nutzer in einem Schritt klicken kann"""
    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey('scenario_node.id'), nullable=False)
    
    action_text = db.Column(db.String(255), nullable=False) # Aufschrift Button, z.B. "Zugang legen"
    
    # Verknüpfung zu den möglichen Ausgängen (Outcomes) nach dem Klick
    outcomes = db.relationship('ChoiceOutcome', backref='choice', lazy=True, cascade="all, delete-orphan")

class ChoiceOutcome(db.Model):
    """Das Ergebnis eines Klicks (mit BPR-Bedingungen und Wahrscheinlichkeit)"""
    id = db.Column(db.Integer, primary_key=True)
    choice_id = db.Column(db.Integer, db.ForeignKey('scenario_choice.id'), nullable=False)
    
    # Zu welchem Schritt (Node) führt dieser Ausgang?
    next_node_id = db.Column(db.Integer, db.ForeignKey('scenario_node.id'), nullable=True)
    
    # Wahrscheinlichkeit in Prozent, dass dieses Outcome eintritt (Standard: 100%)
    probability_weight = db.Column(db.Integer, default=100) 
    
    # --- DAS BPR INVENTAR (State Machine) ---
    # JSON Dictionary: Welche Flags MÜSSEN aktiv sein? (z.B. {"zugang_liegt": true})
    required_flags = db.Column(db.JSON, nullable=True) 
    
    # JSON Dictionary: Welche Flags WERDEN HINZUGEFÜGT/GEÄNDERT? (z.B. {"zugang_liegt": true})
    set_flags = db.Column(db.JSON, nullable=True) 
    
    # Was passiert, wenn man hier reinfällt (z.B. falsche Dosis oder Bedingung verfehlt)?
    is_fatal_error = db.Column(db.Boolean, default=False)
    error_feedback = db.Column(db.Text, nullable=True)

class UserScenarioSession(db.Model):
    """Speichert den aktuellen Durchlauf eines Nutzers (Sein 'Savegame')"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenario.id'), nullable=False)
    
    # Wo im Baum befindet sich der Nutzer aktuell?
    current_node_id = db.Column(db.Integer, db.ForeignKey('scenario_node.id'), nullable=True)
    
    # Das dynamische "Inventar" (JSON), z.B. gesetzte Zugänge, Loops bei Reanimation
    state_flags = db.Column(db.JSON, default={}) 
    
    # Historie: IDs der bisher besuchten Nodes als Liste (hilft beim Aufbau der Baum-UI)
    history_nodes = db.Column(db.JSON, default=[]) 
    
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed = db.Column(db.Boolean, default=False)
    success = db.Column(db.Boolean, default=False)

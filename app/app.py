import os
import datetime
import json
import csv
import io
import random
import time
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.sql.expression import func, or_
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'geheimnis_fuer_topp_nfs_dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp3', 'wav', 'csv'}

app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.example.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'user@example.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'password')
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

db = SQLAlchemy(app)
mail = Mail(app)
limiter = Limiter(key_func=get_remote_address, app=app, storage_uri="memory://")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELS ---
card_tags = db.Table('card_tags', db.Column('card_id', db.Integer, db.ForeignKey('card.id')), db.Column('tag_id', db.Integer, db.ForeignKey('tag.id')))
user_badges = db.Table('user_badges', db.Column('user_id', db.Integer, db.ForeignKey('user.id')), db.Column('badge_id', db.Integer, db.ForeignKey('badge.id')), db.Column('earned_at', db.DateTime, default=datetime.datetime.utcnow))

class Group(db.Model):
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
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    active = db.Column(db.Boolean, default=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    real_name = db.Column(db.String(100), nullable=True)
    age = db.Column(db.Integer, nullable=True)
    bio = db.Column(db.Text, nullable=True)
    profile_image = db.Column(db.String(200), nullable=True)
    total_learning_time = db.Column(db.Integer, default=0)
    last_active = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    streak = db.Column(db.Integer, default=0)
    badges = db.relationship('Badge', secondary=user_badges, lazy='subquery', backref=db.backref('users', lazy=True))
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20))     
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False) 
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
    next_review = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    easiness_factor = db.Column(db.Float, default=2.5)
    interval = db.Column(db.Integer, default=0)
    card = db.relationship('Card', backref='progress_records')
    user = db.relationship('User', backref='progress_records')

class ExamAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
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

@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Zugriff verweigert!", "danger"); return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(fn): return '.' in fn and fn.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.template_filter('format_duration')
def format_duration(s):
    if not s: return "0 Min"
    m, s = divmod(s, 60); h, m = divmod(m, 60)
    return f"{h} Std {m} Min" if h>0 else f"{m} Min {s} Sek"

@app.context_processor
def inject_globals(): return {'now': datetime.datetime.utcnow()}

def get_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'])

def check_gamification(user):
    today = datetime.datetime.utcnow().date()
    last = user.last_active.date() if user.last_active else None
    if last != today:
        if last == today - datetime.timedelta(days=1): user.streak += 1
        else: user.streak = 1
        user.last_active = datetime.datetime.utcnow(); db.session.commit()

def award_badges(user):
    checks = [("Erster Schritt", "Erste Frage", lambda u: UserProgress.query.filter_by(user_id=u.id).count() >= 1),
              ("Dauerbrenner", "5er Streak", lambda u: u.streak >= 5)]
    new = []
    for n, d, f in checks:
        if f(user):
            b = Badge.query.filter_by(name=n).first()
            if not b: b = Badge(name=n, description=d); db.session.add(b); db.session.commit()
            if b not in user.badges: user.badges.append(b); new.append(n)
    if new: db.session.commit(); flash(f"🎉 Neu: {', '.join(new)}", "warning")

def get_next_card(user, paths, force=False):
    now = datetime.datetime.utcnow()
    conditions = [Card.category.like(f"{p}%") for p in paths]
    filter_cond = or_(*conditions)
    query = UserProgress.query.join(Card).filter(UserProgress.user_id==user.id, filter_cond)
    # ZUFALLSMISCHUNG (Wichtig: func.random() statt Datum)
    if not force: due = query.filter(UserProgress.next_review <= now).order_by(func.random()).first()
    else: due = query.order_by(func.random()).first()
    if due: return due.card, due
    sub = db.session.query(UserProgress.card_id).filter(UserProgress.user_id==user.id)
    new = Card.query.filter(filter_cond, ~Card.id.in_(sub)).order_by(func.random()).first()
    return new, None

def update_progress(user, card, quality):
    if isinstance(quality, bool): quality = 4 if quality else 0
    p = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first()
    if not p: p = UserProgress(user_id=user.id, card_id=card.id, box=0, easiness_factor=2.5, interval=0); db.session.add(p)
    p.last_correct = (quality >= 3)
    if quality >= 3:
        if p.box == 0: p.interval = 1
        elif p.box == 1: p.interval = 6
        else: p.interval = int(p.interval * p.easiness_factor)
        p.box += 1
    else:
        p.box = 0; p.interval = 0
    p.easiness_factor = p.easiness_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if p.easiness_factor < 1.3: p.easiness_factor = 1.3
    if p.interval == 0: delta = datetime.timedelta(minutes=3)
    else: delta = datetime.timedelta(days=p.interval)
    p.next_review = datetime.datetime.utcnow() + delta; db.session.commit()

def build_category_tree(cards, user):
    tree = {}
    for c in cards:
        parts = c.category.split('/')
        current = tree
        learned = False
        if user.is_authenticated:
            p = UserProgress.query.filter_by(user_id=user.id, card_id=c.id).first()
            if p and p.box > 0: learned = True
        for i, part in enumerate(parts):
            if part not in current: current[part] = {'_subs': {}, '_stats': {'total':0,'learned':0}, '_path': "/".join(parts[:i+1])}
            current[part]['_stats']['total'] += 1
            if learned: current[part]['_stats']['learned'] += 1
            current = current[part]['_subs']
    return tree

def get_mc_options(card):
    try: opts = json.loads(card.options) if card.options else []
    except: opts = []
    if not isinstance(opts, list): opts = []
    if card.answer and card.answer not in opts: opts.append(card.answer)
    random.shuffle(opts)
    return opts

# FIX: context_path Parameter hinzugefügt, um "Tunnelblick" zu vermeiden
def render_learn_card(card, context_path):
    p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first(); box = p.box if p else 0
    try: opts = json.loads(card.options) if card.options else []
    except: opts = []
    
    if card.type == 'mc': opts = get_mc_options(card)
    elif card.type=='ordering': random.shuffle(opts)
    elif card.type=='assignment':
        pool=[]; [([pool.append({'val':i, 'group':g.get('name')}) for i in g.get('items',[])] if isinstance(opts,list) else None) for g in (opts if isinstance(opts,list) else [])]; random.shuffle(pool)
        return render_template('quiz.html', card=card, options=opts, pool_items=pool, finished=False, box=box, current_category=context_path)
    
    return render_template('quiz.html', card=card, options=opts, finished=False, box=box, current_category=context_path)

# --- ROUTES ---

@app.route('/')
def index():
    if current_user.is_authenticated: check_gamification(current_user)
    global_stats = {'total': 0, 'learned': 0}
    if current_user.is_authenticated:
        global_stats['total'] = Card.query.count()
        global_stats['learned'] = UserProgress.query.join(Card).filter(UserProgress.user_id==current_user.id, UserProgress.box>0).count()
    all_cards = Card.query.all()
    u = current_user if current_user.is_authenticated else type('obj', (object,), {'id':0, 'is_authenticated':False})
    tree = build_category_tree(all_cards, u)
    msgs = DashboardMessage.query.filter_by(active=True).order_by(DashboardMessage.created_at.desc()).all()
    return render_template('index.html', tree=tree, messages=msgs, global_stats=global_stats)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method=='POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and u.check_password(request.form['password']): login_user(u); return redirect(url_for('index'))
        flash('Fehler: Benutzer oder Passwort falsch', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('index'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            s = get_serializer(); token = s.dumps(user.email, salt='password-reset-salt')
            link = url_for('reset_password_with_token', token=token, _external=True)
            try:
                msg = Message('Passwort zurücksetzen', recipients=[user.email])
                msg.body = f'Link: {link}'
                mail.send(msg)
            except Exception as e: print("Mail Error:", e)
        flash('Link gesendet.', 'info'); return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    s = get_serializer()
    try: email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except: flash('Link ungültig.', 'danger'); return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        if request.form.get('password') != request.form.get('confirm'): flash('Ungleiche Passwörter', 'warning')
        else:
            u = User.query.filter_by(email=email).first()
            if u: u.set_password(request.form.get('password')); db.session.commit(); flash('OK!', 'success'); return redirect(url_for('login'))
    return render_template('reset_password.html')

@app.route('/learn/custom', methods=['POST'])
@login_required
def learn_custom():
    cats = request.form.getlist('categories')
    if not cats: flash("Kategorie wählen", "warning"); return redirect(url_for('index'))
    return redirect(url_for('learn', category_path="|".join(cats)))

@app.route('/learn/<path:category_path>')
@login_required
def learn(category_path):
    paths = category_path.split('|'); f = request.args.get('force') == 'true'
    card, p = get_next_card(current_user, paths, force=f)
    if not card: 
        conds = [Card.category.like(f"{p}%") for p in paths]
        w = UserProgress.query.join(Card).filter(UserProgress.user_id==current_user.id, or_(*conds), UserProgress.next_review>datetime.datetime.utcnow()).count()
        return render_template('quiz.html', finished=True, category=category_path, waiting_count=w)
    
    # WICHTIG: Hier übergeben wir den ursprünglichen Pfad (category_path) statt card.category
    return render_learn_card(card, category_path)

@app.route('/submit/<int:card_id>', methods=['POST'])
@login_required
def submit(card_id):
    try:
        if request.form.get('start_time'): 
            try:
                d = datetime.datetime.utcnow().timestamp()-float(request.form.get('start_time'))
                if 0<d<600: current_user.total_learning_time+=int(d); db.session.commit()
            except: pass
        card = Card.query.get_or_404(card_id)
        
        # WICHTIG: Ursprünglichen Pfad (Context) aus Formular holen
        origin = request.form.get('origin_path')
        # Fallback auf Karten-Kategorie, falls kein Origin da ist (sollte nicht passieren)
        if not origin: origin = card.category

        card_opts = []
        if card.options:
            try: card_opts = json.loads(card.options)
            except: card_opts = []

        if card.type=='mc':
            u=request.form.get('mc_answer'); corr=(u==card.answer)
            update_progress(current_user, card, corr); award_badges(current_user)
            opts_for_feedback = get_mc_options(card)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, options=opts_for_feedback, finished=False, feedback=True, user_answer=u, is_correct=corr, box=p.box if p else 0, current_category=origin)
        
        elif card.type=='anatomy':
            ud=request.form.get('input_de','').lower(); ul=request.form.get('input_lat','').lower()
            sd=card.answer.lower() if card.answer else ""; sl=card.answer_lat.lower() if card.answer_lat else ""
            de_ok = (ud == sd) if sd else True; lat_ok = (ul == sl) if sl else True
            corr = (de_ok and lat_ok)
            update_progress(current_user, card, corr); award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_anatomy=True, result_de=(ud==sd), result_lat=(ul==sl if sl else True), box=p.box if p else 0, current_category=origin)
        
        elif card.type=='anatomy_multi':
            sols=card_opts; sub=True; res=[]
            for i in sols:
                rid=str(i.get('id')); ud=request.form.get(f"de_{rid}",'').lower(); ul=request.form.get(f"lat_{rid}",'').lower()
                correct_de = i.get('de','').lower() if i.get('de') else ""; correct_lat = i.get('lat','').lower() if i.get('lat') else ""
                cde = (ud == correct_de) if correct_de else True; clat = (ul == correct_lat) if correct_lat else True
                if (correct_de and not cde) or (correct_lat and not clat): sub=False
                res.append({'label':rid, 'user_de':ud, 'user_lat':ul, 'correct_de':i.get('de'), 'correct_lat':i.get('lat'), 'is_de_ok':cde, 'is_lat_ok':clat})
            update_progress(current_user, card, sub); award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_multi=True, multi_results=res, all_correct=sub, box=p.box if p else 0, current_category=origin)
        
        elif card.type=='ordering':
            try: uo = json.loads(request.form.get('order_json', '[]'))
            except: uo = []
            corr = (uo==card_opts)
            update_progress(current_user, card, corr); award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_ordering=True, user_order=uo, correct_order=card_opts, is_correct=corr, box=p.box if p else 0, current_category=origin)
        
        elif card.type=='assignment':
            try: ud = json.loads(request.form.get('assignment_json', '{}'))
            except: ud = {}
            all_c=True; res=[]
            for g in card_opts:
                gn=g.get('name'); ci=g.get('items',[]); ui=ud.get(gn,[]); gr={'name':gn,'group_items':[],'missing':[]}
                for i, u in enumerate(ui):
                    st={'text':u}; 
                    if u not in ci: all_c=False; st['correct']=False; st['reason']='wrong_group'
                    elif i<len(ci) and ci[i]==u: st['correct']=True
                    else: all_c=False; st['correct']=False; st['reason']='wrong_order'
                    gr['group_items'].append(st)
                for c in ci: 
                    if c not in ui: all_c=False; gr['missing'].append(c)
                res.append(gr)
            update_progress(current_user, card, all_c); award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_assignment=True, all_correct=all_c, assignment_results=res, box=p.box if p else 0, current_category=origin)
        
        else: # Flashcard (Redirect logic)
            try: quality = int(request.form.get('result', 0))
            except: quality = 0
            update_progress(current_user, card, quality); award_badges(current_user)
            # FIX: Hier leiten wir zurück zum Ursprung (origin), nicht zur Karten-Kategorie
            return redirect(url_for('learn', category_path=origin))
            
    except Exception as e: print(f"ERROR: {e}"); return "Fehler beim Auswerten", 500

@app.route('/report/<int:card_id>', methods=['POST'])
@login_required
def report_card(card_id):
    reason = request.form.get('reason')
    if reason:
        db.session.add(CardReport(card_id=card_id, user_id=current_user.id, reason=reason))
        db.session.commit()
        flash('Gemeldet.', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/learn/errors')
@login_required
def learn_errors():
    sub_query = UserProgress.query.filter(UserProgress.user_id == current_user.id, or_(UserProgress.box == 0, UserProgress.last_correct == False)).with_entities(UserProgress.card_id)
    card = Card.query.filter(Card.id.in_(sub_query)).order_by(func.random()).first()
    if not card: flash("Keine Fehler gefunden!", "success"); return redirect(url_for('index'))
    # Dummy Context für Errors
    return render_learn_card(card, "errors")

@app.route('/admin/users')
@admin_required
def admin_users(): return render_template('admin_users.html', users=User.query.all())

@app.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    if User.query.filter_by(username=request.form['username']).first(): flash('Existiert','danger')
    else: u=User(username=request.form['username'], is_admin='is_admin' in request.form); u.set_password(request.form['password']); db.session.add(u); db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/users/edit/<int:uid>', methods=['POST'])
@admin_required
def edit_user(uid):
    u = User.query.get_or_404(uid)
    u.username = request.form.get('username')
    u.real_name = request.form.get('real_name')
    u.email = request.form.get('email')
    u.is_admin = 'is_admin' in request.form
    new_pw = request.form.get('new_password')
    if new_pw and new_pw.strip(): u.set_password(new_pw)
    db.session.commit(); flash('Gespeichert.', 'success'); return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<int:uid>', methods=['POST'])
@admin_required
def delete_user(uid):
    u=User.query.get(uid); 
    if u and u.username!='admin': db.session.delete(u); db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if 'profile_image' in request.files and request.files['profile_image']:
            f = request.files['profile_image']; fn = secure_filename(f"user_{current_user.id}_{f.filename}"); f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); current_user.profile_image = url_for('static', filename='uploads/'+fn)
        if 'real_name' in request.form: current_user.real_name = request.form['real_name']
        if 'email' in request.form: current_user.email = request.form['email']
        if request.form.get('new_password'):
            if request.form['new_password'] == request.form.get('confirm_password'): current_user.set_password(request.form['new_password']); flash('PW geändert', 'success')
        db.session.commit(); flash('Profil gespeichert', 'success'); return redirect(url_for('profile'))
    return render_template('profile.html', attempts=ExamAttempt.query.filter_by(user_id=current_user.id).order_by(ExamAttempt.timestamp.desc()).all(), user=current_user)

@app.route('/profile/reset_all', methods=['POST'])
@login_required
def reset_global_progress():
    UserProgress.query.filter_by(user_id=current_user.id).delete(); db.session.commit(); flash('Reset erfolgreich', 'warning'); return redirect(url_for('index'))

@app.route('/reset/<path:category_path>', methods=['POST'])
@login_required
def reset_category(category_path):
    cids = [c.id for c in Card.query.filter(Card.category.like(f"{category_path}%")).all()]
    if cids: UserProgress.query.filter(UserProgress.user_id==current_user.id, UserProgress.card_id.in_(cids)).delete(synchronize_session=False); db.session.commit()
    flash(f"Reset: {category_path}", "info"); return redirect(url_for('index'))

@app.route('/admin', methods=['GET','POST'])
@admin_required
def admin_dashboard():
    if request.method=='POST':
        if 'tag_name' in request.form:
            db.session.add(Tag(name=request.form['tag_name'])); db.session.commit(); return redirect(url_for('admin_dashboard'))
        if 'question' in request.form:
            cat_final = request.form.get('category_path') or request.form.get('category_new') or request.form.get('category_select')
            c=Card(category=cat_final, type=request.form['type'], question=request.form['question'])
            if 'tags_input' in request.form:
                for t in request.form.get('tags_input','').split(','):
                    if t.strip(): tag = Tag.query.filter_by(name=t.strip()).first() or Tag(name=t.strip()); db.session.add(tag); c.tags.append(tag)
            c.answer = request.form.get('answer_de_field') if c.type=='anatomy' else request.form.get('answer','')
            c.answer_lat = request.form.get('answer_lat')
            if c.type=='mc': c.options=json.dumps(request.form['options'].split(',')) if request.form['options'] else '[]'
            elif c.type=='anatomy_multi': c.options=request.form.get('multi_json')
            elif c.type=='ordering': c.options=request.form.get('ordering_json')
            elif c.type=='assignment': c.options=request.form.get('assignment_json')
            if 'image' in request.files and request.files['image']:
                f=request.files['image']; fn=secure_filename(f.filename); f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); c.image_url=url_for('static',filename='uploads/'+fn)
            db.session.add(c); db.session.commit(); flash('Gespeichert','success'); return redirect(url_for('admin_dashboard'))
    reports = CardReport.query.filter_by(resolved=False).order_by(CardReport.created_at.desc()).all()
    return render_template('admin.html', cards=Card.query.all(), categories=[c[0] for c in db.session.query(Card.category).distinct().all()], tags=Tag.query.all(), messages=DashboardMessage.query.all(), reports=reports)

@app.route('/admin/import', methods=['POST'])
@admin_required
def import_preview():
    if 'file' not in request.files: flash('Kein File','danger'); return redirect(url_for('admin_dashboard'))
    file = request.files['file']
    try:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        csv_input = csv.reader(stream, delimiter=';')
        
        preview_data = []
        for row in csv_input:
            if len(row) < 4: continue
            item = {'category': row[0], 'type': row[1], 'question': row[2], 'answer': row[3]}
            if len(row) > 4: item['options'] = row[4]
            preview_data.append(item)
            
        return render_template('admin_import_preview.html', data=preview_data, json_data=json.dumps(preview_data))
    except Exception as e: flash(f'Fehler: {e}','danger'); return redirect(url_for('admin_dashboard'))

@app.route('/admin/import/confirm', methods=['POST'])
@admin_required
def import_confirm():
    try:
        data = json.loads(request.form.get('json_data'))
        count = 0
        for item in data:
            c = Card(category=item['category'], type=item['type'], question=item['question'], answer=item['answer'])
            if 'options' in item and item['options']:
                if item['type'] == 'mc':
                    # FIX: Text "A, B" -> JSON ["A", "B"] UND Antwort dazu
                    opts = [x.strip() for x in item['options'].split(',')]
                    if c.answer and c.answer not in opts:
                        opts.append(c.answer)
                    c.options = json.dumps(opts)
                else:
                    c.options = item['options']
            db.session.add(c)
            count += 1
        db.session.commit()
        flash(f'{count} Fragen erfolgreich importiert!', 'success')
    except Exception as e: flash(f'Import Fehler: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/bulk_delete', methods=['POST'])
@admin_required
def bulk_delete():
    ids = request.form.getlist('selected_ids')
    if not ids: flash('Keine Fragen ausgewählt', 'warning'); return redirect(url_for('admin_dashboard'))
    count = 0
    for cid in ids:
        c = Card.query.get(int(cid))
        if c:
            UserProgress.query.filter_by(card_id=cid).delete()
            db.session.delete(c)
            count += 1
    db.session.commit()
    flash(f'{count} Fragen gelöscht.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/export')
@admin_required
def export_data():
    d={'cards':[{'q':c.question,'a':c.answer,'cat':c.category, 'type':c.type, 'opts':c.options} for c in Card.query.all()]}
    return Response(json.dumps(d, indent=2), mimetype='application/json', headers={'Content-Disposition':f'attachment;filename=topp-nfs-backup_{datetime.datetime.now().strftime("%Y-%m-%d")}.json'})

@app.route('/admin/reports/dismiss/<int:rid>', methods=['POST'])
@admin_required
def dismiss_report(rid):
    r = CardReport.query.get(rid); 
    if r: r.resolved=True; db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<int:card_id>', methods=['POST'])
@admin_required
def delete_card(card_id):
    c = Card.query.get_or_404(card_id); UserProgress.query.filter_by(card_id=card_id).delete(); db.session.delete(c); db.session.commit()
    flash('Gelöscht', 'success'); return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit/<int:card_id>', methods=['GET', 'POST'])
@admin_required
def edit_card(card_id):
    card = Card.query.get_or_404(card_id)
    
    options_str = ''
    if card.type == 'mc' and card.options:
        try:
            opts_list = json.loads(card.options)
            if isinstance(opts_list, list):
                options_str = ", ".join(opts_list)
            else:
                options_str = str(card.options)
        except:
            options_str = card.options

    if request.method == 'POST':
        card.category = request.form.get('category_new'); card.question = request.form.get('question'); card.type = request.form.get('type')
        card.answer = request.form.get('answer'); card.answer_lat = request.form.get('answer_lat')
        new_tags = request.form.get('tags_input', '')
        card.tags = [] 
        for t_name in new_tags.split(','):
            if t_name.strip():
                tag = Tag.query.filter_by(name=t_name.strip()).first()
                if not tag: tag = Tag(name=t_name.strip()); db.session.add(tag)
                card.tags.append(tag)
        if 'image' in request.files:
            f = request.files['image']
            if f and allowed_file(f.filename):
                fn = secure_filename(f.filename); f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); card.image_url = url_for('static', filename='uploads/'+fn)
        if card.type == 'mc': 
            opts_raw = request.form.get('options')
            if opts_raw:
                opts = [x.strip() for x in opts_raw.split(',')]
                if card.answer and card.answer not in opts:
                    opts.append(card.answer)
                card.options = json.dumps(opts)
            else:
                card.options = '[]'
        elif card.type == 'anatomy_multi': card.options = request.form.get('multi_json')
        elif card.type == 'ordering': card.options = request.form.get('ordering_json')
        elif card.type == 'assignment': card.options = request.form.get('assignment_json')
        db.session.commit(); flash('Gespeichert', 'success'); return redirect(url_for('admin_dashboard'))
    return render_template('edit_card.html', card=card, options_str=options_str, multi_json=card.options if card.type=='anatomy_multi' else '[]', ordering_json=card.options if card.type=='ordering' else '[]', assignment_json=card.options if card.type=='assignment' else '[]')

@app.route('/exam')
@login_required
def exam_index():
    valid_types = ['mc', 'anatomy', 'anatomy_multi', 'ordering', 'assignment']
    questions = Card.query.filter(Card.type.in_(valid_types)).order_by(func.random()).limit(30).all()
    prepared = []
    for card in questions:
        opts = []
        if card.options:
            try: opts = json.loads(card.options)
            except: opts = []
        
        if card.type == 'mc':
            opts = get_mc_options(card)
            
        elif card.type == 'ordering': random.shuffle(opts)
        elif card.type == 'assignment':
             pool=[]; [([pool.append({'val':i, 'group':g.get('name')}) for i in g.get('items',[])] if isinstance(opts,list) else None) for g in (opts if isinstance(opts,list) else [])]; random.shuffle(pool); card.temp_pool = pool
        prepared.append({'card': card, 'options': opts})
    return render_template('exam.html', questions=prepared)

@app.route('/exam/submit', methods=['POST'])
@login_required
def exam_submit():
    score = 0; total = 0; card_ids = request.form.getlist('card_ids')
    attempt = ExamAttempt(user_id=current_user.id, total_questions=len(card_ids)); db.session.add(attempt); db.session.commit()
    for cid in card_ids:
        card = Card.query.get(int(cid)); total += 1; is_correct = False
        if card.type == 'mc' and request.form.get(f'q_{cid}') == card.answer: is_correct = True
        if is_correct: score += 1
        db.session.add(ExamDetail(attempt_id=attempt.id, question_text=card.question, question_type=card.type, is_correct=is_correct))
    attempt.score = score; attempt.passed = (score >= (total * 0.6)); db.session.commit()
    return redirect(url_for('review_exam', attempt_id=attempt.id))

@app.route('/profile/exam/<int:attempt_id>')
@login_required
def review_exam(attempt_id):
    att = ExamAttempt.query.get_or_404(attempt_id)
    if att.user_id != current_user.id and not current_user.is_admin: flash("Verboten", "danger"); return redirect(url_for('profile'))
    res = [{'question':d.question_text, 'type':d.question_type, 'is_correct':d.is_correct} for d in att.details]
    return render_template('exam_result.html', score=att.score, total=att.total_questions, passed=att.passed, results=res, date=att.timestamp)

@app.route('/leaderboard')
def leaderboard(): return render_template('leaderboard.html', by_time=User.query.order_by(User.total_learning_time.desc()).limit(10).all(), by_streak=User.query.order_by(User.streak.desc()).limit(10).all())

@app.route('/search')
def search():
    q = request.args.get('q', '')
    results = Card.query.filter(or_(Card.question.ilike(f'%{q}%'), Card.answer.ilike(f'%{q}%'))).all() if q else []
    return render_template('search.html', query=q, results=results)

@app.route('/admin/messages', methods=['POST'])
@admin_required
def add_message(): db.session.add(DashboardMessage(content=request.form['content'])); db.session.commit(); return redirect(url_for('admin_dashboard'))

@app.route('/admin/messages/delete/<int:mid>')
@admin_required
def delete_message(mid): DashboardMessage.query.filter_by(id=mid).delete(); db.session.commit(); return redirect(url_for('admin_dashboard'))

# --- INIT ---
def seed_data():
    if not User.query.filter_by(username='admin').first(): 
        u=User(username='admin', is_admin=True); u.set_password('admin123'); db.session.add(u); db.session.commit()
        print("Admin user created")

with app.app_context():
    for i in range(10):
        try: db.create_all(); seed_data(); print("DB Ready"); break
        except: time.sleep(3)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

import os
import datetime
import json
import csv
import io
import random
import traceback
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.sql.expression import func, or_, and_
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail

app = Flask(__name__)
app.config['SECRET_KEY'] = 'geheimnis_fuer_topp_nfs_dev_key'
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp3', 'wav'}

# Dummy Mail Config
app.config['MAIL_SERVER'] = 'smtp.example.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'user@example.com'
app.config['MAIL_PASSWORD'] = 'password'

db = SQLAlchemy(app)
mail = Mail(app)
limiter = Limiter(key_func=get_remote_address, app=app, storage_uri="memory://")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- TABELLEN ---
card_tags = db.Table('card_tags', db.Column('card_id', db.Integer, db.ForeignKey('card.id')), db.Column('tag_id', db.Integer, db.ForeignKey('tag.id')))
user_badges = db.Table('user_badges', db.Column('user_id', db.Integer, db.ForeignKey('user.id')), db.Column('badge_id', db.Integer, db.ForeignKey('badge.id')), db.Column('earned_at', db.DateTime, default=datetime.datetime.utcnow))

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    users = db.relationship('User', backref='group', lazy=True)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

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
    category = db.Column(db.String(200), nullable=False) # Pfad-String
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
    user_response_json = db.Column(db.Text)
    correct_solution_json = db.Column(db.Text)
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

# --- HELPER FUNCTIONS ---
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

# MULTI-SELECT LOGIK: Akzeptiert Liste von Pfaden und sucht rekursiv
def get_next_card(user, paths, force=False):
    now = datetime.datetime.utcnow()
    
    # Baue Filter: (category LIKE 'Pfad1%' OR category LIKE 'Pfad2%')
    conditions = []
    for p in paths:
        conditions.append(Card.category.like(f"{p}%"))
    
    filter_cond = or_(*conditions)
    
    query = UserProgress.query.join(Card).filter(UserProgress.user_id==user.id, filter_cond)
    
    if not force: due = query.filter(UserProgress.next_review <= now).order_by(UserProgress.next_review.asc()).first()
    else: due = query.order_by(UserProgress.next_review.asc()).first()
    
    if due: return due.card, due
    
    sub = db.session.query(UserProgress.card_id).filter(UserProgress.user_id==user.id)
    new = Card.query.filter(filter_cond, ~Card.id.in_(sub)).order_by(func.random()).first()
    return new, None

def update_progress(user, card, known):
    p = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first()
    if not p: p = UserProgress(user_id=user.id, card_id=card.id, box=0); db.session.add(p)
    p.last_correct = known
    if known: p.box += 1; delta = datetime.timedelta(days=2**p.box)
    else: p.box = 0; delta = datetime.timedelta(minutes=3)
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

# --- ROUTES ---

@app.route('/')
def index():
    if current_user.is_authenticated: check_gamification(current_user)
    
    # Global Stats für das Chart
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
        flash('Fehler', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('index'))

@app.route('/learn/custom', methods=['POST'])
@login_required
def learn_custom():
    cats = request.form.getlist('categories')
    if not cats: flash("Bitte mindestens eine Kategorie wählen", "warning"); return redirect(url_for('index'))
    # Wir übergeben die Liste als String, getrennt durch Pipe '|', da Komma in Namen sein könnte
    return redirect(url_for('learn', category_path="|".join(cats)))

@app.route('/learn/<path:category_path>')
@login_required
def learn(category_path):
    # Pfade trennen (Pipe |)
    paths = category_path.split('|')
    f = request.args.get('force') == 'true'
    
    card, p = get_next_card(current_user, paths, force=f)
    
    if not card: 
        # Waiting Count Berechnung (komplexer bei mehreren Pfaden)
        conds = [Card.category.like(f"{p}%") for p in paths]
        w = UserProgress.query.join(Card).filter(UserProgress.user_id==current_user.id, or_(*conds), UserProgress.next_review>datetime.datetime.utcnow()).count()
        return render_template('quiz.html', finished=True, category=category_path, waiting_count=w)
    return render_learn_card(card)

def render_learn_card(card):
    p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first(); box = p.box if p else 0
    opts = json.loads(card.options) if card.options else []
    if card.type=='ordering': random.shuffle(opts)
    elif card.type=='assignment':
        pool=[]; [([pool.append({'val':i, 'group':g.get('name')}) for i in g.get('items',[])] if isinstance(opts,list) else None) for g in (opts if isinstance(opts,list) else [])]; random.shuffle(pool)
        return render_template('quiz.html', card=card, options=opts, pool_items=pool, finished=False, box=box)
    return render_template('quiz.html', card=card, options=opts, finished=False, box=box)

@app.route('/submit/<int:card_id>', methods=['POST'])
@login_required
def submit(card_id):
    try:
        if request.form.get('start_time'): 
            d=datetime.datetime.utcnow().timestamp()-float(request.form.get('start_time'))
            if 0<d<600: current_user.total_learning_time+=int(d); db.session.commit()
        
        card = Card.query.get_or_404(card_id); p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first(); box = p.box if p else 0
        
        if card.type=='mc':
            u=request.form.get('mc_answer'); corr=(u==card.answer); update_progress(current_user, card, corr); award_badges(current_user)
            return render_template('quiz.html', card=card, options=json.loads(card.options), finished=False, feedback=True, user_answer=u, is_correct=corr, box=box)
        elif card.type=='anatomy':
            ud=request.form.get('input_de','').lower(); ul=request.form.get('input_lat','').lower(); sd=card.answer.lower(); sl=card.answer_lat.lower(); corr=(ud==sd and ul==sl)
            update_progress(current_user, card, corr); award_badges(current_user)
            return render_template('quiz.html', card=card, finished=False, feedback_anatomy=True, result_de=(ud==sd), result_lat=(ul==sl), box=box)
        elif card.type=='anatomy_multi':
            sols=json.loads(card.options); sub=True; res=[]
            for i in sols:
                rid=str(i.get('id')); ud=request.form.get(f"de_{rid}",'').lower(); ul=request.form.get(f"lat_{rid}",'').lower()
                cde=(ud==i.get('de','').lower()); clat=(ul==i.get('lat','').lower())
                if not cde or not clat: sub=False
                res.append({'label':rid, 'user_de':ud, 'user_lat':ul, 'correct_de':i.get('de'), 'correct_lat':i.get('lat'), 'is_de_ok':cde, 'is_lat_ok':clat})
            update_progress(current_user, card, sub); award_badges(current_user)
            return render_template('quiz.html', card=card, finished=False, feedback_multi=True, multi_results=res, all_correct=sub, box=box)
        elif card.type=='ordering':
            co=json.loads(card.options); uo=json.loads(request.form.get('order_json')); corr=(uo==co)
            update_progress(current_user, card, corr); award_badges(current_user)
            return render_template('quiz.html', card=card, finished=False, feedback_ordering=True, user_order=uo, correct_order=co, is_correct=corr, box=box)
        elif card.type=='assignment':
            cs=json.loads(card.options); ud=json.loads(request.form.get('assignment_json')); all_c=True; res=[]
            for g in cs:
                gn=g.get('name'); ci=g.get('items',[]); ui=ud.get(gn,[]); gr={'name':gn,'group_items':[],'missing':[]}
                for i, u in enumerate(ui):
                    st={'text':u}; 
                    if u not in ci: all_c=False; st['correct']=False; st['reason']='wrong_group'; st['actual_group']='?'
                    elif i<len(ci) and ci[i]==u: st['correct']=True
                    else: all_c=False; st['correct']=False; st['reason']='wrong_order'
                    gr['group_items'].append(st)
                for c in ci: 
                    if c not in ui: all_c=False; gr['missing'].append(c)
                res.append(gr)
            update_progress(current_user, card, all_c); award_badges(current_user)
            return render_template('quiz.html', card=card, finished=False, feedback_assignment=True, all_correct=all_c, assignment_results=res, box=box)
        else: # Flashcard
            k=(request.form.get('result')=='known'); update_progress(current_user, card, k); award_badges(current_user)
            return redirect(url_for('learn', category=card.category))
    except Exception as e: print(e); return "Fehler", 500

@app.route('/reset/<path:category_path>', methods=['POST'])
@login_required
def reset_category(category_path):
    cards = Card.query.filter(Card.category.like(f"{category_path}%")).all()
    cids = [c.id for c in cards]
    if cids:
        UserProgress.query.filter(UserProgress.user_id==current_user.id, UserProgress.card_id.in_(cids)).delete(synchronize_session=False)
        db.session.commit()
    flash(f"Fortschritt für {category_path} gelöscht.", "info")
    return redirect(url_for('index'))

@app.route('/admin', methods=['GET','POST'])
@admin_required
def admin_dashboard():
    if request.method=='POST' and 'tag_name' in request.form:
        db.session.add(Tag(name=request.form['tag_name'])); db.session.commit(); return redirect(url_for('admin_dashboard'))
    if request.method=='POST' and 'question' in request.form:
        cat_final = request.form.get('category_path')
        if not cat_final: cat_final = request.form.get('category_new') or request.form.get('category_select')
        c=Card(category=cat_final, type=request.form['type'], question=request.form['question'])
        tags_raw = request.form.get('tags_input','')
        if tags_raw:
            for t_name in tags_raw.split(','):
                t_name = t_name.strip()
                if t_name:
                    tag = Tag.query.filter_by(name=t_name).first()
                    if not tag: tag = Tag(name=t_name); db.session.add(tag)
                    c.tags.append(tag)
        if c.type=='anatomy': c.answer=request.form.get('answer_de_field'); c.answer_lat=request.form.get('answer_lat')
        else: c.answer=request.form.get('answer','')
        if c.type=='mc': c.options=json.dumps(request.form['options'].split(',')) if request.form['options'] else '[]'
        elif c.type=='anatomy_multi': c.options=request.form.get('multi_json')
        elif c.type=='ordering': c.options=request.form.get('ordering_json')
        elif c.type=='assignment': c.options=request.form.get('assignment_json')
        if 'image' in request.files:
            f=request.files['image']; 
            if f and allowed_file(f.filename): fn=secure_filename(f.filename); f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); c.image_url=url_for('static',filename='uploads/'+fn)
        if 'audio' in request.files:
            f=request.files['audio']; 
            if f and allowed_file(f.filename): fn=secure_filename(f.filename); f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); c.audio_url=url_for('static',filename='uploads/'+fn)
        db.session.add(c); db.session.commit(); flash('Gespeichert','success'); return redirect(url_for('admin_dashboard'))
    cats = [c[0] for c in db.session.query(Card.category).distinct().all()]
    return render_template('admin.html', cards=Card.query.all(), categories=cats, tags=Tag.query.all(), messages=DashboardMessage.query.all(), groups=Group.query.all())

# WIEDERHERGESTELLTE ROUTEN FÜR IMPORT / EXPORT / MESSAGES

@app.route('/admin/import', methods=['POST'])
@admin_required
def import_csv():
    if 'file' not in request.files: flash('Keine Datei','danger'); return redirect(url_for('admin_dashboard'))
    file = request.files['file']
    if file:
        try:
            stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
            csv_input = csv.reader(stream, delimiter=';')
            for row in csv_input:
                if len(row) < 4: continue
                # Erwartet: Category;Type;Question;Answer;Options
                c = Card(category=row[0], type=row[1], question=row[2], answer=row[3])
                if len(row) > 4 and row[4]: 
                    if c.type=='mc': c.options = json.dumps([x.strip() for x in row[4].split(',')])
                    else: c.options = row[4] # Raw JSON für komplexe Typen
                db.session.add(c)
            db.session.commit(); flash('Import erfolgreich','success')
        except Exception as e: flash(f'Import Fehler: {e}','danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/messages', methods=['POST'])
@admin_required
def add_message(): db.session.add(DashboardMessage(content=request.form['content'])); db.session.commit(); return redirect(url_for('admin_dashboard'))

@app.route('/admin/messages/delete/<int:mid>')
@admin_required
def delete_message(mid): DashboardMessage.query.filter_by(id=mid).delete(); db.session.commit(); return redirect(url_for('admin_dashboard'))

@app.route('/admin/export')
@admin_required
def export_data():
    d={'cards':[{'q':c.question,'a':c.answer,'cat':c.category} for c in Card.query.all()]}; return json.dumps(d), 200, {'Content-Type':'application/json','Content-Disposition':'attachment;filename=backup.json'}

# ... Profile/Exam/Users Routen wie bekannt (Platzhalter, damit Datei nicht zu lang wird, sind aber notwendig) ...
# (Bitte die vorherigen Implementierungen für /profile, /exam, /admin/users nutzen. Siehe vorherige Antworten.)
# Um Fehler zu vermeiden, füge ich die wichtigsten Profil/Exam Routen wieder an:

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if 'profile_image' in request.files:
            f = request.files['profile_image']
            if f and allowed_file(f.filename): fn = secure_filename(f"user_{current_user.id}_{f.filename}"); f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); current_user.profile_image = url_for('static', filename='uploads/'+fn)
        if 'real_name' in request.form: current_user.real_name = request.form['real_name']
        if request.form.get('new_password'):
            if request.form['new_password'] == request.form.get('confirm_password'): current_user.set_password(request.form['new_password']); flash('Passwort geändert', 'success')
        db.session.commit(); flash('Profil gespeichert', 'success'); return redirect(url_for('profile'))
    att = ExamAttempt.query.filter_by(user_id=current_user.id).order_by(ExamAttempt.timestamp.desc()).all()
    return render_template('profile.html', attempts=att, user=current_user)

@app.route('/profile/exam/<int:attempt_id>')
@login_required
def review_exam(attempt_id):
    att = ExamAttempt.query.get_or_404(attempt_id)
    if att.user_id != current_user.id and not current_user.is_admin: flash("Verboten", "danger"); return redirect(url_for('profile'))
    res = []
    for d in att.details:
        res.append({'question':d.question_text, 'type':d.question_type, 'is_correct':d.is_correct})
    return render_template('exam_result.html', score=att.score, total=att.total_questions, passed=att.passed, results=res, date=att.timestamp)

@app.route('/learn/errors')
@login_required
def learn_errors():
    sub = db.session.query(UserProgress.card_id).filter(UserProgress.user_id==current_user.id, or_(UserProgress.box==0, UserProgress.last_correct==False))
    card = Card.query.filter(Card.id.in_(sub)).order_by(func.random()).first()
    if not card: flash("Keine Fehler!", "success"); return redirect(url_for('index'))
    return render_learn_card(card)

@app.route('/admin/users')
@admin_required
def admin_users(): return render_template('admin_users.html', users=User.query.all())

@app.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    if User.query.filter_by(username=request.form['username']).first(): flash('Existiert','danger')
    else: u=User(username=request.form['username'], is_admin='is_admin' in request.form); u.set_password(request.form['password']); db.session.add(u); db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<int:uid>', methods=['POST'])
@admin_required
def delete_user(uid):
    u=User.query.get(uid); 
    if u and u.username!='admin': db.session.delete(u); db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/users/reset/<int:uid>', methods=['POST'])
@admin_required
def reset_user_password(uid):
    u=User.query.get(uid); u.set_password(request.form['new_password']); db.session.commit(); flash('Reset OK','success'); return redirect(url_for('admin_users'))

def seed_data():
    if not User.query.filter_by(username='admin').first(): u=User(username='admin', is_admin=True); u.set_password('admin123'); db.session.add(u); db.session.commit()

if __name__ == '__main__':
    with app.app_context(): db.create_all(); seed_data()
    app.run(host='0.0.0.0', port=5000)

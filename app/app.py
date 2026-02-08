import os
import datetime
import json
import csv
import io
import random
import traceback
import math
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.sql.expression import func, or_

app = Flask(__name__)
# Sicherheitsschlüssel (in Produktion durch einen echten Secret Key ersetzen)
app.config['SECRET_KEY'] = 'geheimnis_fuer_topp_nfs_dev_key'

# Datenbank Konfiguration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Upload Ordner
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELLE ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Profil-Felder
    real_name = db.Column(db.String(100), nullable=True)
    age = db.Column(db.Integer, nullable=True)
    bio = db.Column(db.Text, nullable=True)
    profile_image = db.Column(db.String(200), nullable=True)
    total_learning_time = db.Column(db.Integer, default=0) # Sekunden

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50))
    type = db.Column(db.String(20))     
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False) 
    answer_lat = db.Column(db.Text, nullable=True) 
    options = db.Column(db.Text, nullable=True) 
    image_url = db.Column(db.String(200), nullable=True)

class UserProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False)
    box = db.Column(db.Integer, default=0)
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
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Zugriff verweigert!", "danger"); return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.template_filter('format_duration')
def format_duration(seconds):
    if not seconds: return "0 Min"
    m, s = divmod(seconds, 60); h, m = divmod(m, 60)
    if h > 0: return f"{h} Std {m} Min"
    return f"{m} Min {s} Sek"

@app.context_processor
def inject_now(): return {'now': datetime.datetime.utcnow()}

# --- LOGIK ---

def get_next_card(user, category, force=False):
    now = datetime.datetime.utcnow()
    query = UserProgress.query.join(Card).filter(UserProgress.user_id == user.id, Card.category == category)
    if not force:
        due_progress = query.filter(UserProgress.next_review <= now).order_by(UserProgress.next_review.asc()).first()
    else:
        due_progress = query.order_by(UserProgress.next_review.asc()).first()
    if due_progress: return due_progress.card, due_progress
    subquery = db.session.query(UserProgress.card_id).filter(UserProgress.user_id == user.id)
    new_card = Card.query.filter(Card.category == category, ~Card.id.in_(subquery)).first()
    return new_card, None

def update_progress(user, card, known):
    progress = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first()
    if not progress:
        progress = UserProgress(user_id=user.id, card_id=card.id, box=0); db.session.add(progress)
    if known:
        progress.box += 1; delta = datetime.timedelta(days=2 ** progress.box)
    else:
        progress.box = 0; delta = datetime.timedelta(minutes=3)
    progress.next_review = datetime.datetime.utcnow() + delta; db.session.commit()

def seed_data():
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin); db.session.commit()
        print("Admin User erstellt.")

# --- ROUTEN ---

@app.route('/')
def index():
    categories = db.session.query(Card.category).distinct().all(); stats = {}
    if current_user.is_authenticated:
        for cat in categories:
            cat_name = cat[0]
            total = Card.query.filter_by(category=cat_name).count()
            learned = UserProgress.query.join(Card).filter(UserProgress.user_id == current_user.id, Card.category == cat_name, UserProgress.box > 0).count()
            stats[cat_name] = {'total': total, 'learned': learned}
    else: stats = {c[0]: {'total': Card.query.filter_by(category=c[0]).count(), 'learned': 0} for c in categories}
    return render_template('index.html', stats=stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user); return redirect(url_for('index'))
        flash('Login fehlgeschlagen.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('index'))

# PROFIL
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"user_{current_user.id}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                current_user.profile_image = url_for('static', filename='uploads/' + filename)
        if 'real_name' in request.form: current_user.real_name = request.form['real_name']
        if 'age' in request.form: 
            try: current_user.age = int(request.form['age'])
            except: pass
        if 'bio' in request.form: current_user.bio = request.form['bio']
        if request.form.get('new_password'):
            if request.form['new_password'] == request.form.get('confirm_password'):
                current_user.set_password(request.form['new_password'])
                flash('Passwort geändert.', 'success')
            else: flash('Passwörter stimmen nicht überein.', 'warning')
        db.session.commit(); flash('Profil aktualisiert.', 'success'); return redirect(url_for('profile'))
    attempts = ExamAttempt.query.filter_by(user_id=current_user.id).order_by(ExamAttempt.timestamp.desc()).all()
    return render_template('profile.html', attempts=attempts, user=current_user)

@app.route('/profile/exam/<int:attempt_id>')
@login_required
def review_exam(attempt_id):
    attempt = ExamAttempt.query.get_or_404(attempt_id)
    if attempt.user_id != current_user.id and not current_user.is_admin:
        flash("Zugriff verweigert", "danger"); return redirect(url_for('profile'))
    results = []
    for d in attempt.details:
        try:
            u_res = json.loads(d.user_response_json) if d.user_response_json else None
            c_res = json.loads(d.correct_solution_json) if d.correct_solution_json else None
        except: u_res, c_res = "Fehler", "Fehler"
        results.append({'question': d.question_text, 'type': d.question_type, 'is_correct': d.is_correct, 'user_data': u_res, 'correct_data': c_res})
    percent = int((attempt.score / attempt.total_questions * 100)) if attempt.total_questions > 0 else 0
    return render_template('exam_result.html', score=attempt.score, total=attempt.total_questions, percent=percent, passed=attempt.passed, results=results, date=attempt.timestamp)

# LERNEN & SUBMIT
@app.route('/learn/<category>')
@login_required
def learn(category):
    force_mode = request.args.get('force') == 'true'
    card, progress = get_next_card(current_user, category, force=force_mode)
    if not card:
        waiting_count = UserProgress.query.join(Card).filter(UserProgress.user_id == current_user.id, Card.category == category, UserProgress.next_review > datetime.datetime.utcnow()).count()
        return render_template('quiz.html', finished=True, category=category, waiting_count=waiting_count)
    current_box = progress.box if progress else 0
    try: options_list = json.loads(card.options) if card.options else []
    except: options_list = []
    if card.type == 'ordering':
        shuffled = options_list.copy(); random.shuffle(shuffled)
        return render_template('quiz.html', card=card, options=shuffled, finished=False, box=current_box, force_mode=force_mode)
    elif card.type == 'assignment':
        pool_items = []
        try:
            if isinstance(options_list, list):
                for group in options_list:
                    if isinstance(group, dict):
                        for item in group.get('items', []): pool_items.append({'val': item, 'group': group.get('name', 'Unbekannt')})
        except: pass
        random.shuffle(pool_items)
        return render_template('quiz.html', card=card, options=options_list, pool_items=pool_items, finished=False, box=current_box, force_mode=force_mode)
    return render_template('quiz.html', card=card, options=options_list, finished=False, box=current_box, force_mode=force_mode)

@app.route('/submit/<int:card_id>', methods=['POST'])
@login_required
def submit(card_id):
    try:
        start_time = request.form.get('start_time')
        if start_time:
            try:
                duration = datetime.datetime.utcnow().timestamp() - float(start_time)
                if duration > 0 and duration < 600:
                    current_user.total_learning_time += int(duration); db.session.commit()
            except: pass
        card = Card.query.get_or_404(card_id); progress = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
        current_box = progress.box if progress else 0
        
        if card.type == 'mc':
            user_answer = request.form.get('mc_answer'); is_correct = (user_answer == card.answer)
            update_progress(current_user, card, is_correct)
            try: options_list = json.loads(card.options) if card.options else []
            except: options_list = []
            progress = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, options=options_list, finished=False, feedback=True, user_answer=user_answer, is_correct=is_correct, box=progress.box)
        elif card.type == 'anatomy':
            u_de = request.form.get('input_de', '').strip().lower(); u_lat = request.form.get('input_lat', '').strip().lower()
            s_de = card.answer.strip().lower() if card.answer else ""; s_lat = card.answer_lat.strip().lower() if card.answer_lat else ""
            is_correct = (u_de == s_de) and (u_lat == s_lat); update_progress(current_user, card, is_correct)
            progress = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_anatomy=True, result_de=(u_de==s_de), result_lat=(u_lat==s_lat), box=progress.box)
        elif card.type == 'anatomy_multi':
            try: solutions = json.loads(card.options) if card.options else []
            except: solutions = []
            results = []; all_correct = True
            for item in solutions:
                row_id = str(item.get('id', '?')).strip()
                inp_de = request.form.get(f"de_{row_id}", "").strip().lower(); inp_lat = request.form.get(f"lat_{row_id}", "").strip().lower()
                sol_de = item.get('de', '').strip().lower(); sol_lat = item.get('lat', '').strip().lower()
                check_de = (inp_de == sol_de) if sol_de else True; check_lat = (inp_lat == sol_lat) if sol_lat else True
                if not check_de or not check_lat: all_correct = False
                results.append({'label': item.get('id'), 'user_de': request.form.get(f"de_{row_id}"), 'user_lat': request.form.get(f"lat_{row_id}"), 'correct_de': item.get('de'), 'correct_lat': item.get('lat'), 'is_de_ok': check_de, 'is_lat_ok': check_lat})
            update_progress(current_user, card, all_correct)
            progress = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_multi=True, multi_results=results, all_correct=all_correct, box=progress.box)
        elif card.type == 'ordering':
            try: correct_order = json.loads(card.options) if card.options else []
            except: correct_order = []
            raw_order = request.form.get('order_json')
            try: user_order = json.loads(raw_order) if raw_order else []
            except: user_order = []
            is_correct = (user_order == correct_order); update_progress(current_user, card, is_correct)
            progress = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_ordering=True, user_order=user_order, correct_order=correct_order, is_correct=is_correct, box=progress.box)
        elif card.type == 'assignment':
            try: correct_structure = json.loads(card.options) if card.options else []
            except: correct_structure = []
            raw_json = request.form.get('assignment_json')
            try: user_data = json.loads(raw_json) if raw_json else {}
            except: user_data = {}
            results = []; all_correct = True
            if isinstance(correct_structure, list):
                for grp in correct_structure:
                    if not isinstance(grp, dict): continue
                    g_name = grp.get('name', 'Unbekannt'); c_items = grp.get('items', []); u_items = user_data.get(g_name, [])
                    grp_res = {'name': g_name, 'group_items': [], 'missing': []}
                    for index, u in enumerate(u_items):
                        status = {'text': u}
                        if u not in c_items:
                            all_correct = False; status['correct'] = False; status['reason'] = 'wrong_group'
                            actual = "?"; 
                            for g in correct_structure: 
                                if isinstance(g, dict) and u in g.get('items', []): actual = g.get('name', '?')
                            status['actual_group'] = actual
                        else:
                            if index < len(c_items) and c_items[index] == u: status['correct'] = True
                            else: all_correct = False; status['correct'] = False; status['reason'] = 'wrong_order'
                        grp_res['group_items'].append(status)
                    for c in c_items:
                        if c not in u_items: all_correct = False; grp_res['missing'].append(c)
                    results.append(grp_res)
            update_progress(current_user, card, all_correct)
            progress = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_assignment=True, all_correct=all_correct, assignment_results=results, box=progress.box)
        else: # Flashcard
            is_known = (request.form.get('result') == 'known')
            update_progress(current_user, card, is_known)
            return redirect(url_for('learn', category=card.category))
    except Exception as e:
        print(f"CRITICAL ERROR SUBMIT: {e}"); traceback.print_exc()
        return f"Fehler 500: {e}", 500

@app.route('/reset/<category>', methods=['POST'])
@login_required
def reset_category(category):
    cards = Card.query.filter_by(category=category).all(); card_ids = [c.id for c in cards]
    if card_ids:
        UserProgress.query.filter(UserProgress.user_id == current_user.id, UserProgress.card_id.in_(card_ids)).delete(synchronize_session=False)
        db.session.commit()
    flash(f'Fortschritt für "{category}" zurückgesetzt.', 'info'); return redirect(url_for('learn', category=category))

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', ''); results = []
    if query: results = Card.query.filter(or_(Card.question.ilike(f'%{query}%'),Card.answer.ilike(f'%{query}%'),Card.category.ilike(f'%{query}%'))).all()
    return render_template('search.html', query=query, results=results)

@app.route('/tools')
def tools(): return render_template('tools.html')

# EXAM
@app.route('/exam')
@login_required
def start_exam():
    questions = Card.query.filter(Card.type != 'flashcard').order_by(func.random()).limit(20).all(); exam_data = []
    for q in questions:
        opts = []
        try:
            if q.options:
                opts = json.loads(q.options)
                if q.type == 'ordering': random.shuffle(opts)
                elif q.type == 'assignment':
                    pool = []
                    if isinstance(opts, list):
                        for grp in opts:
                            for item in grp.get('items', []): pool.append({'val': item, 'group': grp.get('name')})
                    random.shuffle(pool); q.temp_pool = pool
        except: opts = []
        exam_data.append({'card': q, 'options': opts})
    return render_template('exam.html', questions=exam_data)

@app.route('/exam/submit', methods=['POST'])
@login_required
def submit_exam():
    score = 0; total = 0; submitted_ids = request.form.getlist('card_ids')
    attempt = ExamAttempt(user_id=current_user.id); db.session.add(attempt); db.session.commit()
    try:
        for str_id in submitted_ids:
            try:
                card_id = int(str_id); card = Card.query.get(card_id)
                if not card: continue
                total += 1; is_correct = False; user_data_obj = None; correct_data_obj = None
                
                if card.type == 'mc':
                    val = request.form.get(f'q_{card.id}'); is_correct = (val == card.answer)
                    user_data_obj = val; correct_data_obj = card.answer
                elif card.type == 'anatomy':
                    u_de = request.form.get(f'q_{card.id}_de', '').strip().lower(); u_lat = request.form.get(f'q_{card.id}_lat', '').strip().lower()
                    s_de = card.answer.strip().lower() if card.answer else ""; s_lat = card.answer_lat.strip().lower() if card.answer_lat else ""
                    is_correct = (u_de == s_de) and (u_lat == s_lat)
                    user_data_obj = {'de': u_de, 'lat': u_lat}; correct_data_obj = {'de': s_de, 'lat': s_lat}
                elif card.type == 'anatomy_multi':
                    sols = json.loads(card.options) if card.options else []; sub_correct = True; u_list = []
                    for item in sols:
                        rid = str(item.get('id')).strip()
                        ude = request.form.get(f'q_{card.id}_{rid}_de', '').strip().lower(); ulat = request.form.get(f'q_{card.id}_{rid}_lat', '').strip().lower()
                        sde = item.get('de', '').strip().lower(); slat = item.get('lat', '').strip().lower()
                        if sde and ude != sde: sub_correct = False
                        if slat and ulat != slat: sub_correct = False
                        u_list.append({'id': rid, 'de': ude, 'lat': ulat})
                    is_correct = sub_correct; user_data_obj = u_list; correct_data_obj = sols
                elif card.type == 'ordering':
                    correct_list = json.loads(card.options) if card.options else []; raw = request.form.get(f'q_{card.id}_json')
                    user_list = json.loads(raw) if raw else []; is_correct = (user_list == correct_list)
                    user_data_obj = user_list; correct_data_obj = correct_list
                elif card.type == 'assignment':
                    correct_structure = json.loads(card.options) if card.options else []; raw = request.form.get(f'q_{card.id}_json')
                    user_dict = json.loads(raw) if raw else {}; assign_correct = True
                    for grp in correct_structure:
                        g_name = grp['name']; c_items = grp.get('items', []); u_items = user_dict.get(g_name, [])
                        if c_items != u_items: assign_correct = False
                    is_correct = assign_correct; user_data_obj = user_dict; correct_data_obj = correct_structure
                
                if is_correct: score += 1
                detail = ExamDetail(attempt_id=attempt.id, question_text=card.question, question_type=card.type, is_correct=is_correct, user_response_json=json.dumps(user_data_obj), correct_solution_json=json.dumps(correct_data_obj))
                db.session.add(detail)
            except: pass
        attempt.score = score; attempt.total_questions = total; attempt.passed = (score / total * 100 >= 60) if total > 0 else False
        db.session.commit(); return redirect(url_for('review_exam', attempt_id=attempt.id))
    except: return "Fehler", 500

# ADMIN
@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_dashboard():
    existing_categories = [c[0] for c in db.session.query(Card.category).distinct().all()]
    if request.method == 'POST':
        if 'file' in request.files: return redirect(url_for('import_csv'))
        cat = request.form.get('category_new') or request.form.get('category_select'); q_type = request.form['type']
        new_card = Card(category=cat, type=q_type, question=request.form['question'], answer=request.form.get('answer', ''))
        if q_type == 'mc':
            opts_raw = request.form['options']; opts_list = [o.strip() for o in opts_raw.split(',')]
            if new_card.answer not in opts_list: opts_list.append(new_card.answer)
            new_card.options = json.dumps(opts_list)
        elif q_type == 'anatomy': new_card.answer_lat = request.form.get('answer_lat')
        elif q_type == 'anatomy_multi': new_card.options = request.form.get('multi_json'); new_card.answer = "Siehe Details"
        elif q_type == 'ordering': new_card.options = request.form.get('ordering_json'); new_card.answer = "Reihenfolge"
        elif q_type == 'assignment': new_card.options = request.form.get('assignment_json'); new_card.answer = "Zuordnung"
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename); file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                new_card.image_url = url_for('static', filename='uploads/' + filename)
        db.session.add(new_card); db.session.commit(); flash('Frage hinzugefügt', 'success'); return redirect(url_for('admin_dashboard'))
    all_cards = Card.query.order_by(Card.id.desc()).all()
    return render_template('admin.html', cards=all_cards, categories=existing_categories)

@app.route('/admin/delete/<int:card_id>', methods=['POST'])
@admin_required
def delete_card(card_id):
    card = Card.query.get_or_404(card_id); UserProgress.query.filter_by(card_id=card.id).delete(); db.session.delete(card); db.session.commit()
    flash('Karte gelöscht', 'info'); return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit/<int:card_id>', methods=['GET', 'POST'])
@admin_required
def edit_card(card_id):
    card = Card.query.get_or_404(card_id); cats = [c[0] for c in db.session.query(Card.category).distinct().all()]
    if request.method == 'POST':
        card.category = request.form.get('category_new') or request.form.get('category_select')
        card.question = request.form['question']; card.answer = request.form['answer']; card.type = request.form['type']
        if card.type == 'mc':
            opts = [o.strip() for o in request.form['options'].split(',')]
            if card.answer not in opts: opts.append(card.answer)
            card.options = json.dumps(opts)
        elif card.type == 'anatomy': card.answer_lat = request.form.get('answer_lat'); card.options = None
        elif card.type == 'anatomy_multi': card.options = request.form.get('multi_json'); card.answer_lat = None
        elif card.type == 'ordering': card.options = request.form.get('ordering_json')
        elif card.type == 'assignment': card.options = request.form.get('assignment_json')
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                fn = secure_filename(file.filename); file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                card.image_url = url_for('static', filename='uploads/' + fn)
        db.session.commit(); flash('Gespeichert', 'success'); return redirect(url_for('admin_dashboard'))
    opts_str = ""; m_json = "[]"; o_json = "[]"; a_json = "[]"
    if card.options:
        try:
            if card.type == 'mc': opts_str = ", ".join(json.loads(card.options))
            elif card.type == 'anatomy_multi': m_json = card.options 
            elif card.type == 'ordering': o_json = card.options
            elif card.type == 'assignment': a_json = card.options
        except: pass
    return render_template('edit_card.html', card=card, categories=cats, options_str=opts_str, multi_json=m_json, ordering_json=o_json, assignment_json=a_json)

@app.route('/admin/import', methods=['POST'])
@admin_required
def import_csv():
    if 'file' not in request.files: return redirect(url_for('admin_dashboard'))
    file = request.files['file']
    if file:
        try:
            stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
            csv_input = csv.reader(stream, delimiter=';')
            for row in csv_input:
                if len(row) < 4: continue
                cat = row[0].strip(); q_type = row[1].strip().lower(); question = row[2].strip(); answer = row[3].strip()
                new_card = Card(category=cat, type=q_type, question=question, answer=answer)
                if q_type == 'mc' and len(row) > 4:
                    opts = [o.strip() for o in row[4].split(',')]
                    if answer not in opts: opts.append(answer)
                    new_card.options = json.dumps(opts)
                db.session.add(new_card)
            db.session.commit(); flash('Import erfolgreich', 'success')
        except Exception as e: flash(f'Fehler: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))

# USER MANAGEMENT
@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    if User.query.filter_by(username=request.form['username']).first(): flash('Existiert bereits', 'danger')
    else:
        u = User(username=request.form['username'], is_admin=('is_admin' in request.form))
        u.set_password(request.form['password'])
        db.session.add(u); db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.username != 'admin':
        UserProgress.query.filter_by(user_id=user.id).delete()
        ExamAttempt.query.filter_by(user_id=user.id).delete() # Löscht auch Details via Cascade
        db.session.delete(user); db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/users/reset/<int:user_id>', methods=['POST'])
@admin_required
def reset_user_password(user_id):
    user = User.query.get_or_404(user_id)
    if request.form['new_password']:
        user.set_password(request.form['new_password'])
        db.session.commit()
        flash(f'Passwort für {user.username} zurückgesetzt.', 'success')
    return redirect(url_for('admin_users'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    app.run(host='0.0.0.0', port=5000)

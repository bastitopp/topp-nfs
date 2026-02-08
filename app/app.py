import os
import datetime
import json
import csv
import io
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.sql.expression import func, or_

app = Flask(__name__)
app.config['SECRET_KEY'] = 'geheimnis_fuer_topp_nfs_dev_key'
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50))
    type = db.Column(db.String(20))     # 'flashcard', 'mc'
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    options = db.Column(db.Text, nullable=True) # JSON String
    image_url = db.Column(db.String(200), nullable=True)

class UserProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False)
    box = db.Column(db.Integer, default=0)
    next_review = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    card = db.relationship('Card', backref='progress_records')
    user = db.relationship('User', backref='progress_records')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Zugriff verweigert! Nur für Admins.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- LOGIK: LERNEN ---

def get_next_card(user, category, force=False):
    now = datetime.datetime.utcnow()
    query = UserProgress.query.join(Card).filter(
        UserProgress.user_id == user.id,
        Card.category == category
    )
    if not force:
        due_progress = query.filter(UserProgress.next_review <= now)\
                            .order_by(UserProgress.next_review.asc()).first()
    else:
        due_progress = query.order_by(UserProgress.next_review.asc()).first()
    
    if due_progress: return due_progress.card, due_progress
    
    subquery = db.session.query(UserProgress.card_id).filter(UserProgress.user_id == user.id)
    new_card = Card.query.filter(Card.category == category, ~Card.id.in_(subquery)).first()
    return new_card, None

def update_progress(user, card, known):
    progress = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first()
    if not progress:
        progress = UserProgress(user_id=user.id, card_id=card.id, box=0)
        db.session.add(progress)
    
    if known:
        progress.box += 1
        days_to_add = 2 ** progress.box
        delta = datetime.timedelta(days=days_to_add)
    else:
        progress.box = 0
        delta = datetime.timedelta(minutes=3)
    
    progress.next_review = datetime.datetime.utcnow() + delta
    db.session.commit()

def seed_data():
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

# --- ROUTEN ---

@app.route('/')
def index():
    categories = db.session.query(Card.category).distinct().all()
    stats = {}
    if current_user.is_authenticated:
        for cat in categories:
            cat_name = cat[0]
            total = Card.query.filter_by(category=cat_name).count()
            learned = UserProgress.query.join(Card).filter(
                UserProgress.user_id == current_user.id,
                Card.category == cat_name,
                UserProgress.box > 0
            ).count()
            stats[cat_name] = {'total': total, 'learned': learned}
    else:
        stats = {c[0]: {'total': Card.query.filter_by(category=c[0]).count(), 'learned': 0} for c in categories}
    return render_template('index.html', stats=stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('index'))
        flash('Login fehlgeschlagen.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/learn/<category>')
@login_required
def learn(category):
    force_mode = request.args.get('force') == 'true'
    card, progress = get_next_card(current_user, category, force=force_mode)
    
    if not card:
        waiting_count = UserProgress.query.join(Card).filter(
            UserProgress.user_id == current_user.id,
            Card.category == category,
            UserProgress.next_review > datetime.datetime.utcnow()
        ).count()
        return render_template('quiz.html', finished=True, category=category, waiting_count=waiting_count)
    
    current_box = progress.box if progress else 0
    options_list = json.loads(card.options) if card.options else []
    return render_template('quiz.html', card=card, options=options_list, finished=False, box=current_box, force_mode=force_mode)

@app.route('/submit/<int:card_id>', methods=['POST'])
@login_required
def submit(card_id):
    card = Card.query.get_or_404(card_id)
    if 'mc_answer' in request.form:
        user_answer = request.form.get('mc_answer')
        is_correct = (user_answer == card.answer)
        update_progress(current_user, card, is_correct)
        options_list = json.loads(card.options) if card.options else []
        progress = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
        current_box = progress.box if progress else 0
        return render_template('quiz.html', card=card, options=options_list, finished=False, feedback=True, user_answer=user_answer, is_correct=is_correct, box=current_box)
    else:
        is_known = (request.form.get('result') == 'known')
        update_progress(current_user, card, is_known)
        return redirect(url_for('learn', category=card.category))

@app.route('/reset/<category>', methods=['POST'])
@login_required
def reset_category(category):
    cards = Card.query.filter_by(category=category).all()
    card_ids = [c.id for c in cards]
    if card_ids:
        UserProgress.query.filter(UserProgress.user_id == current_user.id, UserProgress.card_id.in_(card_ids)).delete(synchronize_session=False)
        db.session.commit()
    flash(f'Fortschritt für "{category}" zurückgesetzt.', 'info')
    return redirect(url_for('learn', category=category))

# --- NEU: SUCHE ROUTE ---
@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '')
    results = []
    if query:
        # Case-insensitive Suche in Frage UND Antwort
        results = Card.query.filter(
            or_(
                Card.question.ilike(f'%{query}%'),
                Card.answer.ilike(f'%{query}%'),
                Card.category.ilike(f'%{query}%')
            )
        ).all()
    return render_template('search.html', query=query, results=results)

@app.route('/tools')
def tools():
    return render_template('tools.html')

# --- EXAM MODUS ---

@app.route('/exam')
@login_required
def start_exam():
    questions = Card.query.filter(Card.type == 'mc').order_by(func.random()).limit(20).all()
    exam_data = []
    for q in questions:
        opts = json.loads(q.options) if q.options else []
        exam_data.append({'card': q, 'options': opts})
    return render_template('exam.html', questions=exam_data)

@app.route('/exam/submit', methods=['POST'])
@login_required
def submit_exam():
    score = 0
    total = 0
    results = []
    for key, value in request.form.items():
        if key.startswith('q_'):
            card_id = int(key.split('_')[1])
            card = Card.query.get(card_id)
            if card:
                total += 1
                is_correct = (value == card.answer)
                if is_correct: score += 1
                results.append({'question': card.question, 'user_answer': value, 'correct_answer': card.answer, 'is_correct': is_correct, 'category': card.category})
    percent = int((score / total * 100)) if total > 0 else 0
    passed = percent >= 60
    return render_template('exam_result.html', score=score, total=total, percent=percent, passed=passed, results=results)

# --- ADMIN ROUTEN ---

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_dashboard():
    existing_categories = [c[0] for c in db.session.query(Card.category).distinct().all()]
    if request.method == 'POST':
        cat = request.form.get('category_new') or request.form.get('category_select')
        q_type = request.form['type']
        new_card = Card(category=cat, type=q_type, question=request.form['question'], answer=request.form['answer'])
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                new_card.image_url = url_for('static', filename='uploads/' + filename)
        if q_type == 'mc':
            opts_raw = request.form['options']
            opts_list = [o.strip() for o in opts_raw.split(',')]
            if new_card.answer not in opts_list: opts_list.append(new_card.answer)
            new_card.options = json.dumps(opts_list)
        db.session.add(new_card)
        db.session.commit()
        flash('Frage hinzugefügt!', 'success')
        return redirect(url_for('admin_dashboard'))
    all_cards = Card.query.order_by(Card.id.desc()).all()
    return render_template('admin.html', cards=all_cards, categories=existing_categories)

@app.route('/admin/delete/<int:card_id>', methods=['POST'])
@admin_required
def delete_card(card_id):
    card = Card.query.get_or_404(card_id)
    UserProgress.query.filter_by(card_id=card.id).delete()
    db.session.delete(card)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit/<int:card_id>', methods=['GET', 'POST'])
@admin_required
def edit_card(card_id):
    card = Card.query.get_or_404(card_id)
    existing_categories = [c[0] for c in db.session.query(Card.category).distinct().all()]
    if request.method == 'POST':
        cat_selection = request.form.get('category_select')
        cat_new = request.form.get('category_new')
        card.category = cat_new if cat_new else cat_selection
        card.question = request.form['question']
        card.answer = request.form['answer']
        card.type = request.form['type']
        if card.type == 'mc':
            opts_raw = request.form['options']
            opts_list = [o.strip() for o in opts_raw.split(',')]
            if card.answer not in opts_list: opts_list.append(card.answer)
            card.options = json.dumps(opts_list)
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                card.image_url = url_for('static', filename='uploads/' + filename)
        db.session.commit()
        return redirect(url_for('admin_dashboard'))
    options_str = ""
    if card.options:
        opts = json.loads(card.options)
        options_str = ", ".join(opts)
    return render_template('edit_card.html', card=card, categories=existing_categories, options_str=options_str)

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
                cat = row[0].strip()
                q_type = row[1].strip().lower()
                question = row[2].strip()
                answer = row[3].strip()
                new_card = Card(category=cat, type=q_type, question=question, answer=answer)
                if q_type == 'mc' and len(row) > 4:
                    opts = [o.strip() for o in row[4].split(',')]
                    if answer not in opts: opts.append(answer)
                    new_card.options = json.dumps(opts)
                db.session.add(new_card)
            db.session.commit()
            flash('Import erfolgreich!', 'success')
        except Exception as e:
            flash(f'Fehler: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    username = request.form['username']
    if User.query.filter_by(username=username).first():
        flash('User existiert bereits', 'danger')
    else:
        new_user = User(username=username, is_admin=('is_admin' in request.form))
        new_user.set_password(request.form['password'])
        db.session.add(new_user)
        db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.username != 'admin':
        UserProgress.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for('admin_users'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    app.run(host='0.0.0.0', port=5000)

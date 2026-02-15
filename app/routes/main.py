import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import or_
from ..extensions import db
from ..models import Card, UserProgress, DashboardMessage, ExamAttempt, User
from ..utils import check_gamification, build_category_tree, get_learning_stats

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    
    check_gamification(current_user)
    global_stats = get_learning_stats(current_user)
    
    # OPTIMIERT: build_category_tree lädt Daten aggregiert (blitzschnell bei 5000+ Fragen)
    tree = build_category_tree(current_user)
    
    msgs = DashboardMessage.query.filter_by(active=True).order_by(DashboardMessage.created_at.desc()).all()
    
    return render_template('index.html', tree=tree, messages=msgs, global_stats=global_stats)

@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if 'profile_image' in request.files and request.files['profile_image']:
            f = request.files['profile_image']
            if f.filename != '' and '.' in f.filename and f.filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg'}:
                target_dir = os.path.join(current_app.root_path, 'static', 'uploads')
                if not os.path.exists(target_dir): os.makedirs(target_dir, exist_ok=True)
                fn = secure_filename(f"user_{current_user.id}_{f.filename}")
                destination_path = os.path.join(target_dir, fn)
                try:
                    f.save(destination_path)
                    current_user.profile_image = url_for('static', filename='uploads/' + fn)
                except Exception as e:
                    flash(f'Fehler beim Speichern: {str(e)}', 'danger')
                    return redirect(url_for('main.profile'))
        
        if 'real_name' in request.form: current_user.real_name = request.form['real_name']
        if 'email' in request.form: current_user.email = request.form['email']
        
        if request.form.get('new_password'):
            if request.form['new_password'] == request.form.get('confirm_password'):
                current_user.set_password(request.form['new_password'])
                flash('Passwort wurde aktualisiert.', 'success')
            else:
                flash('Passwörter stimmen nicht überein.', 'danger')

        db.session.commit()
        flash('Profil erfolgreich gespeichert!', 'success')
        return redirect(url_for('main.profile'))
        
    return render_template('profile.html', attempts=ExamAttempt.query.filter_by(user_id=current_user.id).order_by(ExamAttempt.timestamp.desc()).all(), user=current_user)

@bp.route('/profile/reset_all', methods=['POST'])
@login_required
def reset_global_progress():
    UserProgress.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash('Gesamter Fortschritt wurde zurückgesetzt.', 'warning')
    return redirect(url_for('main.index'))

@bp.route('/reset/<path:category_path>', methods=['POST'])
@login_required
def reset_category(category_path):
    # Optimiert: Zieht IDs direkt über LIKE
    cids = [c.id for c in Card.query.filter(Card.category.like(f"{category_path}%")).all()]
    if cids: 
        UserProgress.query.filter(UserProgress.user_id==current_user.id, UserProgress.card_id.in_(cids)).delete(synchronize_session=False)
        db.session.commit()
    flash(f"Fortschritt für {category_path} zurückgesetzt.", "info")
    return redirect(url_for('main.index'))

@bp.route('/leaderboard')
def leaderboard(): 
    return render_template('leaderboard.html', 
                           by_xp=User.query.filter(User.username != 'admin').order_by(User.xp.desc()).limit(10).all(),
                           by_time=User.query.filter(User.username != 'admin').order_by(User.total_learning_time.desc()).limit(10).all(), 
                           by_streak=User.query.filter(User.username != 'admin').order_by(User.streak.desc()).limit(10).all())

@bp.route('/search')
def search():
    q = request.args.get('q', '')
    results = Card.query.filter(or_(Card.question.ilike(f'%{q}%'), Card.answer.ilike(f'%{q}%'))).all() if q else []
    return render_template('search.html', query=q, results=results)

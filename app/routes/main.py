import os
import json
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import or_, func
from ..extensions import db
from ..models import Card, UserProgress, DashboardMessage, ExamAttempt, User
from ..utils import check_gamification, build_category_tree, get_learning_stats

bp = Blueprint('main', __name__)

@bp.before_app_request
def update_last_active():
    if current_user.is_authenticated:
        if current_user.last_active is None or current_user.last_active < datetime.utcnow() - timedelta(minutes=5):
            current_user.last_active = datetime.utcnow()
            db.session.commit()

@bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    
    check_gamification(current_user)
    global_stats = get_learning_stats(current_user)
    
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

    total_by_cat = db.session.query(Card.category, func.count(Card.id)).group_by(Card.category).all()
    learned_by_cat = db.session.query(Card.category, func.count(Card.id))\
        .join(UserProgress, UserProgress.card_id == Card.id)\
        .filter(UserProgress.user_id == current_user.id, UserProgress.box > 0)\
        .group_by(Card.category).all()
        
    stats_map = {}
    
    for cat, count in total_by_cat:
        parts = cat.strip('/').split('/') if cat else ['Sonstiges']
        main = parts[0]
        sub = parts[1] if len(parts) > 1 else "Allgemein"
        
        if main not in stats_map: 
            stats_map[main] = {'t': 0, 'l': 0, 'subs': {}}
        
        stats_map[main]['t'] += count
        if sub not in stats_map[main]['subs']: 
            stats_map[main]['subs'][sub] = {'t': 0, 'l': 0}
        stats_map[main]['subs'][sub]['t'] += count
        
    for cat, count in learned_by_cat:
        parts = cat.strip('/').split('/') if cat else ['Sonstiges']
        main = parts[0]
        sub = parts[1] if len(parts) > 1 else "Allgemein"
        
        if main in stats_map:
            stats_map[main]['l'] += count
            if sub in stats_map[main]['subs']:
                stats_map[main]['subs'][sub]['l'] += count

    labels_lvl1 = []
    data_lvl1 = []
    for m in sorted(stats_map.keys()):
        labels_lvl1.append(m)
        data_lvl1.append(int((stats_map[m]['l'] / stats_map[m]['t']) * 100))
    
    detail_data = {}
    for m in stats_map:
        s_labels = []
        s_data = []
        for s in sorted(stats_map[m]['subs'].keys()):
            s_labels.append(s)
            s_data.append(int((stats_map[m]['subs'][s]['l'] / stats_map[m]['subs'][s]['t']) * 100))
        detail_data[m] = {'labels': s_labels, 'data': s_data}

    chart_config = {
        'main': {'labels': labels_lvl1, 'data': data_lvl1},
        'details': detail_data
    }

    return render_template('profile.html', 
                           attempts=ExamAttempt.query.filter_by(user_id=current_user.id).order_by(ExamAttempt.timestamp.desc()).all(), 
                           user=current_user,
                           chart_config=json.dumps(chart_config))

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
    cids = [c.id for c in Card.query.filter(Card.category.like(f"{category_path}%")).all()]
    if cids: 
        UserProgress.query.filter(UserProgress.user_id==current_user.id, UserProgress.card_id.in_(cids)).delete(synchronize_session=False)
        db.session.commit()
    flash(f"Fortschritt für {category_path} zurückgesetzt.", "info")
    return redirect(url_for('main.index'))

@bp.route('/leaderboard')
@login_required
def leaderboard():
    if not current_user.study_class_id:
        users = []
        class_name = "Keiner Klasse zugewiesen"
    else:
        # User der gleichen Klasse laden, sortiert nach XP (absteigend) und Lernzeit (absteigend)
        users = User.query.filter_by(study_class_id=current_user.study_class_id, is_admin=False)\
                          .order_by(User.xp.desc(), User.total_learning_time.desc())\
                          .all()
        
        org_name = current_user.study_class.organization.name
        class_name = f"{org_name} / {current_user.study_class.name}"
    
    return render_template('leaderboard.html', users=users, class_name=class_name)

@bp.route('/search')
def search():
    q = request.args.get('q', '')
    results = Card.query.filter(or_(Card.question.ilike(f'%{q}%'), Card.answer.ilike(f'%{q}%'))).all() if q else []
    return render_template('search.html', query=q, results=results)
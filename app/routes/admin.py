import os
import json
import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from functools import wraps
from sqlalchemy import or_
from ..extensions import db
from ..models import Card, User, Tag, DashboardMessage, CardReport, UserProgress

bp = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Zugriff verweigert!", "danger")
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'mp3', 'wav', 'csv'}

def build_admin_tree(cards):
    """Baut eine Baumstruktur für das Admin-Interface"""
    tree = {}
    for card in cards:
        cat_clean = card.category.strip('/')
        parts = cat_clean.split('/')
        current = tree
        path_accum = ""
        for i, part in enumerate(parts):
            path_accum += part + "/"
            if part not in current:
                current[part] = {'_path': path_accum, '_subs': {}, '_cards': []}
            if i == len(parts) - 1:
                current[part]['_cards'].append(card)
            current = current[part]['_subs']
    return tree

def handle_upload(file_obj):
    if file_obj and allowed_file(file_obj.filename):
        fn = secure_filename(file_obj.filename)
        if not os.path.exists(current_app.config['UPLOAD_FOLDER']):
            os.makedirs(current_app.config['UPLOAD_FOLDER'])
        file_obj.save(os.path.join(current_app.config['UPLOAD_FOLDER'], fn))
        return url_for('static', filename='uploads/'+fn)
    return None

@bp.route('/admin', methods=['GET','POST'])
@admin_required
def admin_dashboard():
    if request.method == 'POST':
        if 'tag_name' in request.form:
            db.session.add(Tag(name=request.form['tag_name']))
            db.session.commit()
            return redirect(url_for('admin.admin_dashboard'))
        
        if 'question' in request.form:
            cat = request.form.get('category_path') or request.form.get('category_new') or request.form.get('category_select')
            c = Card(category=cat, type=request.form['type'], question=request.form['question'])
            c.explanation = request.form.get('explanation', '')
            
            if 'image' in request.files:
                url = handle_upload(request.files['image'])
                if url: c.image_url = url
            if 'audio' in request.files:
                url = handle_upload(request.files['audio'])
                if url: c.audio_url = url
            
            c.answer = request.form.get('answer','')
            if c.type=='mc':
                opts = [x.strip() for x in request.form.get('options','').split(',')]
                if c.answer and c.answer not in opts: opts.append(c.answer)
                c.options = json.dumps(opts)
            elif c.type == 'anatomy_multi': c.options = request.form.get('multi_json')
            elif c.type == 'ordering': c.options = request.form.get('ordering_json')
            elif c.type == 'assignment': c.options = request.form.get('assignment_json')
            elif c.type == 'calculation': c.options = request.form.get('calc_json')
            
            db.session.add(c)
            db.session.commit()
            flash('Gespeichert', 'success')
            return redirect(url_for('admin.admin_dashboard'))

    all_cards = Card.query.all()
    standard_cards_raw = [c for c in all_cards if c.type not in ['calculation', 'case_study']]
    question_tree = build_admin_tree(standard_cards_raw)
    
    reports = CardReport.query.options(db.joinedload(CardReport.card))\
        .filter_by(resolved=False)\
        .order_by(CardReport.created_at.desc()).all()
    
    return render_template('admin.html', 
                           question_tree=question_tree,
                           med_cards=[c for c in all_cards if c.type == 'calculation'], 
                           case_cards=[c for c in all_cards if c.type == 'case_study'], 
                           categories=[c[0] for c in db.session.query(Card.category).distinct().all()], 
                           tags=Tag.query.all(), 
                           messages=DashboardMessage.query.all(), 
                           reports=reports)

@bp.route('/admin/bulk_delete', methods=['POST'])
@admin_required
def bulk_delete():
    ids = request.form.getlist('selected_ids')
    if not ids:
        flash('Keine Fragen ausgewählt', 'warning')
        return redirect(url_for('admin.admin_dashboard'))
    count = 0
    for cid in ids:
        c = Card.query.get(int(cid))
        if c:
            UserProgress.query.filter_by(card_id=c.id).delete()
            CardReport.query.filter_by(card_id=c.id).delete()
            db.session.delete(c)
            count += 1
    db.session.commit()
    flash(f'{count} Fragen gelöscht.', 'success')
    return redirect(url_for('admin.admin_dashboard'))

# --- NEU: KATEGORIE BEARBEITEN (UMBENENNEN / STRUKTUR ÄNDERN) ---
@bp.route('/admin/category/edit', methods=['POST'])
@admin_required
def edit_category():
    old_name = request.form.get('old_category_name', '').strip('/')
    new_name = request.form.get('new_category_name', '').strip('/')
    
    if not old_name or not new_name:
        flash('Ungültige Eingabe', 'danger')
        return redirect(url_for('admin.admin_dashboard'))
        
    if old_name == new_name:
        return redirect(url_for('admin.admin_dashboard'))

    # 1. Exakte Matches aktualisieren (Fragen direkt in dieser Kategorie)
    exact_cards = Card.query.filter(Card.category == old_name).all()
    count = 0
    for c in exact_cards:
        c.category = new_name
        count += 1
        
    # 2. Unterkategorien aktualisieren (Prefix ändern)
    # Wenn old="Anatomie", new="Körper", dann wird "Anatomie/Knochen" zu "Körper/Knochen"
    sub_cards = Card.query.filter(Card.category.like(f"{old_name}/%")).all()
    for c in sub_cards:
        # Ersetze den Start des Strings
        c.category = new_name + c.category[len(old_name):]
        count += 1
        
    db.session.commit()
    flash(f'Kategorie "{old_name}" zu "{new_name}" geändert ({count} Fragen aktualisiert).', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/category/delete', methods=['POST'])
@admin_required
def delete_category():
    cat_name = request.form.get('category_name')
    if not cat_name: return redirect(url_for('admin.admin_dashboard'))
    clean_name = cat_name.rstrip('/')
    cards = Card.query.filter(or_(Card.category == clean_name, Card.category.like(f"{clean_name}/%"))).all()
    count = 0
    for c in cards:
        UserProgress.query.filter_by(card_id=c.id).delete()
        CardReport.query.filter_by(card_id=c.id).delete()
        db.session.delete(c)
        count += 1
    db.session.commit()
    flash(f'Kategorie "{clean_name}" und {count} Fragen gelöscht.', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/delete/<int:card_id>', methods=['POST'])
@admin_required
def delete_card(card_id):
    c = Card.query.get_or_404(card_id)
    UserProgress.query.filter_by(card_id=card_id).delete()
    CardReport.query.filter_by(card_id=card_id).delete()
    db.session.delete(c)
    db.session.commit()
    flash('Gelöscht', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/edit/<int:card_id>', methods=['GET', 'POST'])
@admin_required
def edit_card(card_id):
    card = Card.query.get_or_404(card_id)
    if request.method == 'POST':
        card.category = request.form.get('category_new') or card.category
        card.question = request.form.get('question')
        card.type = request.form.get('type')
        card.answer = request.form.get('answer')
        card.answer_lat = request.form.get('answer_lat')
        card.explanation = request.form.get('explanation')
        if 'image' in request.files:
            url = handle_upload(request.files['image'])
            if url: card.image_url = url
        if 'audio' in request.files:
            url = handle_upload(request.files['audio'])
            if url: card.audio_url = url
        db.session.commit()
        flash('Gespeichert', 'success')
        return redirect(url_for('admin.admin_dashboard'))
    return render_template('edit_card.html', card=card)

@bp.route('/admin/reports/dismiss/<int:rid>', methods=['POST'])
@admin_required
def dismiss_report(rid):
    r = CardReport.query.get(rid)
    if r:
        r.resolved = True
        db.session.commit()
    return redirect(url_for('admin.admin_dashboard'))

# --- BENUTZER VERWALTUNG ---

@bp.route('/admin/users')
@admin_required
def admin_users():
    return render_template('admin_users.html', users=User.query.all())

@bp.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    is_admin = 'is_admin' in request.form
    if User.query.filter_by(username=username).first():
        flash('Benutzer existiert bereits!', 'danger')
    else:
        u = User(username=username, is_admin=is_admin)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash('Benutzer angelegt.', 'success')
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/users/edit/<int:uid>', methods=['POST'])
@admin_required
def edit_user(uid):
    u = User.query.get_or_404(uid)
    u.username = request.form.get('username')
    u.email = request.form.get('email')
    u.real_name = request.form.get('real_name')
    u.is_admin = 'is_admin' in request.form
    new_pw = request.form.get('new_password')
    if new_pw:
        u.set_password(new_pw)
    db.session.commit()
    flash('Benutzer aktualisiert.', 'success')
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/users/delete/<int:uid>', methods=['POST'])
@admin_required
def delete_user(uid):
    u = User.query.get_or_404(uid)
    if u.username == 'admin':
        flash('Der Haupt-Administrator kann nicht gelöscht werden!', 'danger')
    else:
        UserProgress.query.filter_by(user_id=u.id).delete()
        CardReport.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
        db.session.commit()
        flash('Benutzer gelöscht.', 'success')
    return redirect(url_for('admin.admin_users'))

# --- WEITERE ADMIN ROUTEN ---

@bp.route('/admin/add_med', methods=['POST'])
@admin_required
def add_med():
    cat = request.form.get('category'); drug = request.form.get('drug_name')
    config = { "var": "weight", "min": int(request.form.get('weight_min', 10)), "max": int(request.form.get('weight_max', 150)), "step": 1, "unit": request.form.get('unit', 'mg') }
    c = Card(category=cat, type='calculation', question=f"{drug} Gabe: Patient wiegt {{weight}} kg.")
    c.options = json.dumps(config)
    c.answer = request.form.get('dosage_range', '0')
    db.session.add(c); db.session.commit()
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/add_case', methods=['POST'])
@admin_required
def add_case():
    cat = request.form.get('category'); title = request.form.get('title')
    c = Card(category=cat, type='case_study', question=f"**{title}**\n\n{request.form.get('intro')}")
    c.answer = request.form.get('solution'); db.session.add(c); db.session.commit()
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/messages', methods=['POST'])
@admin_required
def add_message():
    db.session.add(DashboardMessage(content=request.form['content']))
    db.session.commit()
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/messages/delete/<int:mid>')
@admin_required
def delete_message(mid):
    DashboardMessage.query.filter_by(id=mid).delete()
    db.session.commit()
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/export')
@admin_required
def export_data():
    d={'cards':[{'q':c.question,'a':c.answer,'cat':c.category, 'type':c.type, 'opts':c.options, 'expl': c.explanation} for c in Card.query.all()]}
    return Response(json.dumps(d, indent=2), mimetype='application/json', headers={'Content-Disposition':f'attachment;filename=topp-nfs-backup.json'})

@bp.route('/admin/import', methods=['POST'])
@admin_required
def import_preview():
    if 'file' not in request.files: return redirect(url_for('admin.admin_dashboard'))
    file = request.files['file']
    try:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        csv_input = csv.reader(stream, delimiter=';')
        preview_data = []
        for row in csv_input:
            if len(row) < 4: continue
            item = {'category': row[0], 'type': row[1], 'question': row[2], 'answer': row[3], 'options': row[4] if len(row) > 4 else '', 'explanation': row[5] if len(row) > 5 else ''}
            existing = Card.query.filter_by(question=item['question']).first()
            item['is_duplicate'] = True if existing else False
            if existing: item['existing_id'] = existing.id
            preview_data.append(item)
        return render_template('admin_import_preview.html', data=preview_data, json_data=json.dumps(preview_data))
    except Exception as e:
        flash(f'Fehler: {e}','danger')
        return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/import/confirm', methods=['POST'])
@admin_required
def import_confirm():
    try:
        data = json.loads(request.form.get('json_data'))
        for i, item in enumerate(data):
            action = request.form.get(f'action_{i}', 'new')
            if item.get('is_duplicate') and action == 'skip': continue
            if item.get('is_duplicate') and action == 'overwrite':
                c = Card.query.get(item.get('existing_id'))
            else:
                c = Card(question=item['question'])
                db.session.add(c)
            c.category, c.type, c.answer, c.explanation = item['category'], item['type'], item['answer'], item.get('explanation', '')
            c.options = item.get('options')
        db.session.commit()
        flash('Import erfolgreich.', 'success')
    except Exception as e: flash(f'Import Fehler: {e}', 'danger')
    return redirect(url_for('admin.admin_dashboard'))

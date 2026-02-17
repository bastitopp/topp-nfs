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

def check_question_quality(cards):
    warnings = []
    absolutes = [' immer ', ' nie ', ' niemals ', ' ausschließlich ', ' grundsätzlich ', ' keinesfalls ']
    
    for c in cards:
        if c.type != 'mc': continue
        issues = []
        try:
            db_opts = json.loads(c.options) if c.options else []
            final_opts = list(db_opts)
            if c.answer and c.answer not in final_opts:
                final_opts.append(c.answer)
            
            if len(final_opts) != 4:
                issues.append(f"Falsche Anzahl an Antwortmöglichkeiten: {len(final_opts)} (Erwartet: 4)")

            if c.answer and final_opts:
                c_len = len(c.answer)
                distractors = [o for o in final_opts if o != c.answer]
                if distractors:
                    avg_len = sum(len(o) for o in distractors) / max(1, len(distractors))
                    if avg_len > 0:
                        # INTELLIGENTE REGEL: Toleranz von 30%, ABER Unterschied muss > 15 Zeichen sein!
                        if c_len > avg_len * 1.30 and (c_len - avg_len) > 15:
                            issues.append(f"Richtige Antwort ist auffällig LÄNGER als die falschen.")
                        elif c_len < avg_len * 0.70 and (avg_len - c_len) > 15:
                            issues.append(f"Richtige Antwort ist auffällig KÜRZER als die falschen.")

            found_absolutes = set()
            for opt in final_opts:
                opt_lower = f" {opt.lower()} " 
                for w in absolutes:
                    if w in opt_lower:
                        found_absolutes.add(w.strip())
            if found_absolutes:
                issues.append(f"Absolut-Wörter gefunden: {', '.join(found_absolutes)}")

        except Exception as e:
            issues.append("Fehlerhaftes Format in den Optionen")

        if issues:
            warnings.append({'card': c, 'issues': issues})
            
    return warnings

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
            
            if c.type == 'mc':
                opts = [x.strip() for x in request.form.getlist('mc_options') if x.strip()]
                if c.answer and c.answer not in opts: opts.append(c.answer)
                c.options = json.dumps(opts)
            elif c.type == 'anatomy_multi': 
                c.options = request.form.get('multi_json')
            elif c.type in ['ordering', 'assignment', 'calculation']: 
                c.options = request.form.get('ordering_json')
            
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
        
    quality_warnings = check_question_quality(standard_cards_raw)
    
    return render_template('admin.html', 
                           question_tree=question_tree,
                           med_cards=[c for c in all_cards if c.type == 'calculation'], 
                           case_cards=[c for c in all_cards if c.type == 'case_study'], 
                           categories=[c[0] for c in db.session.query(Card.category).distinct().all()], 
                           tags=Tag.query.all(), 
                           messages=DashboardMessage.query.all(), 
                           reports=reports,
                           quality_warnings=quality_warnings)

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

    exact_cards = Card.query.filter(Card.category == old_name).all()
    count = 0
    for c in exact_cards:
        c.category = new_name
        count += 1
        
    sub_cards = Card.query.filter(Card.category.like(f"{old_name}/%")).all()
    for c in sub_cards:
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
        
        if card.type == 'mc':
            opts = [x.strip() for x in request.form.getlist('mc_options') if x.strip()]
            if card.answer and card.answer not in opts: opts.append(card.answer)
            card.options = json.dumps(opts)
        elif card.type == 'anatomy_multi': 
            card.options = request.form.get('multi_json')
        elif card.type in ['ordering', 'assignment', 'calculation']: 
            card.options = request.form.get('ordering_json')

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
        u = User(username=username, is_admin=is_admin, is_approved=True)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash('Benutzer angelegt.', 'success')
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/users/approve/<int:uid>', methods=['POST'])
@admin_required
def approve_user(uid):
    u = User.query.get_or_404(uid)
    u.is_approved = True
    db.session.commit()
    
    try:
        if u.email:
            from ..extensions import mail
            from flask_mail import Message
            msg = Message('Dein Account bei Topp-NFS wurde freigeschaltet!', recipients=[u.email])
            msg.body = f'Hallo {u.real_name or u.username},\n\ndein Account wurde soeben durch einen Administrator freigeschaltet.\nDu kannst dich ab sofort unter folgendem Link einloggen:\n{url_for("auth.login", _external=True)}'
            mail.send(msg)
    except Exception as e:
        print(f"Fehler beim Senden der Bestätigungsmail an Nutzer: {e}")
        
    flash(f'Benutzer {u.username} wurde erfolgreich freigeschaltet!', 'success')
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
            
            if c.type == 'mc' and item.get('options'):
                raw_opts = item.get('options')
                try:
                    json.loads(raw_opts)
                    c.options = raw_opts
                except:
                    opts_list = [x.strip() for x in raw_opts.split(',') if x.strip()]
                    c.options = json.dumps(opts_list)
            else:
                c.options = item.get('options')

        db.session.commit()
        flash('Import erfolgreich.', 'success')
    except Exception as e: flash(f'Import Fehler: {e}', 'danger')
    return redirect(url_for('admin.admin_dashboard'))

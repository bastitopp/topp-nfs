import os
import json
import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from functools import wraps
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
                f = request.files['image']
                if f and allowed_file(f.filename):
                    fn = secure_filename(f.filename)
                    if not os.path.exists(current_app.config['UPLOAD_FOLDER']):
                        os.makedirs(current_app.config['UPLOAD_FOLDER'])
                    f.save(os.path.join(current_app.config['UPLOAD_FOLDER'], fn))
                    c.image_url = url_for('static', filename='uploads/'+fn)
            
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
    med_cards = [c for c in all_cards if c.type == 'calculation']
    case_cards = [c for c in all_cards if c.type == 'case_study']
    standard_cards_raw = [c for c in all_cards if c.type not in ['calculation', 'case_study']]
    
    grouped_cards = {}
    for c in standard_cards_raw:
        if c.category not in grouped_cards: grouped_cards[c.category] = []
        grouped_cards[c.category].append(c)
    
    sorted_categories = sorted(grouped_cards.keys())
    reports = CardReport.query.filter_by(resolved=False).order_by(CardReport.created_at.desc()).all()
    categories_list = [c[0] for c in db.session.query(Card.category).distinct().all()]
    
    return render_template('admin.html', grouped_cards=grouped_cards, sorted_categories=sorted_categories, med_cards=med_cards, case_cards=case_cards, categories=categories_list, tags=Tag.query.all(), messages=DashboardMessage.query.all(), reports=reports)

@bp.route('/admin/category/delete', methods=['POST'])
@admin_required
def delete_category():
    cat_name = request.form.get('category_name')
    if not cat_name: return redirect(url_for('admin.admin_dashboard'))
    cards = Card.query.filter_by(category=cat_name).all()
    for c in cards:
        UserProgress.query.filter_by(card_id=c.id).delete()
        db.session.delete(c)
    db.session.commit()
    flash(f'Kategorie "{cat_name}" gelöscht.', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/add_med', methods=['POST'])
@admin_required
def add_med():
    cat = request.form.get('category'); drug = request.form.get('drug_name')
    config = { "var": "weight", "min": int(request.form.get('weight_min')), "max": int(request.form.get('weight_max')), "step": int(request.form.get('weight_step')), "unit": request.form.get('unit') }
    question = f"{drug} Gabe: Patient wiegt {{weight}} kg."
    c = Card(category=cat, type='calculation', question=question)
    c.options = json.dumps(config)
    c.answer = request.form.get('dosage_range')
    db.session.add(c)
    db.session.commit()
    flash(f'Medikament {drug} angelegt.', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/add_case', methods=['POST'])
@admin_required
def add_case():
    cat = request.form.get('category'); title = request.form.get('title'); intro = request.form.get('intro'); solution = request.form.get('solution')
    c = Card(category=cat, type='case_study', question=f"**{title}**\n\n{intro}")
    c.answer = f"### Lösung & Maßnahmen\n{solution}"
    db.session.add(c)
    db.session.commit()
    flash('Fallbeispiel angelegt.', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/users')
@admin_required
def admin_users():
    return render_template('admin_users.html', users=User.query.all())

@bp.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    if User.query.filter_by(username=request.form['username']).first():
        flash('Existiert','danger')
    else:
        u=User(username=request.form['username'], is_admin='is_admin' in request.form)
        u.set_password(request.form['password'])
        db.session.add(u)
        db.session.commit()
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/users/edit/<int:uid>', methods=['POST'])
@admin_required
def edit_user(uid):
    u = User.query.get_or_404(uid)
    u.username = request.form.get('username')
    u.real_name = request.form.get('real_name')
    u.email = request.form.get('email')
    u.is_admin = 'is_admin' in request.form
    if request.form.get('new_password'):
        u.set_password(request.form.get('new_password'))
    db.session.commit()
    flash('Gespeichert.', 'success')
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/users/delete/<int:uid>', methods=['POST'])
@admin_required
def delete_user(uid):
    u=User.query.get(uid)
    if u and u.username!='admin':
        db.session.delete(u)
        db.session.commit()
    return redirect(url_for('admin.admin_users'))

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

@bp.route('/admin/reports/dismiss/<int:rid>', methods=['POST'])
@admin_required
def dismiss_report(rid):
    r = CardReport.query.get(rid)
    if r:
        r.resolved=True
        db.session.commit()
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/delete/<int:card_id>', methods=['POST'])
@admin_required
def delete_card(card_id):
    c = Card.query.get_or_404(card_id)
    UserProgress.query.filter_by(card_id=card_id).delete()
    db.session.delete(c)
    db.session.commit()
    flash('Gelöscht', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/edit/<int:card_id>', methods=['GET', 'POST'])
@admin_required
def edit_card(card_id):
    card = Card.query.get_or_404(card_id)
    options_str = ''
    if card.type == 'mc' and card.options:
        try:
            opts_list = json.loads(card.options)
            if isinstance(opts_list, list): options_str = ", ".join(opts_list)
            else: options_str = str(card.options)
        except: options_str = card.options

    if request.method == 'POST':
        card.category = request.form.get('category_new')
        card.question = request.form.get('question')
        card.type = request.form.get('type')
        card.answer = request.form.get('answer')
        card.answer_lat = request.form.get('answer_lat')
        card.explanation = request.form.get('explanation')

        new_tags = request.form.get('tags_input', '')
        card.tags = [] 
        for t_name in new_tags.split(','):
            if t_name.strip():
                tag = Tag.query.filter_by(name=t_name.strip()).first()
                if not tag:
                    tag = Tag(name=t_name.strip())
                    db.session.add(tag)
                card.tags.append(tag)
        if 'image' in request.files:
            f = request.files['image']
            if f and allowed_file(f.filename):
                fn = secure_filename(f.filename)
                f.save(os.path.join(current_app.config['UPLOAD_FOLDER'], fn))
                card.image_url = url_for('static', filename='uploads/'+fn)
        if card.type == 'mc': 
            opts_raw = request.form.get('options')
            if opts_raw:
                opts = [x.strip() for x in opts_raw.split(',')]
                if card.answer and card.answer not in opts: opts.append(card.answer)
                card.options = json.dumps(opts)
            else: card.options = '[]'
        elif card.type == 'anatomy_multi': card.options = request.form.get('multi_json')
        elif card.type == 'ordering': card.options = request.form.get('ordering_json')
        elif card.type == 'assignment': card.options = request.form.get('assignment_json')
        elif card.type == 'calculation': card.options = request.form.get('calc_json')
        
        db.session.commit()
        flash('Gespeichert', 'success')
        return redirect(url_for('admin.admin_dashboard'))
    return render_template('edit_card.html', card=card, options_str=options_str, multi_json=card.options if card.type=='anatomy_multi' else '[]', ordering_json=card.options if card.type=='ordering' else '[]', assignment_json=card.options if card.type=='assignment' else '[]')

@bp.route('/admin/import', methods=['POST'])
@admin_required
def import_preview():
    if 'file' not in request.files:
        flash('Kein File','danger')
        return redirect(url_for('admin.admin_dashboard'))
    file = request.files['file']
    try:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        csv_input = csv.reader(stream, delimiter=';')
        preview_data = []
        for row in csv_input:
            if len(row) < 4: continue
            item = {'category': row[0], 'type': row[1], 'question': row[2], 'answer': row[3]}
            if len(row) > 4: item['options'] = row[4]
            # NEU: Erklärung einlesen (Spalte 6)
            if len(row) > 5: item['explanation'] = row[5]
            else: item['explanation'] = ''
            
            existing = Card.query.filter_by(question=item['question']).first()
            if existing:
                item['is_duplicate'] = True
                item['existing_id'] = existing.id
            else:
                item['is_duplicate'] = False
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
        count_new = 0
        count_overwritten = 0
        count_skipped = 0
        for i, item in enumerate(data):
            action = request.form.get(f'action_{i}', 'new')
            if item.get('is_duplicate') and action == 'skip':
                count_skipped += 1
                continue
            
            # Helper für Optionen
            final_options = None
            if 'options' in item and item['options']:
                if item['type'] == 'mc':
                    opts = [x.strip() for x in item['options'].split(',')]
                    if item['answer'] and item['answer'] not in opts: opts.append(item['answer'])
                    final_options = json.dumps(opts)
                else: final_options = item['options']

            if item.get('is_duplicate') and action == 'overwrite':
                c = Card.query.get(item.get('existing_id'))
                if c:
                    c.category = item['category']
                    c.type = item['type']
                    c.answer = item['answer']
                    c.explanation = item.get('explanation', '') # Update explanation
                    if final_options: c.options = final_options
                    count_overwritten += 1
                    continue
            
            # Neu anlegen
            c = Card(category=item['category'], type=item['type'], question=item['question'], answer=item['answer'])
            c.explanation = item.get('explanation', '') # Insert explanation
            if final_options: c.options = final_options
            db.session.add(c)
            count_new += 1
            
        db.session.commit()
        flash(f'Import abgeschlossen: {count_new} neu, {count_overwritten} überschrieben, {count_skipped} übersprungen.', 'success')
    except Exception as e: flash(f'Import Fehler: {e}', 'danger')
    return redirect(url_for('admin.admin_dashboard'))

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
            UserProgress.query.filter_by(card_id=cid).delete()
            db.session.delete(c)
            count += 1
    db.session.commit()
    flash(f'{count} Fragen gelöscht.', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@bp.route('/admin/export')
@admin_required
def export_data():
    # NEU: Erklärung exportieren
    d={'cards':[{'q':c.question,'a':c.answer,'cat':c.category, 'type':c.type, 'opts':c.options, 'expl': c.explanation} for c in Card.query.all()]}
    return Response(json.dumps(d, indent=2), mimetype='application/json', headers={'Content-Disposition':f'attachment;filename=topp-nfs-backup.json'})

import os
import json
import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, make_response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import func
from ..extensions import db
from ..models import Card, User, CardReport, DashboardMessage, UserProgress

bp = Blueprint('admin', __name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'csv'}

# Haupt-Dashboard Route
@bp.route('/admin', methods=['GET', 'POST'])
@login_required
def index():
    if not current_user.is_admin:
        flash("Zugriff verweigert.", "danger")
        return redirect(url_for('main.index'))

    # Neue Frage erstellen
    if request.method == 'POST':
        try:
            cat = request.form.get('category_path')
            ctype = request.form.get('type')
            quest = request.form.get('question')
            expl = request.form.get('explanation')
            
            # Bild Upload
            img_file = request.files.get('image')
            img_filename = None
            if img_file and img_file.filename:
                fname = secure_filename(img_file.filename)
                fname = f"{int(datetime.utcnow().timestamp())}_{fname}"
                path = os.path.join(current_app.root_path, 'static/uploads', fname)
                img_file.save(path)
                img_filename = fname

            card = Card(category=cat, type=ctype, question=quest, explanation=expl, image_url=img_filename)

            if ctype == 'mc':
                card.answer = request.form.get('answer')
                card.options = request.form.get('options')
            elif ctype == 'anatomy':
                card.answer = request.form.get('answer_de_field')
                card.answer_lat = request.form.get('answer_lat')
            elif ctype == 'anatomy_multi':
                card.options = request.form.get('multi_json')
            elif ctype in ['ordering', 'assignment']:
                card.options = request.form.get('ordering_json')
            else: # flashcard
                card.answer = request.form.get('answer')

            db.session.add(card)
            db.session.commit()
            flash('Frage erfolgreich erstellt!', 'success')
            return redirect(url_for('admin.index'))

        except Exception as e:
            flash(f"Fehler beim Erstellen: {e}", "danger")

    # Daten laden
    reports = CardReport.query.options(db.joinedload(CardReport.card), db.joinedload(CardReport.user)).order_by(CardReport.created_at.desc()).all()
    messages = DashboardMessage.query.order_by(DashboardMessage.created_at.desc()).all()
    
    cats = db.session.query(Card.category).distinct().order_by(Card.category).all()
    categories = [c[0] for c in cats]

    all_cards = Card.query.order_by(Card.category, Card.id).all()
    grouped_cards = {}
    for c in all_cards:
        if c.category not in grouped_cards: grouped_cards[c.category] = []
        grouped_cards[c.category].append(c)
    
    sorted_categories = sorted(grouped_cards.keys())

    med_cards = [c for c in all_cards if c.category.startswith('Medikamente')]
    case_cards = [c for c in all_cards if c.category.startswith('Fallbeispiele')]

    return render_template('admin.html', 
                           reports=reports, 
                           messages=messages, 
                           categories=categories,
                           grouped_cards=grouped_cards,
                           sorted_categories=sorted_categories,
                           med_cards=med_cards,
                           case_cards=case_cards)

# Alias für Links die noch auf admin_dashboard zeigen
@bp.route('/admin/dashboard')
@login_required
def admin_dashboard():
    return redirect(url_for('admin.index'))

@bp.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@bp.route('/admin/users/add', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    try:
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = request.form.get('is_admin') == 'on'
        
        if User.query.filter_by(username=username).first():
            flash('Benutzername existiert bereits.', 'warning')
        else:
            u = User(username=username, is_admin=is_admin)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash(f'Benutzer {username} angelegt.', 'success')
    except Exception as e:
        flash(f'Fehler: {e}', 'danger')
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/users/edit/<int:uid>', methods=['POST'])
@login_required
def edit_user(uid):
    if not current_user.is_admin: return redirect(url_for('main.index'))
    u = User.query.get_or_404(uid)
    try:
        u.username = request.form.get('username')
        u.email = request.form.get('email')
        u.real_name = request.form.get('real_name')
        u.is_admin = request.form.get('is_admin') == 'on'
        
        pw = request.form.get('new_password')
        if pw: u.set_password(pw)
        
        db.session.commit()
        flash(f'Benutzer {u.username} aktualisiert.', 'success')
    except Exception as e:
        flash(f'Fehler: {e}', 'danger')
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/users/delete/<int:uid>', methods=['POST'])
@login_required
def delete_user(uid):
    if not current_user.is_admin: return redirect(url_for('main.index'))
    u = User.query.get_or_404(uid)
    if u.username == 'admin':
        flash('Der Admin-User kann nicht gelöscht werden.', 'danger')
    else:
        UserProgress.query.filter_by(user_id=u.id).delete()
        CardReport.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
        db.session.commit()
        flash('Benutzer gelöscht.', 'success')
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/card/delete/<int:card_id>', methods=['POST'])
@login_required
def delete_card(card_id):
    if not current_user.is_admin: return redirect(url_for('main.index'))
    c = Card.query.get_or_404(card_id)
    CardReport.query.filter_by(card_id=card_id).delete()
    UserProgress.query.filter_by(card_id=card_id).delete()
    db.session.delete(c)
    db.session.commit()
    flash('Frage gelöscht.', 'success')
    return redirect(url_for('admin.index'))

@bp.route('/admin/bulk_delete', methods=['POST'])
@login_required
def bulk_delete():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    ids = request.form.getlist('selected_ids')
    if ids:
        count = 0
        for cid in ids:
            c = Card.query.get(cid)
            if c:
                CardReport.query.filter_by(card_id=c.id).delete()
                UserProgress.query.filter_by(card_id=c.id).delete()
                db.session.delete(c)
                count += 1
        db.session.commit()
        flash(f"{count} Fragen gelöscht.", "success")
    return redirect(url_for('admin.index'))

@bp.route('/admin/category/delete', methods=['POST'])
@login_required
def delete_category():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    cat = request.form.get('category_name')
    if cat:
        cards = Card.query.filter(Card.category == cat).all()
        for c in cards:
            CardReport.query.filter_by(card_id=c.id).delete()
            UserProgress.query.filter_by(card_id=c.id).delete()
            db.session.delete(c)
        db.session.commit()
        flash(f"Kategorie '{cat}' und {len(cards)} Fragen gelöscht.", "success")
    return redirect(url_for('admin.index'))

@bp.route('/admin/report/dismiss/<int:rid>', methods=['POST'])
@login_required
def dismiss_report(rid):
    if not current_user.is_admin: return redirect(url_for('main.index'))
    r = CardReport.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    flash('Meldung entfernt.', 'success')
    return redirect(url_for('admin.index'))

@bp.route('/admin/card/edit/<int:card_id>', methods=['GET', 'POST'])
@login_required
def edit_card(card_id):
    if not current_user.is_admin: return redirect(url_for('main.index'))
    card = Card.query.get_or_404(card_id)
    
    if request.method == 'POST':
        card.category = request.form.get('category')
        card.question = request.form.get('question')
        card.explanation = request.form.get('explanation')
        card.answer = request.form.get('answer')
        
        # Options Handling beim Editieren (Form ist CSV String)
        if card.type == 'mc':
            opts_raw = request.form.get('options')
            if opts_raw:
                opts = [x.strip() for x in opts_raw.split(',')]
                if card.answer and card.answer not in opts: opts.append(card.answer)
                card.options = json.dumps(opts)
        else:
            card.options = request.form.get('options')

        if request.form.get('answer_lat'):
            card.answer_lat = request.form.get('answer_lat')
        
        db.session.commit()
        flash('Änderungen gespeichert.', 'success')
        return redirect(url_for('admin.index'))
        
    return render_template('edit_card.html', card=card)

@bp.route('/admin/message/add', methods=['POST'])
@login_required
def add_message():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    c = request.form.get('content')
    if c:
        db.session.add(DashboardMessage(content=c))
        db.session.commit()
    return redirect(url_for('admin.index'))

@bp.route('/admin/message/delete/<int:mid>')
@login_required
def delete_message(mid):
    if not current_user.is_admin: return redirect(url_for('main.index'))
    m = DashboardMessage.query.get(mid)
    if m:
        db.session.delete(m)
        db.session.commit()
    return redirect(url_for('admin.index'))

@bp.route('/admin/med/add', methods=['POST'])
@login_required
def add_med():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    try:
        cat = request.form.get('category')
        name = request.form.get('drug_name')
        w_min = float(request.form.get('weight_min'))
        w_max = float(request.form.get('weight_max'))
        step = float(request.form.get('weight_step'))
        unit = request.form.get('unit')
        dosage = request.form.get('dosage_range')
        
        opts = {'min': w_min, 'max': w_max, 'step': step, 'unit': unit}
        
        c = Card(category=cat, type='calculation', 
                 question=f"Berechne die Dosis für {name} bei {{weight}} kg KG.",
                 answer=dosage,
                 options=json.dumps(opts),
                 explanation=f"Dosierung: {dosage} {unit}/kg")
        db.session.add(c)
        db.session.commit()
        flash(f"Medikament {name} angelegt.", "success")
    except Exception as e:
        flash(f"Fehler: {e}", "danger")
    return redirect(url_for('admin.index'))

@bp.route('/admin/case/add', methods=['POST'])
@login_required
def add_case():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    try:
        cat = request.form.get('category')
        title = request.form.get('title')
        intro = request.form.get('intro')
        sol = request.form.get('solution')
        
        c = Card(category=cat, type='flashcard', 
                 question=f"**{title}**\n\n{intro}",
                 answer="Lösung anzeigen", 
                 explanation=sol)
        db.session.add(c)
        db.session.commit()
        flash("Fallbeispiel angelegt.", "success")
    except Exception as e:
        flash(f"Fehler: {e}", "danger")
    return redirect(url_for('admin.index'))

@bp.route('/admin/export')
@login_required
def export_data():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    
    si = io.StringIO()
    cw = csv.writer(si, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    cw.writerow(['Kategorie', 'Typ', 'Frage', 'Antwort', 'Optionen', 'Erklärung'])
    
    cards = Card.query.order_by(Card.category, Card.id).all()
    for c in cards:
        cw.writerow([
            c.category,
            c.type,
            c.question,
            c.answer if c.answer else '',
            c.options if c.options else '',
            c.explanation if c.explanation else ''
        ])
        
    output = make_response(si.getvalue().encode('utf-8-sig'))
    output.headers["Content-Disposition"] = "attachment; filename=fragen_export.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8-sig"
    return output

@bp.route('/admin/import/preview', methods=['POST'])
@login_required
def import_preview():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    f = request.files.get('file')
    if not f or not allowed_file(f.filename):
        flash("Ungültige Datei.", "danger")
        return redirect(url_for('admin.index'))
    
    try:
        stream = io.StringIO(f.stream.read().decode("utf-8-sig"), newline=None)
        csv_input = csv.reader(stream, delimiter=';')
        
        preview_data = []
        header = next(csv_input, None)
        
        for row in csv_input:
            if len(row) >= 4:
                preview_data.append({
                    'category': row[0],
                    'type': row[1],
                    'question': row[2],
                    'answer': row[3],
                    'options': row[4] if len(row) > 4 else '',
                    'explanation': row[5] if len(row) > 5 else ''
                })
        
        return render_template('admin_import_preview.html', data=preview_data)
    except Exception as e:
        flash(f"Import Fehler: {e}", "danger")
        return redirect(url_for('admin.index'))

@bp.route('/admin/import/commit', methods=['POST'])
@login_required
def import_commit():
    if not current_user.is_admin: return redirect(url_for('main.index'))
    try:
        data = json.loads(request.form.get('import_data', '[]'))
        count = 0
        for item in data:
            # Normalisieren des Typs (mc, MC, Mc -> mc)
            ctype = item['type'].strip().lower()
            
            final_options = None
            if 'options' in item and item['options']:
                raw_opts = item['options'].strip()
                
                if ctype == 'mc':
                    # Logik für MC Optionen
                    # 1. Check ob es ein JSON String vom Export ist (fängt mit [ an)
                    if raw_opts.startswith('[') and raw_opts.endswith(']'):
                         final_options = raw_opts
                         # Sicherheitshalber validieren, dass es valides JSON ist
                         try:
                             json.loads(raw_opts)
                         except:
                             # Falls kaputt, doch als String behandeln? Eher Fallback.
                             pass
                    
                    # 2. Sonst normale Komma-Liste (Manueller Import)
                    else:
                        opts = [x.strip() for x in raw_opts.split(',')]
                        # Antwort hinzufügen falls fehlt
                        if item['answer'] and item['answer'] not in opts: 
                            opts.append(item['answer'])
                        final_options = json.dumps(opts)
                else: 
                    final_options = raw_opts

            c = Card(
                category=item['category'],
                type=ctype, # Wichtig: Normalisierten Typ verwenden
                question=item['question'],
                answer=item['answer'],
                options=final_options,
                explanation=item['explanation']
            )
            db.session.add(c)
            count += 1
        db.session.commit()
        flash(f"{count} Fragen importiert.", "success")
    except Exception as e:
        flash(f"Speicherfehler: {e}", "danger")
    return redirect(url_for('admin.index'))

import os
import json
import csv
import io
import html as pyhtml
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from functools import wraps
from sqlalchemy import or_
from flask_mail import Message
from ..extensions import db, mail
from ..models import Card, User, Tag, DashboardMessage, CardReport, UserProgress, Scenario, ScenarioNode, ScenarioChoice, ChoiceOutcome, UserScenarioSession

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

def build_admin_tree():
    stats = db.session.query(
        Card.category,
        db.func.count(Card.id)
    ).filter(
        ~Card.type.in_(['calculation', 'case_study'])
    ).group_by(Card.category).all()
    
    tree = {}
    for cat, count in stats:
        if not cat: continue
        cat_clean = cat.strip('/')
        parts = cat_clean.split('/')
        current = tree
        path_accum = ""
        for i, part in enumerate(parts):
            path_accum += part + "/"
            if part not in current:
                current[part] = {'_path': path_accum, '_subs': {}, 'card_count': 0}
            if i == len(parts) - 1:
                current[part]['card_count'] += count
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

@bp.route('/admin/api/cards')
@admin_required
def admin_api_cards():
    cat = request.args.get('category')
    q = request.args.get('q')
    
    query = Card.query.filter(~Card.type.in_(['calculation', 'case_study']))
    
    if cat:
        query = query.filter_by(category=cat.rstrip('/'))
    if q:
        query = query.filter(Card.question.ilike(f'%{q}%'))
        
    cards = query.limit(100).all() 
    
    html = ""
    for c in cards:
        edit_url = url_for('admin.edit_card', card_id=c.id, next=url_for('admin.admin_dashboard', tab='questions'))
        del_url = url_for('admin.delete_card', card_id=c.id)
        ctype = c.type or 'unbekannt'
        q_safe = pyhtml.escape(c.question)
        
        html += f"""
        <tr>
            <td style="width: 30px;"><input type="checkbox" name="selected_ids" value="{c.id}" class="form-check-input"></td>
            <td style="width: 60px;"><small class="badge bg-light text-dark border">{ctype}</small></td>
            <td class="text-truncate" style="max-width: 300px;">{q_safe}</td>
            <td class="text-end" style="width: 100px;">
                <a href="{edit_url}" class="btn btn-sm btn-link text-primary p-0 me-2"><i class="bi bi-pencil-fill"></i></a>
                <button type="submit" formaction="{del_url}" class="btn btn-sm btn-link text-danger p-0" onclick="return confirm('Löschen?');"><i class="bi bi-trash-fill"></i></button>
            </td>
        </tr>
        """
    
    if not cards:
        html = '<tr><td colspan="4" class="text-muted text-center py-3">Keine Fragen gefunden</td></tr>'
        
    return Response(html, mimetype='text/html')

@bp.route('/admin', methods=['GET','POST'])
@admin_required
def admin_dashboard():
    tab = request.args.get('tab', 'questions')

    if request.method == 'POST':
        if 'tag_name' in request.form:
            db.session.add(Tag(name=request.form['tag_name']))
            db.session.commit()
            return redirect(url_for('admin.admin_dashboard', tab=tab))
        
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
            
            if c.type == 'anatomy':
                if request.form.get('answer_de_field'):
                    c.answer = request.form.get('answer_de_field')
                else:
                    c.answer = request.form.get('answer', '')
                c.answer_lat = request.form.get('answer_lat', '')
            else:
                c.answer = request.form.get('answer','')
            
            if c.type == 'mc':
                opts = [x.strip() for x in request.form.getlist('mc_options') if x.strip()]
                if c.answer and c.answer not in opts: opts.append(c.answer)
                c.options = json.dumps(opts)
            elif c.type == 'anatomy_multi': 
                c.options = request.form.get('multi_json') or '[]'
            elif c.type in ['ordering', 'assignment', 'calculation']: 
                c.options = request.form.get('ordering_json')
            
            db.session.add(c)
            db.session.commit()
            flash('Gespeichert', 'success')
            return redirect(url_for('admin.admin_dashboard', tab='questions'))

    reports_count = CardReport.query.filter_by(resolved=False).count()
    
    question_tree = {}
    quality_warnings = []
    med_cards = []
    case_cards = []
    categories = []
    tags = []
    messages = []
    reports = []
    scenarios = []

    if tab == 'questions':
        question_tree = build_admin_tree()
        categories = [c[0] for c in db.session.query(Card.category).distinct().all() if c[0]]
        tags = Tag.query.all()
    elif tab == 'quality':
        all_cards = Card.query.all()
        standard_cards_raw = [c for c in all_cards if c.type not in ['calculation', 'case_study']]
        quality_warnings = check_question_quality(standard_cards_raw)
    elif tab == 'bpr':
        scenarios = Scenario.query.all()
    elif tab == 'meds':
        med_cards = Card.query.filter_by(type='calculation').all()
    elif tab == 'cases':
        case_cards = Card.query.filter_by(type='case_study').all()
    elif tab == 'reports':
        reports = CardReport.query.options(db.joinedload(CardReport.card)).filter_by(resolved=False).order_by(CardReport.created_at.desc()).all()
    elif tab == 'messages':
        messages = DashboardMessage.query.all()

    return render_template('admin.html', 
                           tab=tab,
                           reports_count=reports_count,
                           question_tree=question_tree,
                           med_cards=med_cards, 
                           case_cards=case_cards, 
                           categories=categories, 
                           tags=tags, 
                           messages=messages, 
                           reports=reports,
                           quality_warnings=quality_warnings,
                           scenarios=scenarios)

@bp.route('/admin/bulk_delete', methods=['POST'])
@admin_required
def bulk_delete():
    ids = request.form.getlist('selected_ids')
    if not ids:
        flash('Keine Fragen ausgewählt', 'warning')
        return redirect(url_for('admin.admin_dashboard', tab='questions'))
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
    return redirect(url_for('admin.admin_dashboard', tab='questions'))

@bp.route('/admin/category/edit', methods=['POST'])
@admin_required
def edit_category():
    old_name = request.form.get('old_category_name', '').strip('/')
    new_name = request.form.get('new_category_name', '').strip('/')
    
    if not old_name or not new_name:
        flash('Ungültige Eingabe', 'danger')
        return redirect(url_for('admin.admin_dashboard', tab='questions'))
        
    if old_name == new_name:
        return redirect(url_for('admin.admin_dashboard', tab='questions'))

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
    return redirect(url_for('admin.admin_dashboard', tab='questions'))

@bp.route('/admin/category/delete', methods=['POST'])
@admin_required
def delete_category():
    cat_name = request.form.get('category_name')
    if not cat_name: return redirect(url_for('admin.admin_dashboard', tab='questions'))
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
    return redirect(url_for('admin.admin_dashboard', tab='questions'))

@bp.route('/admin/delete/<int:card_id>', methods=['POST'])
@admin_required
def delete_card(card_id):
    c = Card.query.get_or_404(card_id)
    ctype = c.type
    UserProgress.query.filter_by(card_id=card_id).delete()
    CardReport.query.filter_by(card_id=card_id).delete()
    db.session.delete(c)
    db.session.commit()
    flash('Gelöscht', 'success')
    
    tab = 'questions'
    if ctype == 'calculation': tab = 'meds'
    elif ctype == 'case_study': tab = 'cases'
    return redirect(url_for('admin.admin_dashboard', tab=tab))

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
            card.options = request.form.get('multi_json') or '[]'
        elif card.type in ['ordering', 'assignment', 'calculation']: 
            card.options = request.form.get('ordering_json')

        if 'image' in request.files:
            url = handle_upload(request.files['image'])
            if url: card.image_url = url
        if 'audio' in request.files:
            url = handle_upload(request.files['audio'])
            if url: card.audio_url = url
            
        reports = CardReport.query.filter_by(card_id=card.id, resolved=False).all()
        for r in reports:
            db.session.delete(r)
            
        db.session.commit()
        flash('Gespeichert und offene Meldungen automatisch geschlossen!', 'success')
        
        next_url = request.form.get('next')
        if next_url:
            return redirect(next_url)
            
        tab = 'questions'
        if card.type == 'calculation': tab = 'meds'
        elif card.type == 'case_study': tab = 'cases'
        return redirect(url_for('admin.admin_dashboard', tab=tab))
    
    next_url = request.args.get('next')
    return render_template('edit_card.html', card=card, next_url=next_url)

@bp.route('/admin/reports/dismiss/<int:rid>', methods=['POST'])
@admin_required
def dismiss_report(rid):
    r = CardReport.query.get(rid)
    if r:
        r.resolved = True
        db.session.commit()
    return redirect(url_for('admin.admin_dashboard', tab='reports'))

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
    
    if u.email:
        try:
            msg = Message('Dein Account wurde freigeschaltet', recipients=[u.email])
            msg.body = f'Hallo {u.username},\n\ndein Account wurde soeben von einem Administrator freigeschaltet.\nDu kannst dich nun einloggen:\n{url_for("auth.login", _external=True)}'
            mail.send(msg)
        except Exception as e:
            print(f"Fehler beim Senden der Bestätigungsmail an {u.email}: {e}")
            flash(f'Benutzer {u.username} freigeschaltet, aber E-Mail konnte nicht gesendet werden.', 'warning')
            return redirect(url_for('admin.admin_users'))

    flash(f'Benutzer {u.username} wurde erfolgreich freigeschaltet und benachrichtigt!', 'success')
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
    return redirect(url_for('admin.admin_dashboard', tab='meds'))

@bp.route('/admin/add_case', methods=['POST'])
@admin_required
def add_case():
    cat = request.form.get('category'); title = request.form.get('title')
    c = Card(category=cat, type='case_study', question=f"**{title}**\n\n{request.form.get('intro')}")
    c.answer = request.form.get('solution'); db.session.add(c); db.session.commit()
    return redirect(url_for('admin.admin_dashboard', tab='cases'))

@bp.route('/admin/messages', methods=['POST'])
@admin_required
def add_message():
    db.session.add(DashboardMessage(content=request.form['content']))
    db.session.commit()
    return redirect(url_for('admin.admin_dashboard', tab='messages'))

@bp.route('/admin/messages/delete/<int:mid>')
@admin_required
def delete_message(mid):
    DashboardMessage.query.filter_by(id=mid).delete()
    db.session.commit()
    return redirect(url_for('admin.admin_dashboard', tab='messages'))

@bp.route('/admin/export')
@admin_required
def export_data():
    d={'cards':[{'q':c.question,'a':c.answer,'cat':c.category, 'type':c.type, 'opts':c.options, 'expl': c.explanation} for c in Card.query.all()]}
    return Response(json.dumps(d, indent=2), mimetype='application/json', headers={'Content-Disposition':f'attachment;filename=topp-nfs-backup.json'})

@bp.route('/admin/import', methods=['POST'])
@admin_required
def import_preview():
    if 'file' not in request.files: return redirect(url_for('admin.admin_dashboard', tab='io'))
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
        return redirect(url_for('admin.admin_dashboard', tab='io'))

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
    return redirect(url_for('admin.admin_dashboard', tab='io'))

@bp.route('/admin/bpr/add', methods=['POST'])
@admin_required
def add_bpr_scenario():
    title = request.form.get('title')
    dispatch = request.form.get('dispatch_text')
    category = request.form.get('category', 'Allgemein') # NEU
    
    s = Scenario(title=title, dispatch_text=dispatch, category=category)
    db.session.add(s)
    db.session.commit()
    
    flash('Neues Szenario erstellt. Du kannst jetzt Knotenpunkte hinzufügen.', 'success')
    return redirect(url_for('admin.edit_bpr_scenario', scenario_id=s.id))

@bp.route('/admin/bpr/edit/<int:scenario_id>', methods=['GET'])
@admin_required
def edit_bpr_scenario(scenario_id):
    scenario = Scenario.query.get_or_404(scenario_id)
    return render_template('admin_bpr_editor.html', scenario=scenario)

@bp.route('/admin/bpr/set_start/<int:scenario_id>', methods=['POST'])
@admin_required
def set_bpr_start(scenario_id):
    s = Scenario.query.get_or_404(scenario_id)
    s.first_node_id = request.form.get('first_node_id', type=int)
    db.session.commit()
    flash('Startpunkt aktualisiert.', 'success')
    return redirect(url_for('admin.edit_bpr_scenario', scenario_id=s.id))

@bp.route('/admin/bpr/delete/<int:scenario_id>', methods=['POST'])
@admin_required
def delete_bpr_scenario(scenario_id):
    s = Scenario.query.get_or_404(scenario_id)
    
    UserScenarioSession.query.filter_by(scenario_id=s.id).delete()
    
    for node in s.nodes:
        for choice in node.choices:
            ChoiceOutcome.query.filter_by(choice_id=choice.id).delete()
        ScenarioChoice.query.filter_by(node_id=node.id).delete()
        
    ScenarioNode.query.filter_by(scenario_id=s.id).delete()
    db.session.delete(s)
    db.session.commit()
    
    flash('Szenario erfolgreich gelöscht.', 'success')
    return redirect(url_for('admin.admin_dashboard', tab='bpr'))

@bp.route('/admin/bpr/node/add/<int:scenario_id>', methods=['POST'])
@admin_required
def add_bpr_node(scenario_id):
    s = Scenario.query.get_or_404(scenario_id)
    
    vitals = {
        "hf": request.form.get('vital_hf', ''),
        "rr": request.form.get('vital_rr', ''),
        "spo2": request.form.get('vital_spo2', ''),
        "af": request.form.get('vital_af', ''),
        "temp": request.form.get('vital_temp', ''),
        "bz": request.form.get('vital_bz', '')
    }
    
    n = ScenarioNode(
        scenario_id=s.id,
        situation_text=request.form.get('situation_text'),
        status_badge=request.form.get('status_badge', 'Unklare Diagnose'),
        vitals=vitals, 
        is_endpoint='is_endpoint' in request.form,
        is_success='is_success' in request.form
    )
    db.session.add(n)
    db.session.commit()
    
    if not s.first_node_id:
        s.first_node_id = n.id
        db.session.commit()
        
    flash('Knotenpunkt (Schritt) erfolgreich hinzugefügt.', 'success')
    return redirect(url_for('admin.edit_bpr_scenario', scenario_id=s.id))

@bp.route('/admin/bpr/choice/add/<int:node_id>', methods=['POST'])
@admin_required
def add_bpr_choice(node_id):
    n = ScenarioNode.query.get_or_404(node_id)
    c = ScenarioChoice(
        node_id=n.id, 
        action_text=request.form.get('action_text')
    )
    db.session.add(c)
    db.session.commit()
    flash('Auswahlmöglichkeit hinzugefügt.', 'success')
    return redirect(url_for('admin.edit_bpr_scenario', scenario_id=n.scenario_id))

@bp.route('/admin/bpr/outcome/add/<int:choice_id>', methods=['POST'])
@admin_required
def add_bpr_outcome(choice_id):
    c = ScenarioChoice.query.get_or_404(choice_id)
    
    req_flags = request.form.get('required_flags')
    set_flags = request.form.get('set_flags')
    
    try:
        r_json = json.loads(req_flags) if req_flags else None
        s_json = json.loads(set_flags) if set_flags else None
    except:
        flash('Fehler: Die Flags müssen valides JSON Format haben (z.B. {"zugang": true}).', 'danger')
        return redirect(url_for('admin.edit_bpr_scenario', scenario_id=c.node.scenario_id))

    o = ChoiceOutcome(
        choice_id=c.id,
        next_node_id=request.form.get('next_node_id', type=int) or None,
        probability_weight=request.form.get('probability', type=int, default=100),
        required_flags=r_json,
        set_flags=s_json,
        is_fatal_error='is_fatal' in request.form,
        error_feedback=request.form.get('error_feedback')
    )
    db.session.add(o)
    db.session.commit()
    flash('Ergebnis (Outcome) hinzugefügt.', 'success')
    return redirect(url_for('admin.edit_bpr_scenario', scenario_id=c.node.scenario_id))

@bp.route('/admin/bpr/export')
@admin_required
def export_bpr():
    scenarios = Scenario.query.all()
    export_data = []
    
    for s in scenarios:
        s_data = {
            'title': s.title,
            'dispatch_text': s.dispatch_text,
            'category': s.category, # NEU
            'first_node_id': s.first_node_id,
            'nodes': []
        }
        for n in s.nodes:
            n_data = {
                'id': n.id,
                'situation_text': n.situation_text,
                'vitals': n.vitals,
                'is_endpoint': n.is_endpoint,
                'is_success': n.is_success,
                'status_badge': n.status_badge,
                'choices': []
            }
            for c in n.choices:
                c_data = {
                    'id': c.id,
                    'action_text': c.action_text,
                    'outcomes': []
                }
                for o in c.outcomes:
                    o_data = {
                        'next_node_id': o.next_node_id,
                        'probability_weight': o.probability_weight,
                        'required_flags': o.required_flags,
                        'set_flags': o.set_flags,
                        'is_fatal_error': o.is_fatal_error,
                        'error_feedback': o.error_feedback
                    }
                    c_data['outcomes'].append(o_data)
                n_data['choices'].append(c_data)
            s_data['nodes'].append(n_data)
        export_data.append(s_data)

    return Response(
        json.dumps(export_data, indent=2), 
        mimetype='application/json', 
        headers={'Content-Disposition': 'attachment;filename=topp_bpr_scenarios.json'}
    )

@bp.route('/admin/bpr/import', methods=['POST'])
@admin_required
def import_bpr():
    if 'file' not in request.files:
        flash('Keine Datei hochgeladen.', 'danger')
        return redirect(url_for('admin.admin_dashboard', tab='bpr'))
        
    file = request.files['file']
    if file.filename == '':
        flash('Keine Datei ausgewählt.', 'danger')
        return redirect(url_for('admin.admin_dashboard', tab='bpr'))

    try:
        file_content = file.read().decode('utf-8')
        data = json.loads(file_content)
        
        if not isinstance(data, list):
            data = [data]
            
        for s_data in data:
            new_s = Scenario(
                title=s_data.get('title', 'Importiertes Szenario'),
                dispatch_text=s_data.get('dispatch_text', 'Unbekanntes Stichwort'),
                category=s_data.get('category', 'Allgemein') # NEU
            )
            db.session.add(new_s)
            db.session.flush()

            id_map = {}
            
            for n_data in s_data.get('nodes', []):
                new_n = ScenarioNode(
                    scenario_id=new_s.id,
                    situation_text=n_data.get('situation_text', ''),
                    vitals=n_data.get('vitals'),
                    status_badge=n_data.get('status_badge', 'Unklar'),
                    is_endpoint=n_data.get('is_endpoint', False),
                    is_success=n_data.get('is_success', False)
                )
                db.session.add(new_n)
                db.session.flush()
                
                if 'id' in n_data:
                    id_map[n_data['id']] = new_n.id
                    
                n_data['_new_node'] = new_n
            
            for n_data in s_data.get('nodes', []):
                new_n = n_data.get('_new_node')
                if not new_n: continue
                
                for c_data in n_data.get('choices', []):
                    new_c = ScenarioChoice(
                        node_id=new_n.id,
                        action_text=c_data.get('action_text', 'Fehlender Text')
                    )
                    db.session.add(new_c)
                    db.session.flush()
                    
                    for o_data in c_data.get('outcomes', []):
                        old_next_id = o_data.get('next_node_id')
                        new_next_id = id_map.get(old_next_id) if old_next_id else None
                        
                        new_o = ChoiceOutcome(
                            choice_id=new_c.id,
                            next_node_id=new_next_id,
                            probability_weight=o_data.get('probability_weight', 100),
                            required_flags=o_data.get('required_flags'),
                            set_flags=o_data.get('set_flags'),
                            is_fatal_error=o_data.get('is_fatal_error', False),
                            error_feedback=o_data.get('error_feedback')
                        )
                        db.session.add(new_o)
            
            old_first_id = s_data.get('first_node_id')
            if old_first_id and old_first_id in id_map:
                new_s.first_node_id = id_map[old_first_id]
            elif s_data.get('nodes'):
                new_s.first_node_id = id_map.get(s_data['nodes'][0].get('id'))
                
        db.session.commit()
        flash(f'{len(data)} BPR Szenarien erfolgreich importiert.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Importieren der JSON: {str(e)}', 'danger')
        
    return redirect(url_for('admin.admin_dashboard', tab='bpr'))

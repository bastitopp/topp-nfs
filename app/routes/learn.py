import json
import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from sqlalchemy.sql.expression import func, or_
from ..extensions import db
from ..models import Card, UserProgress, ExamAttempt, ExamDetail, CardReport
from ..utils import get_next_card, update_progress, award_badges, render_learn_card, get_mc_options, add_xp

bp = Blueprint('learn', __name__)

@bp.route('/learn/custom', methods=['POST'])
@login_required
def learn_custom():
    cats = request.form.getlist('categories')
    if not cats: 
        flash("Bitte wähle mindestens eine Kategorie.", "warning")
        return redirect(url_for('main.index'))
    return redirect(url_for('learn.learn', category_path="|".join(cats)))

@bp.route('/learn/<path:category_path>')
@login_required
def learn(category_path):
    paths = category_path.split('|')
    force = request.args.get('force') == 'true'
    card, p = get_next_card(current_user, paths, force=force)
    
    if not card: 
        conds = [Card.category.like(f"{p}%") for p in paths]
        w = UserProgress.query.join(Card).filter(
            UserProgress.user_id==current_user.id, 
            or_(*conds), 
            UserProgress.next_review > datetime.utcnow()
        ).count()
        return render_template('quiz.html', finished=True, category=category_path, waiting_count=w)
    
    return render_learn_card(card, current_user, category_path)

@bp.route('/submit/<int:card_id>', methods=['POST'])
@login_required
def submit(card_id):
    try:
        if request.form.get('start_time'): 
            try:
                d = datetime.utcnow().timestamp() - float(request.form.get('start_time'))
                if 0 < d < 600:
                    current_user.total_learning_time += int(d)
                    db.session.commit()
            except: pass
        
        card = Card.query.get_or_404(card_id)
        origin = request.form.get('origin_path', card.category)
        
        card_opts = []
        if card.options:
            try: card_opts = json.loads(card.options)
            except: card_opts = []

        if card.type == 'mc':
            u = request.form.get('mc_answer')
            corr = (u == card.answer)
            update_progress(current_user, card, corr)
            award_badges(current_user)
            opts_feedback = get_mc_options(card)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, options=opts_feedback, finished=False, feedback=True, user_answer=u, is_correct=corr, box=p.box if p else 0, current_category=origin)
        
        elif card.type == 'anatomy':
            ud = request.form.get('input_de','').strip().lower()
            ul = request.form.get('input_lat','').strip().lower()
            sd = card.answer.strip().lower() if card.answer else ""
            sl = card.answer_lat.strip().lower() if card.answer_lat else ""
            corr = ((ud == sd) if sd else True) and ((ul == sl) if sl else True)
            update_progress(current_user, card, corr)
            award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_anatomy=True, result_de=(ud==sd), result_lat=(ul==sl if sl else True), box=p.box if p else 0, current_category=origin)
        
        elif card.type == 'anatomy_multi':
            sub = True
            res = []
            for i in card_opts:
                rid = str(i.get('id'))
                ud = request.form.get(f"de_{rid}",'').strip().lower()
                ul = request.form.get(f"lat_{rid}",'').strip().lower()
                correct_de = i.get('de','').strip().lower() if i.get('de') else ""
                correct_lat = i.get('lat','').strip().lower() if i.get('lat') else ""
                cde = (ud == correct_de) if correct_de else True
                clat = (ul == correct_lat) if correct_lat else True
                if (correct_de and not cde) or (correct_lat and not clat): sub = False
                res.append({'label': rid, 'user_de': request.form.get(f"de_{rid}",''), 'user_lat': request.form.get(f"lat_{rid}",''), 'correct_de': i.get('de'), 'correct_lat': i.get('lat'), 'is_de_ok': cde, 'is_lat_ok': clat})
            update_progress(current_user, card, sub)
            award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_multi=True, multi_results=res, all_correct=sub, box=p.box if p else 0, current_category=origin)

        elif card.type == 'ordering':
            try: uo = json.loads(request.form.get('order_json', '[]'))
            except: uo = []
            corr = (uo == card_opts)
            update_progress(current_user, card, corr)
            award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_ordering=True, user_order=uo, correct_order=card_opts, is_correct=corr, box=p.box if p else 0, current_category=origin)

        elif card.type == 'assignment':
            try: ud = json.loads(request.form.get('assignment_json', '{}'))
            except: ud = {}
            all_c = True
            res = []
            for g in card_opts:
                gn = g.get('name')
                ci = g.get('items', [])
                ui = ud.get(gn, [])
                gr = {'name': gn, 'group_items': [], 'missing': []}
                for i, u in enumerate(ui):
                    st = {'text': u}
                    if u not in ci: 
                        all_c = False; st['correct'] = False; st['reason'] = 'wrong_group'
                    elif i < len(ci) and ci[i] == u: st['correct'] = True
                    else: 
                        all_c = False; st['correct'] = False; st['reason'] = 'wrong_order'
                    gr['group_items'].append(st)
                for c in ci: 
                    if c not in ui: all_c = False; gr['missing'].append(c)
                res.append(gr)
            update_progress(current_user, card, all_c)
            award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_assignment=True, all_correct=all_c, assignment_results=res, box=p.box if p else 0, current_category=origin)

        elif card.type == 'calculation':
            try:
                user_val = float(request.form.get('calc_input', '0').replace(',', '.'))
                used_var = float(request.form.get('calc_var', '0')) 
                if '-' in card.answer: f_min, f_max = map(float, card.answer.split('-'))
                else: f_min = f_max = float(card.answer)
                target_min = used_var * f_min; target_max = used_var * f_max
                is_correct = (round(target_min, 3) <= round(user_val, 3) <= round(target_max, 3))
                result_text = f"Zielbereich: {target_min:.2f} - {target_max:.2f}"
                try: result_text += f" {json.loads(card.options).get('unit', '')}"
                except: pass
            except ValueError: is_correct = False; result_text = "Ungültige Eingabe"; user_val = request.form.get('calc_input', '-')
            update_progress(current_user, card, is_correct)
            award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            calc_data_reconstructed = {'val': used_var, 'question': card.question.replace('{weight}', str(int(used_var) if used_var.is_integer() else used_var)), 'unit': ''}
            try: calc_data_reconstructed['unit'] = json.loads(card.options).get('unit','')
            except: pass
            return render_template('quiz.html', card=card, finished=False, feedback_calc=True, is_correct=is_correct, user_val=user_val, result_text=result_text, box=p.box if p else 0, current_category=origin, calc_data=calc_data_reconstructed)

        else: 
            try: quality = int(request.form.get('result', 0))
            except: quality = 0
            update_progress(current_user, card, quality)
            award_badges(current_user)
            return redirect(url_for('learn.learn', category_path=origin))
            
    except Exception as e: 
        print(f"ERROR submitting card {card_id}: {e}")
        flash("Ein Fehler ist aufgetreten.", "danger")
        return redirect(url_for('main.index'))

@bp.route('/report/<int:card_id>', methods=['GET', 'POST'])
@login_required
def report_card(card_id):
    if request.method == 'POST':
        reason = request.form.get('reason')
        if reason:
            db.session.add(CardReport(card_id=card_id, user_id=current_user.id, reason=reason))
            db.session.commit()
            flash('Frage wurde gemeldet.', 'success')
        return redirect(request.referrer or url_for('main.index'))
    return redirect(url_for('main.index'))

@bp.route('/learn/errors')
@login_required
def learn_errors():
    sub = UserProgress.query.filter(UserProgress.user_id == current_user.id, or_(UserProgress.box == 0, UserProgress.last_correct == False)).with_entities(UserProgress.card_id)
    card = Card.query.filter(Card.id.in_(sub)).order_by(func.random()).first()
    if not card: flash("Keine Fehler gefunden!", "success"); return redirect(url_for('main.index'))
    return render_learn_card(card, current_user, "errors")

# --- PRÜFUNGSMODUS ---

@bp.route('/exam')
@login_required
def exam_index():
    # Setup Seite für die Prüfung
    valid_types = ['mc', 'anatomy', 'anatomy_multi', 'ordering', 'assignment', 'calculation']
    max_count = Card.query.filter(Card.type.in_(valid_types)).count()
    return render_template('exam_setup.html', max_questions=max_count)

@bp.route('/exam/start', methods=['POST'])
@login_required
def exam_start():
    try:
        count = int(request.form.get('question_count', 30))
    except: count = 30
    
    valid = ['mc', 'anatomy', 'anatomy_multi', 'ordering', 'assignment', 'calculation']
    questions = Card.query.filter(Card.type.in_(valid)).order_by(func.random()).limit(count).all()
    
    if not questions:
        flash("Keine geeigneten Fragen gefunden.", "warning")
        return redirect(url_for('learn.exam_index'))

    prepared = []
    exam_vars = {} 
    
    # Zeitberechnung
    total_seconds = 0

    for card in questions:
        # Zeit addieren
        if card.type == 'mc': total_seconds += 45
        else: total_seconds += 120 # 2 Minuten für komplexe Fragen

        opts = []
        pool = [] 
        calc_data = None
        
        if card.options:
            try: opts = json.loads(card.options)
            except: opts = []
            
        if card.type == 'mc': 
            opts = get_mc_options(card)
        
        elif card.type == 'ordering':
            random.shuffle(opts)
            
        elif card.type == 'assignment':
            temp_pool = []
            for gr in opts:
                for item in gr.get('items', []):
                    temp_pool.append({'val': item, 'group': gr.get('name')})
            random.shuffle(temp_pool)
            pool = temp_pool
            
        elif card.type == 'calculation':
            try:
                conf = opts
                val_min = conf.get('min', 10); val_max = conf.get('max', 150); step = conf.get('step', 1)
                steps = int((val_max - val_min) / step)
                val = val_min + (random.randint(0, steps) * step)
                exam_vars[str(card.id)] = val
                display_val = int(val) if val == int(val) else val
                calc_data = {'question': card.question.replace('{weight}', str(display_val)), 'unit': conf.get('unit', '')}
            except: continue
             
        prepared.append({'card': card, 'options': opts, 'pool': pool, 'calc_data': calc_data})
    
    session['exam_vars'] = exam_vars
    
    # Auf Minuten runden (mindestens 1 Minute)
    est_time = max(1, round(total_seconds / 60))
    
    return render_template('exam.html', questions=prepared, estimated_time=est_time)

@bp.route('/exam/submit', methods=['POST'])
@login_required
def exam_submit():
    score = 0
    card_ids = request.form.getlist('card_ids')
    attempt = ExamAttempt(user_id=current_user.id, total_questions=len(card_ids))
    db.session.add(attempt)
    db.session.flush()
    
    exam_vars = session.get('exam_vars', {})
    
    for cid in card_ids:
        try:
            cid = int(cid)
            card = Card.query.get(cid)
            if not card: continue
            
            is_correct = False
            user_sol = None
            correct_sol = None
            
            if card.type == 'mc':
                u_val = request.form.get(f'q_{cid}')
                user_sol = u_val
                correct_sol = card.answer
                if u_val == card.answer: is_correct = True
            
            elif card.type == 'anatomy':
                ud = request.form.get(f'q_{cid}_de','').strip().lower()
                ul = request.form.get(f'q_{cid}_lat','').strip().lower()
                sd = card.answer.strip().lower() if card.answer else ""
                sl = card.answer_lat.strip().lower() if card.answer_lat else ""
                
                user_sol = json.dumps({'de': request.form.get(f'q_{cid}_de',''), 'lat': request.form.get(f'q_{cid}_lat','')})
                correct_sol = json.dumps({'de': card.answer, 'lat': card.answer_lat})
                
                if ((not sd or ud==sd) and (not sl or ul==sl)): is_correct = True

            elif card.type == 'anatomy_multi':
                try:
                    parts = json.loads(card.options)
                    correct_sol = card.options
                    
                    user_parts = []
                    part_correct = True
                    for p in parts:
                        pid = str(p['id'])
                        ud = request.form.get(f'q_{cid}_{pid}_de','').strip().lower()
                        ul = request.form.get(f'q_{cid}_{pid}_lat','').strip().lower()
                        sd = p.get('de','').strip().lower()
                        sl = p.get('lat','').strip().lower()
                        
                        user_parts.append({'id': p['id'], 'de': request.form.get(f'q_{cid}_{pid}_de',''), 'lat': request.form.get(f'q_{cid}_{pid}_lat','')})
                        
                        if (sd and ud!=sd) or (sl and ul!=sl): part_correct = False
                    
                    user_sol = json.dumps(user_parts)
                    is_correct = part_correct
                except: pass

            elif card.type == 'ordering':
                try:
                    u_raw = request.form.get(f'q_{cid}', '[]')
                    uo = json.loads(u_raw)
                    opts = json.loads(card.options)
                    user_sol = u_raw
                    correct_sol = card.options
                    if uo == opts: is_correct = True
                except: pass

            elif card.type == 'assignment':
                try:
                    u_raw = request.form.get(f'q_{cid}', '{}')
                    ud = json.loads(u_raw)
                    groups = json.loads(card.options)
                    
                    user_sol = u_raw
                    correct_sol = card.options
                    
                    assign_ok = True
                    for gr in groups:
                        target_items = set(gr.get('items', []))
                        user_items = set(ud.get(gr.get('name'), []))
                        if target_items != user_items: assign_ok = False
                    is_correct = assign_ok
                except: pass

            elif card.type == 'calculation':
                u_var = float(exam_vars.get(str(cid), 0))
                u_val_raw = request.form.get(f'q_{cid}', '0')
                u_val = float(u_val_raw.replace(',', '.'))
                
                if '-' in card.answer: f_min, f_max = map(float, card.answer.split('-'))
                else: f_min = f_max = float(card.answer)
                t_min = u_var * f_min; t_max = u_var * f_max
                
                user_sol = f"{u_val_raw} (Faktor: {u_var})"
                correct_sol = f"{t_min:.2f} - {t_max:.2f}"
                
                if round(t_min, 3) <= round(u_val, 3) <= round(t_max, 3): is_correct = True

            if is_correct: score += 1
            
            db.session.add(ExamDetail(
                attempt_id=attempt.id, 
                question_text=card.question, 
                question_type=card.type, 
                is_correct=is_correct,
                user_solution=user_sol,
                correct_solution=correct_sol
            ))
            
        except Exception as e: print(f"Exam check error card {cid}: {e}")

    attempt.score = score
    attempt.passed = (score >= (len(card_ids) * 0.6)) if card_ids else False
    
    if attempt.passed:
        add_xp(current_user, 100)
        flash(f"Prüfung bestanden! {score}/{len(card_ids)} Punkte (+100 XP)", "success")
    else:
        flash(f"Nicht bestanden. {score}/{len(card_ids)} Punkte.", "warning")
        
    db.session.commit()
    session.pop('exam_vars', None)
    return redirect(url_for('learn.review_exam', attempt_id=attempt.id))

@bp.route('/profile/exam/<int:attempt_id>')
@login_required
def review_exam(attempt_id):
    att = ExamAttempt.query.get_or_404(attempt_id)
    if att.user_id != current_user.id and not current_user.is_admin: 
        flash("Zugriff verweigert", "danger"); return redirect(url_for('main.profile'))
    
    res = []
    for d in att.details:
        u_data = d.user_solution
        c_data = d.correct_solution
        
        if d.question_type in ['anatomy', 'anatomy_multi', 'ordering', 'assignment']:
            try:
                if u_data: u_data = json.loads(u_data)
                if c_data: c_data = json.loads(c_data)
            except: pass
            
        res.append({
            'question': d.question_text, 
            'type': d.question_type, 
            'is_correct': d.is_correct,
            'user_data': u_data,
            'correct_data': c_data
        })
        
    percent = int((att.score / att.total_questions) * 100) if att.total_questions > 0 else 0
    return render_template('exam_result.html', score=att.score, total=att.total_questions, percent=percent, passed=att.passed, results=res, date=att.timestamp)

import json
import random
import numpy as np
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required, current_user
from sqlalchemy.sql.expression import func, or_
from sqlalchemy.orm.attributes import flag_modified  
from ..extensions import db

from ..models import Card, UserProgress, ExamAttempt, ExamDetail, CardReport, Scenario, ScenarioNode, ScenarioChoice, ChoiceOutcome, UserScenarioSession
from ..utils import (get_next_card, update_progress, award_badges, render_learn_card, 
                     get_mc_options, add_xp, fuzzy_match, build_category_tree)

bp = Blueprint('learn', __name__)

# ==========================================
# --- Quiz / Lern Routen ---
# ==========================================

@bp.route('/learn/custom', methods=['POST'])
@login_required
def learn_custom():
    cats = request.form.getlist('categories')
    if not cats: 
        flash("Bitte wähle mindestens eine Kategorie.", "warning")
        return redirect(url_for('main.index'))
    return redirect(url_for('learn.learn', category_path="|".join(cats)))

@bp.route('/learn/<path:category_path>', methods=['GET', 'POST'])
@login_required
def learn(category_path):
    if request.args.get('ignore_limit') == 'true':
        session['ignore_limit_date'] = datetime.utcnow().strftime('%Y-%m-%d')
        
    paths = category_path.split('|')
    force = request.args.get('force') == 'true' or request.form.get('force') == 'true'
    skip_id = request.args.get('skip_id', type=int) or request.form.get('skip_id', type=int)
    
    card, p = get_next_card(current_user, paths, force=force, exclude_id=skip_id)
    
    if not card: 
        w_query = UserProgress.query.join(Card).filter(
            UserProgress.user_id==current_user.id, 
            UserProgress.next_review > datetime.utcnow()
        )
        if "Alle" not in paths and paths != [""]:
            conds = [Card.category.like(f"{p}%") for p in paths]
            w_query = w_query.filter(or_(*conds))
            
        w = w_query.count()
        return render_template('quiz.html', finished=True, category=category_path, waiting_count=w)
    
    return render_learn_card(card, current_user, category_path)

@bp.route('/submit_quality/<int:card_id>', methods=['POST'])
@login_required
def submit_quality(card_id):
    quality = request.form.get('quality', type=int, default=4)
    origin = request.form.get('origin_path')
    card = Card.query.get_or_404(card_id)
    update_progress(current_user, card, quality)
    award_badges(current_user)
    return redirect(url_for('learn.learn', category_path=origin))

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
        card_opts = json.loads(card.options) if card.options else []
        is_correct = False
        f_data = {}

        if card.type == 'mc':
            u = request.form.get('mc_answer')
            is_correct = (u == card.answer)
            shuffled_json = request.form.get('shuffled_options')
            options = json.loads(shuffled_json) if shuffled_json else get_mc_options(card)
            f_data = {'user_answer': u, 'options': options}
        
        elif card.type == 'anatomy':
            ud, ul = request.form.get('input_de',''), request.form.get('input_lat','')
            res_de, res_lat = fuzzy_match(ud, card.answer), fuzzy_match(ul, card.answer_lat)
            is_correct = res_de and res_lat
            f_data = {'result_de': res_de, 'result_lat': res_lat, 'user_de': ud, 'user_lat': ul}
        
        elif card.type == 'anatomy_multi':
            all_c, res = True, []
            for i in card_opts:
                rid = str(i.get('id'))
                ud, ul = request.form.get(f"de_{rid}",''), request.form.get(f"lat_{rid}",'')
                cde, clat = fuzzy_match(ud, i.get('de')), fuzzy_match(ul, i.get('lat'))
                if not cde or not clat: all_c = False
                res.append({'label': rid, 'user_de': ud, 'user_lat': ul, 'correct_de': i.get('de'), 'correct_lat': i.get('lat'), 'is_de_ok': cde, 'is_lat_ok': clat})
            is_correct = all_c; f_data = {'multi_results': res}

        elif card.type == 'ordering':
            uo = json.loads(request.form.get('order_json', '[]'))
            is_correct = (uo == card_opts)
            f_data = {'correct_order': card_opts}

        elif card.type == 'assignment':
            ud = json.loads(request.form.get('assignment_json', '{}'))
            all_c, res = True, []
            for g in card_opts:
                gn, ci, ui = g.get('name'), g.get('items', []), ud.get(gn, [])
                gr = {'name': gn, 'group_items': [], 'missing': []}
                for i, u in enumerate(ui):
                    st = {'text': u, 'correct': (u in ci)}
                    if not st['correct']: all_c = False
                    gr['group_items'].append(st)
                for c in ci: 
                    if c not in ui: all_c = False; gr['missing'].append(c)
                res.append(gr)
            is_correct = all_c; f_data = {'assignment_results': res}

        elif card.type == 'calculation':
            u_val = float(request.form.get('calc_input', '0').replace(',', '.'))
            u_var = float(request.form.get('calc_var', '0')) 
            f_min, f_max = map(float, card.answer.split('-')) if '-' in card.answer else (float(card.answer), float(card.answer))
            is_correct = (round(u_var * f_min, 3) <= round(u_val, 3) <= round(u_var * f_max, 3))
            f_data = {'user_val': u_val, 'result_text': f"{u_var*f_min:.2f} - {u_var*f_max:.2f}", 'calc_data': {'val': u_var}}

        if not is_correct: 
            update_progress(current_user, card, 0)
        
        award_badges(current_user)
        p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
        return render_template('quiz.html', card=card, finished=False, feedback=True, is_correct=is_correct, box=p.box if p else 0, current_category=origin, **f_data)
            
    except Exception as e: 
        print(f"ERROR: {e}"); flash("Fehler bei der Verarbeitung.", "danger")
        return redirect(url_for('main.index'))

@bp.route('/report/<int:card_id>', methods=['GET', 'POST'])
@login_required
def report_card(card_id):
    card = Card.query.get_or_404(card_id)
    if request.method == 'POST':
        reason = request.form.get('reason')
        origin = request.form.get('origin_path') or 'Alle' 
        if reason:
            db.session.add(CardReport(card_id=card.id, user_id=current_user.id, reason=reason))
            db.session.commit()
            flash('Frage wurde gemeldet.', 'success')
        return redirect(url_for('learn.learn', category_path=origin, skip_id=card.id))
    return redirect(url_for('main.index'))

@bp.route('/learn/errors', methods=['GET', 'POST'])
@login_required
def learn_errors():
    sub = UserProgress.query.filter(UserProgress.user_id == current_user.id, or_(UserProgress.box == 0, UserProgress.last_correct == False)).with_entities(UserProgress.card_id)
    card = Card.query.filter(Card.id.in_(sub)).order_by(func.random()).first()
    if not card: flash("Keine Fehler gefunden!", "success"); return redirect(url_for('main.index'))
    return render_learn_card(card, current_user, "errors")


# ==========================================
# --- Exam Routen ---
# ==========================================

@bp.route('/exam')
@login_required
def exam_index():
    valid_types = ['mc', 'anatomy', 'anatomy_multi', 'ordering', 'assignment', 'calculation']
    tree = build_category_tree(current_user)
    max_count = Card.query.filter(Card.type.in_(valid_types)).count()
    return render_template('exam_setup.html', max_questions=max_count, tree=tree)

@bp.route('/exam/start', methods=['POST'])
@login_required
def exam_start():
    try: count = int(request.form.get('question_count', 30))
    except: count = 30
    cats = request.form.getlist('categories')
    base_query = Card.query
    if cats:
        conds = [Card.category.like(f"{c}%") for c in cats]
        base_query = base_query.filter(or_(*conds))
    
    questions = base_query.filter(Card.type.in_(['mc', 'anatomy', 'anatomy_multi', 'ordering', 'assignment', 'calculation'])).order_by(func.random()).limit(count).all()
    if not questions: flash("Keine Fragen gefunden.", "warning"); return redirect(url_for('learn.exam_index'))
    
    random.shuffle(questions); prepared = []; exam_vars = {}; total_s = 0
    for card in questions:
        total_s += 45 if card.type == 'mc' else 120
        try: opts = json.loads(card.options) if card.options else []
        except: opts = []
            
        calc_data = None
        if card.type == 'mc': opts = get_mc_options(card)
        elif card.type == 'calculation':
            val = random.randrange(opts.get('min',10), opts.get('max',150)+1, opts.get('step',1))
            exam_vars[str(card.id)] = val
            calc_data = {'question': card.question.replace('{weight}', str(val)), 'unit': opts.get('unit','')}
            
        prepared.append({'card': card, 'options': opts, 'calc_data': calc_data})
    
    session['exam_vars'] = exam_vars
    return render_template('exam.html', questions=prepared, estimated_time=max(1, round(total_s / 60)))

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
        card = Card.query.get(int(cid))
        is_c = False
        u_sol, c_sol = None, None
        
        if card.type == 'mc':
            u_sol = request.form.get(f'q_{cid}')
            c_sol = card.answer
            is_c = (u_sol == c_sol)
        elif card.type == 'calculation':
            try:
                u_val = float(request.form.get(f'q_{cid}', '0').replace(',', '.'))
                u_var = float(exam_vars.get(str(cid), '0'))
                f_min, f_max = map(float, card.answer.split('-')) if '-' in card.answer else (float(card.answer), float(card.answer))
                is_c = (round(u_var * f_min, 3) <= round(u_val, 3) <= round(u_var * f_max, 3))
                u_sol, c_sol = str(u_val), f"{u_var*f_min:.2f} - {u_var*f_max:.2f}"
            except: pass
        elif card.type == 'anatomy':
            ud, ul = request.form.get(f'q_{cid}_de',''), request.form.get(f'q_{cid}_lat','')
            is_c = fuzzy_match(ud, card.answer) and fuzzy_match(ul, card.answer_lat)
            u_sol, c_sol = json.dumps({'de': ud, 'lat': ul}), json.dumps({'de': card.answer, 'lat': card.answer_lat})
        elif card.type == 'anatomy_multi':
            card_opts = json.loads(card.options) if card.options else []
            all_c, u_list = True, []
            for i in card_opts:
                rid = str(i.get('id'))
                ud = request.form.get(f"q_{cid}_{rid}_de", '')
                ul = request.form.get(f"q_{cid}_{rid}_lat", '')
                if not fuzzy_match(ud, i.get('de')) or not fuzzy_match(ul, i.get('lat')): all_c = False
                u_list.append({'id': rid, 'de': ud, 'lat': ul})
            is_c, u_sol, c_sol = all_c, json.dumps(u_list), card.options
        elif card.type == 'ordering':
            try:
                u_list = json.loads(request.form.get(f'q_{cid}', '[]'))
                is_c = (u_list == json.loads(card.options))
                u_sol, c_sol = json.dumps(u_list), card.options
            except: is_c = False
        elif card.type == 'assignment':
            try:
                u_dict = json.loads(request.form.get(f'q_{cid}', '{}'))
                card_opts = json.loads(card.options)
                all_c = True
                for g in card_opts:
                    if set(u_dict.get(g.get('name'), [])) != set(g.get('items', [])): all_c = False
                is_c, u_sol, c_sol = all_c, json.dumps(u_dict), card.options
            except: is_c = False
            
        if is_c: score += 1
        db.session.add(ExamDetail(
            attempt_id=attempt.id, question_text=card.question, question_type=card.type,
            is_correct=is_c, user_solution=u_sol, correct_solution=c_sol
        ))

    attempt.score = score
    attempt.passed = (score >= (len(card_ids) * 0.6))
    if attempt.passed: add_xp(current_user, 100)
    db.session.commit()
    return redirect(url_for('learn.review_exam', attempt_id=attempt.id))

@bp.route('/profile/exam/<int:attempt_id>')
@login_required
def review_exam(attempt_id):
    att = ExamAttempt.query.get_or_404(attempt_id)
    res = []
    for d in att.details:
        u_data, c_data = d.user_solution, d.correct_solution
        if d.question_type in ['anatomy', 'anatomy_multi', 'ordering', 'assignment']:
            try:
                u_data = json.loads(d.user_solution) if d.user_solution else None
                c_data = json.loads(d.correct_solution) if d.correct_solution else None
            except: pass
        res.append({
            'question': d.question_text, 'type': d.question_type, 'is_correct': d.is_correct,
            'user_solution': u_data, 'correct_solution': c_data
        })
    
    percent = int((att.score / att.total_questions) * 100) if att.total_questions > 0 else 0
    return render_template('exam_result.html', score=att.score, total=att.total_questions, 
                           percent=percent, results=res, passed=att.passed, date=att.timestamp)


# ==========================================
# --- BPR / SOP Trainer Routen ---
# ==========================================

@bp.route('/bpr')
@login_required
def bpr_index():
    scenarios = Scenario.query.all()
    return render_template('bpr_index.html', scenarios=scenarios)

@bp.route('/bpr/random')
@login_required
def bpr_random():
    scenario = Scenario.query.order_by(func.random()).first()
    if not scenario:
        flash("Aktuell sind keine BPR-Szenarien verfügbar.", "warning")
        return redirect(url_for('learn.bpr_index'))
    return redirect(url_for('learn.bpr_play', scenario_id=scenario.id))

@bp.route('/bpr/play/<int:scenario_id>')
@login_required
def bpr_play(scenario_id):
    scenario = Scenario.query.get_or_404(scenario_id)
    if not scenario.first_node_id:
        flash("Szenario hat keinen Startpunkt.", "warning")
        return redirect(url_for('learn.bpr_index'))
        
    session_db = UserScenarioSession.query.filter_by(user_id=current_user.id, scenario_id=scenario.id).first()
    if not session_db:
        session_db = UserScenarioSession(user_id=current_user.id, scenario_id=scenario.id)
        db.session.add(session_db)
        
    session_db.current_node_id = scenario.first_node_id
    session_db.state_flags = {}
    session_db.history_nodes = []
    session_db.completed = False
    session_db.success = False
    db.session.commit()
    
    current_node = ScenarioNode.query.get(scenario.first_node_id)
    return render_template('bpr_play.html', scenario=scenario, current_node=current_node, flags=session_db.state_flags or {})

@bp.route('/bpr/choice/<int:choice_id>', methods=['POST'])
@login_required
def bpr_choice(choice_id):
    choice = ScenarioChoice.query.get_or_404(choice_id)
    node = choice.node
    scenario = node.scenario
    
    session_db = UserScenarioSession.query.filter_by(user_id=current_user.id, scenario_id=scenario.id).first()
    if not session_db or session_db.completed:
        return "Szenario bereits beendet.", 400
        
    user_flags = session_db.state_flags or {}
    valid_outcomes = []
    
    for out in choice.outcomes:
        req = out.required_flags or {}
        is_valid = True
        for k, v in req.items():
            if user_flags.get(k) != v:
                is_valid = False
                break
        if is_valid:
            valid_outcomes.extend([out] * (out.probability_weight or 100))
            
    if valid_outcomes:
        selected_outcome = random.choice(valid_outcomes)
    else:
        selected_outcome = ChoiceOutcome.query.filter_by(choice_id=choice.id, is_fatal_error=True).first()
        
    if not selected_outcome:
        session_db.completed = True
        db.session.commit()
        return render_template('bpr_swap.html', old_node=node, choice=choice, error="Aktion nicht möglich (Vorbedingungen fehlen).", scenario_id=scenario.id, flags=session_db.state_flags or {})

    if selected_outcome.is_fatal_error:
        session_db.completed = True
        session_db.success = False
        db.session.commit()
        return render_template('bpr_swap.html', old_node=node, choice=choice, error=selected_outcome.error_feedback, scenario_id=scenario.id, flags=session_db.state_flags or {})
        
    if selected_outcome.set_flags:
        current_state = session_db.state_flags or {}
        current_state.update(selected_outcome.set_flags)
        session_db.state_flags = current_state
        flag_modified(session_db, "state_flags")
        
    session_db.current_node_id = selected_outcome.next_node_id
    next_node = ScenarioNode.query.get(selected_outcome.next_node_id)
    
    if next_node and next_node.is_endpoint:
        session_db.completed = True
        if next_node.is_success:
            session_db.success = True
            add_xp(current_user, 100)
            
    db.session.commit()
    
    return render_template('bpr_swap.html', old_node=node, choice=choice, next_node=next_node, scenario_id=scenario.id, flags=session_db.state_flags or {})

# ==========================================
# --- EKG Simulator Routen ---
# ==========================================

@bp.route('/api/simulator/ecg')
@login_required
def api_simulator_ecg():
    preset = request.args.get('preset', 'none')
    
    # 1. Parameter abrufen
    hr = float(request.args.get('hr', 72))
    qrs_width = float(request.args.get('qrs_width', 0.015))
    st_elevation = float(request.args.get('st_elevation', 0.0))
    potassium = float(request.args.get('potassium', 4.0)) 
    axis = float(request.args.get('axis', 60.0))          
    
    # --- PRESET ÜBERSCHREIBUNGEN FÜR PATHOLOGIEN ---
    if preset != 'none':
        if preset == 'vt':
            hr = 170
            qrs_width = 0.045
            axis = -120 # Überdrehter Linkstyp bei VT
            st_elevation = 0.0
        elif preset == 'svt':
            hr = 180
            qrs_width = 0.015
            axis = 60
            st_elevation = 0.0
        elif preset == 'av3':
            hr = 40 # Typischer Kammer-Ersatzrhythmus
            qrs_width = 0.025 # Meist leicht verbreitert
            axis = 60
        elif preset == 'stemi':
            hr = 85
            axis = 60
            st_elevation = 0.5 # ST-Hebung für II und III wird unten verarbeitet
        elif preset == 'av1':
            hr = 65
        elif preset == 'av2':
            hr = 75 # Entspricht einer Kammerfrequenz von ca. 37 (bei 2:1 Block)
            
    duration = 4.0
    fs = 250 
    t = np.linspace(0, duration, int(duration * fs), endpoint=False)
    beat_interval = 60.0 / hr
    
    # --- BASIS-AMPLITUDEN ---
    v_p = 0.15; v_q = -0.15; v_r = 1.5; v_s = -0.3; v_t = 0.35
    
    # --- KALIUM-EFFEKTE ---
    t_amp, t_width, p_amp_current = v_t, 0.04, v_p
    if potassium > 5.0:
        diff = potassium - 5.0
        t_amp = v_t + (diff * 0.4)
        t_width = max(0.015, 0.04 - (diff * 0.01))
        p_amp_current = max(0.0, v_p - (diff * 0.1))
        qrs_width += (diff * 0.005)
    elif potassium < 3.5:
        diff = 3.5 - potassium
        t_amp = max(0.05, v_t - (diff * 0.2))
        t_width = 0.06 
        st_elevation -= (diff * 0.15) 

    # --- ZEITPUNKTE BERECHNEN (RHYTHMUS-GENERATOR) ---
    t_end = duration
    p_times = []
    qrs_times = []
    t_curr = 0.5
    
    if preset in ['none', 'stemi']:
        while t_curr < t_end:
            p_times.append(t_curr - 0.16)
            qrs_times.append(t_curr)
            t_curr += beat_interval
            
    elif preset == 'av1':
        while t_curr < t_end:
            p_times.append(t_curr - 0.32) # PQ-Zeit extrem verlängert (>200ms)
            qrs_times.append(t_curr)
            t_curr += beat_interval
            
    elif preset == 'av2': # 2:1 Blockade
        count = 0
        while t_curr < t_end:
            p_times.append(t_curr - 0.16)
            if count % 2 == 0:
                qrs_times.append(t_curr)
            t_curr += (60.0 / 80.0) # Vorhofrate = 80 bpm
            count += 1
            
    elif preset == 'av3':
        # Vorhöfe (85 bpm) und Kammern (40 bpm) schlagen entkoppelt
        tp = 0.2
        while tp < t_end:
            p_times.append(tp)
            tp += (60.0 / 85.0) 
        tq = 0.5
        while tq < t_end:
            qrs_times.append(tq)
            tq += beat_interval 
            
    elif preset == 'vt':
        while t_curr < t_end:
            qrs_times.append(t_curr) # P-Wellen fehlen komplett
            t_curr += beat_interval
            
    elif preset == 'svt':
        while t_curr < t_end:
            qrs_times.append(t_curr) # P-Wellen fallen in die T-Welle/fehlen
            t_curr += beat_interval

    # --- VEKTOR-PROJEKTION UND ZEICHNEN ---
    axis_rad = np.radians(axis)
    def project(amp, angle_rad, lead_angle_deg):
        return amp * np.cos(angle_rad - np.radians(lead_angle_deg))

    leads = {'I': np.zeros_like(t), 'II': np.zeros_like(t), 'III': np.zeros_like(t)}
    lead_angles = {'I': 0, 'II': 60, 'III': 120} 
    
    for name, angle in lead_angles.items():
        p_amp = project(p_amp_current, axis_rad, angle)
        q_amp = project(v_q, axis_rad, angle)
        r_amp = project(v_r, axis_rad, angle)
        s_amp = project(v_s, axis_rad, angle)
        t_amp_proj = project(t_amp, axis_rad, angle)
        
        p_params = [(p_amp, 0.0, 0.02)]
        qrs_t_params = [
            (q_amp, -0.04, 0.01),
            (r_amp, 0.0, qrs_width),
            (s_amp, 0.04, qrs_width),
            (t_amp_proj, 0.28, t_width) 
        ]
        
        ecg = leads[name]
        
        # P-Wellen zeichnen
        for pt in p_times:
            for amp, offset, width in p_params:
                ecg += amp * np.exp(-((t - (pt + offset)) ** 2) / (2 * width ** 2))
                
        # QRS-Komplexe und T-Wellen zeichnen
        for qt in qrs_times:
            for amp, offset, width in qrs_t_params:
                ecg += amp * np.exp(-((t - (qt + offset)) ** 2) / (2 * width ** 2))
                
            # Pathologische ST-Hebungen (STEMI Logik für Hinterwand)
            st_val = st_elevation
            if preset == 'stemi':
                if name in ['II', 'III']: st_val = 0.5     # Hebung inferior
                elif name == 'I': st_val = -0.2            # Reziproke Senkung
                
            if st_val != 0:
                st_start = qt + 0.06
                st_end = qt + 0.20
                mask = (t > st_start) & (t < st_end)
                ecg[mask] += st_val * np.sin(np.pi * (t[mask] - st_start) / (st_end - st_start))

        # Rauschen
        ecg += 0.02 * np.sin(2 * np.pi * 0.2 * t)
        leads[name] = ecg.tolist()
        
    return jsonify({
        'time': t.tolist(),
        'lead_I': leads['I'],
        'lead_II': leads['II'],
        'lead_III': leads['III'],
        'metadata': {
            'hr': int(hr),
            'axis': int(axis),
            'potassium': round(potassium, 1),
            'qrs_width': round(qrs_width, 3),
            'st_elevation': round(st_elevation, 1),
            'preset': preset
        }
    })

@bp.route('/learn/ecg-simulator')
@login_required
def ecg_simulator():
    return render_template('ecg_simulator.html')

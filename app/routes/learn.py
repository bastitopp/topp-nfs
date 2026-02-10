import json
import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
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
    
    # Nächste Karte holen (SM-2 Algorithmus)
    card, p = get_next_card(current_user, paths, force=force)
    
    if not card: 
        # Keine Karten mehr? Prüfen wie viele warten (für "Trotzdem lernen")
        conds = [Card.category.like(f"{p}%") for p in paths]
        w = UserProgress.query.join(Card).filter(
            UserProgress.user_id==current_user.id, 
            or_(*conds), 
            UserProgress.next_review > datetime.utcnow()
        ).count()
        return render_template('quiz.html', finished=True, category=category_path, waiting_count=w)
    
    # Karte rendern (Delegate an utils)
    return render_learn_card(card, current_user, category_path)

@bp.route('/submit/<int:card_id>', methods=['POST'])
@login_required
def submit(card_id):
    try:
        # Lernzeit erfassen
        if request.form.get('start_time'): 
            try:
                d = datetime.utcnow().timestamp() - float(request.form.get('start_time'))
                if 0 < d < 600: # Max 10 Min pro Karte zählen
                    current_user.total_learning_time += int(d)
                    db.session.commit()
            except: pass
        
        card = Card.query.get_or_404(card_id)
        # Kontext bewahren (damit man nicht aus der Kategorie fliegt)
        origin = request.form.get('origin_path', card.category)
        
        # Optionen laden (für Feedback Anzeige)
        card_opts = []
        if card.options:
            try: card_opts = json.loads(card.options)
            except: card_opts = []

        # --- LOGIK JE NACH TYP ---

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
            
            de_ok = (ud == sd) if sd else True
            lat_ok = (ul == sl) if sl else True
            corr = (de_ok and lat_ok)
            
            update_progress(current_user, card, corr)
            award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_anatomy=True, result_de=(ud==sd), result_lat=(ul==sl if sl else True), box=p.box if p else 0, current_category=origin)
        
        elif card.type == 'anatomy_multi':
            sols = card_opts
            sub = True
            res = []
            for i in sols:
                rid = str(i.get('id'))
                ud = request.form.get(f"de_{rid}",'').strip().lower()
                ul = request.form.get(f"lat_{rid}",'').strip().lower()
                
                correct_de = i.get('de','').strip().lower() if i.get('de') else ""
                correct_lat = i.get('lat','').strip().lower() if i.get('lat') else ""
                
                cde = (ud == correct_de) if correct_de else True
                clat = (ul == correct_lat) if correct_lat else True
                
                if (correct_de and not cde) or (correct_lat and not clat): 
                    sub = False
                
                res.append({
                    'label': rid, 
                    'user_de': request.form.get(f"de_{rid}",''), 
                    'user_lat': request.form.get(f"lat_{rid}",''), 
                    'correct_de': i.get('de'), 
                    'correct_lat': i.get('lat'), 
                    'is_de_ok': cde, 
                    'is_lat_ok': clat
                })
                
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
                        all_c = False
                        st['correct'] = False
                        st['reason'] = 'wrong_group'
                    elif i < len(ci) and ci[i] == u: 
                        st['correct'] = True
                    else: 
                        all_c = False
                        st['correct'] = False
                        st['reason'] = 'wrong_order' # Falls Reihenfolge wichtig (hier vereinfacht angenommen)
                    gr['group_items'].append(st)
                
                for c in ci: 
                    if c not in ui: 
                        all_c = False
                        gr['missing'].append(c)
                res.append(gr)
                
            update_progress(current_user, card, all_c)
            award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_assignment=True, all_correct=all_c, assignment_results=res, box=p.box if p else 0, current_category=origin)

        # --- NEU: MEDIKAMENTEN RECHNER ---
        elif card.type == 'calculation':
            try:
                # Benutzereingabe (Komma zu Punkt)
                user_val = float(request.form.get('calc_input', '0').replace(',', '.'))
                # Der Zufallswert, der generiert wurde (wurde im Formular hidden übergeben)
                used_var = float(request.form.get('calc_var', '0')) 
                
                # Zielbereich berechnen
                # Antwortformat in DB: "0.125-0.25" oder "5"
                if '-' in card.answer:
                    f_min, f_max = map(float, card.answer.split('-'))
                else:
                    f_min = f_max = float(card.answer)
                
                target_min = used_var * f_min
                target_max = used_var * f_max
                
                # Prüfung: Liegt User im Bereich?
                # Wir runden auf 2 Stellen für den Vergleich, um Float-Probleme zu minimieren
                is_correct = (round(target_min, 3) <= round(user_val, 3) <= round(target_max, 3))
                
                result_text = f"Zielbereich: {target_min:.2f} - {target_max:.2f}"
                if card.options:
                    try: 
                        unit = json.loads(card.options).get('unit', '')
                        result_text += f" {unit}"
                    except: pass

            except ValueError:
                is_correct = False
                result_text = "Ungültige Eingabe"
                user_val = request.form.get('calc_input', '-')

            update_progress(current_user, card, is_correct)
            award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            
            # Daten rekonstruieren für Anzeige
            calc_data_reconstructed = {
                'val': used_var,
                'question': card.question.replace('{weight}', str(int(used_var) if used_var.is_integer() else used_var)),
                'unit': '' # Unit holen wir uns ggf. aus Optionen, aber für Anzeige reicht Frage
            }
            try: calc_data_reconstructed['unit'] = json.loads(card.options).get('unit','')
            except: pass

            return render_template('quiz.html', card=card, finished=False, feedback_calc=True, is_correct=is_correct, user_val=user_val, result_text=result_text, box=p.box if p else 0, current_category=origin, calc_data=calc_data_reconstructed)

        # --- NEU: FALLBEISPIELE (Behandlung wie Flashcard) ---
        elif card.type == 'case_study':
            try: 
                # Buttons senden values: "0", "3", "4", "5"
                quality = int(request.form.get('result', 0))
            except: quality = 0
            
            update_progress(current_user, card, quality)
            award_badges(current_user)
            # Bei Flashcards/Cases direkt zur nächsten Frage springen
            return redirect(url_for('learn.learn', category_path=origin))

        else: # Standard Flashcard
            try: quality = int(request.form.get('result', 0))
            except: quality = 0
            update_progress(current_user, card, quality)
            award_badges(current_user)
            return redirect(url_for('learn.learn', category_path=origin))
            
    except Exception as e: 
        print(f"ERROR submitting card {card_id}: {e}")
        flash("Ein Fehler ist aufgetreten. Bitte melden.", "danger")
        return redirect(url_for('main.index'))

@bp.route('/report/<int:card_id>', methods=['POST'])
@login_required
def report_card(card_id):
    reason = request.form.get('reason')
    if reason:
        db.session.add(CardReport(card_id=card_id, user_id=current_user.id, reason=reason))
        db.session.commit()
        flash('Frage wurde gemeldet.', 'success')
    return redirect(request.referrer or url_for('main.index'))

@bp.route('/learn/errors')
@login_required
def learn_errors():
    # Suche Karten, die im "Box 0" sind oder zuletzt falsch waren
    sub = UserProgress.query.filter(
        UserProgress.user_id == current_user.id, 
        or_(UserProgress.box == 0, UserProgress.last_correct == False)
    ).with_entities(UserProgress.card_id)
    
    card = Card.query.filter(Card.id.in_(sub)).order_by(func.random()).first()
    
    if not card: 
        flash("Keine Fehler gefunden! Alles gelernt.", "success")
        return redirect(url_for('main.index'))
    
    return render_learn_card(card, current_user, "errors")

@bp.route('/exam')
@login_required
def exam_index():
    # Nur automatisch prüfbare Typen für Prüfungen zulassen
    # (Flashcards und Fallbeispiele basieren auf Selbsteinschätzung -> ungeeignet für Auto-Exam)
    valid = ['mc', 'anatomy', 'anatomy_multi', 'ordering', 'assignment', 'calculation']
    questions = Card.query.filter(Card.type.in_(valid)).order_by(func.random()).limit(30).all()
    
    prepared = []
    for card in questions:
        opts = []
        calc_data = None
        
        if card.options:
            try: opts = json.loads(card.options)
            except: opts = []
            
        if card.type == 'mc': 
            opts = get_mc_options(card)
        elif card.type == 'ordering': 
            random.shuffle(opts)
        elif card.type == 'assignment':
             pool=[]; [([pool.append({'val':i, 'group':g.get('name')}) for i in g.get('items',[])] if isinstance(opts,list) else None) for g in (opts if isinstance(opts,list) else [])]; random.shuffle(pool)
             card.temp_pool = pool
        elif card.type == 'calculation':
            # Für Exam müssen wir einen festen Wert generieren, der nicht beim Submit neu gewürfelt wird.
            # Workaround: Wir speichern den Wert temporär im Template (Hidden Field)
            # import aus utils muss hier lokal passieren oder oben importiert sein
            from ..utils import prepare_calculation_card 
            calc_data = prepare_calculation_card(card)
             
        prepared.append({'card': card, 'options': opts, 'calc_data': calc_data})
        
    return render_template('exam.html', questions=prepared)

@bp.route('/exam/submit', methods=['POST'])
@login_required
def exam_submit():
    score = 0
    card_ids = request.form.getlist('card_ids')
    attempt = ExamAttempt(user_id=current_user.id, total_questions=len(card_ids))
    db.session.add(attempt)
    db.session.commit()
    
    for cid in card_ids:
        card = Card.query.get(int(cid))
        is_correct = False
        
        if card.type == 'mc':
            if request.form.get(f'q_{cid}') == card.answer: 
                is_correct = True
                
        elif card.type == 'calculation':
            # Logik analog zu submit(), aber Werte aus Exam-Formular holen
            try:
                u_val = float(request.form.get(f'calc_input_{cid}', '0').replace(',', '.'))
                u_var = float(request.form.get(f'calc_var_{cid}', '0'))
                
                if '-' in card.answer:
                    f_min, f_max = map(float, card.answer.split('-'))
                else:
                    f_min = f_max = float(card.answer)
                
                target_min = u_var * f_min
                target_max = u_var * f_max
                
                if round(target_min, 3) <= round(u_val, 3) <= round(target_max, 3):
                    is_correct = True
            except: is_correct = False

        # (Andere Typen für Exam müssten hier implementiert werden, z.B. anatomy Textvergleich)
        
        if is_correct: 
            score += 1
            add_xp(current_user, 10) # XP auch im Exam
            
        db.session.add(ExamDetail(attempt_id=attempt.id, question_text=card.question, question_type=card.type, is_correct=is_correct))
    
    attempt.score = score
    attempt.passed = (score >= (len(card_ids) * 0.6))
    
    # Bonus XP für bestandene Prüfung
    if attempt.passed:
        add_xp(current_user, 100)
        flash("Prüfung bestanden! +100 XP Bonus", "success")
        
    db.session.commit()
    return redirect(url_for('learn.review_exam', attempt_id=attempt.id))

@bp.route('/profile/exam/<int:attempt_id>')
@login_required
def review_exam(attempt_id):
    att = ExamAttempt.query.get_or_404(attempt_id)
    if att.user_id != current_user.id and not current_user.is_admin: 
        flash("Zugriff verweigert", "danger")
        return redirect(url_for('main.profile'))
    
    res = [{'question':d.question_text, 'type':d.question_type, 'is_correct':d.is_correct} for d in att.details]
    return render_template('exam_result.html', score=att.score, total=att.total_questions, passed=att.passed, results=res, date=att.timestamp)

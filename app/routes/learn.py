import json
import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy.sql.expression import func, or_
from ..extensions import db
from ..models import Card, UserProgress, ExamAttempt, ExamDetail, CardReport
from ..utils import get_next_card, update_progress, award_badges, render_learn_card, get_mc_options

bp = Blueprint('learn', __name__)

@bp.route('/learn/custom', methods=['POST'])
@login_required
def learn_custom():
    cats = request.form.getlist('categories')
    if not cats: flash("Kategorie wählen", "warning"); return redirect(url_for('main.index'))
    return redirect(url_for('learn.learn', category_path="|".join(cats)))

@bp.route('/learn/<path:category_path>')
@login_required
def learn(category_path):
    paths = category_path.split('|'); f = request.args.get('force') == 'true'
    card, p = get_next_card(current_user, paths, force=f)
    if not card: 
        conds = [Card.category.like(f"{p}%") for p in paths]
        w = UserProgress.query.join(Card).filter(UserProgress.user_id==current_user.id, or_(*conds), UserProgress.next_review>datetime.utcnow()).count()
        return render_template('quiz.html', finished=True, category=category_path, waiting_count=w)
    return render_learn_card(card, current_user, category_path)

@bp.route('/submit/<int:card_id>', methods=['POST'])
@login_required
def submit(card_id):
    try:
        if request.form.get('start_time'): 
            try: d = datetime.utcnow().timestamp()-float(request.form.get('start_time')); 
            except: d=0
            if 0<d<600: current_user.total_learning_time+=int(d); db.session.commit()
        
        card = Card.query.get_or_404(card_id)
        origin = request.form.get('origin_path', card.category)
        
        card_opts = []
        if card.options:
            try: card_opts = json.loads(card.options)
            except: card_opts = []

        if card.type=='mc':
            u=request.form.get('mc_answer'); corr=(u==card.answer)
            update_progress(current_user, card, corr); award_badges(current_user)
            opts_feedback = get_mc_options(card)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, options=opts_feedback, finished=False, feedback=True, user_answer=u, is_correct=corr, box=p.box if p else 0, current_category=origin)
        
        elif card.type=='anatomy':
            ud=request.form.get('input_de','').lower(); ul=request.form.get('input_lat','').lower()
            sd=card.answer.lower() if card.answer else ""; sl=card.answer_lat.lower() if card.answer_lat else ""
            de_ok = (ud == sd) if sd else True; lat_ok = (ul == sl) if sl else True
            corr = (de_ok and lat_ok); update_progress(current_user, card, corr); award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_anatomy=True, result_de=(ud==sd), result_lat=(ul==sl if sl else True), box=p.box if p else 0, current_category=origin)
        
        # ... (Anatomy Multi, Ordering, Assignment hier analog zur alten app.py einfügen, nur render_template Pfad beachten) ...
        # (Ich kürze das hier etwas ab, der Code ist identisch zur alten submit() Funktion, nur return render_template(...) braucht current_category=origin)
        elif card.type=='anatomy_multi':
            sols=card_opts; sub=True; res=[]
            for i in sols:
                rid=str(i.get('id')); ud=request.form.get(f"de_{rid}",'').lower(); ul=request.form.get(f"lat_{rid}",'').lower()
                correct_de = i.get('de','').lower() if i.get('de') else ""; correct_lat = i.get('lat','').lower() if i.get('lat') else ""
                cde = (ud == correct_de) if correct_de else True; clat = (ul == correct_lat) if correct_lat else True
                if (correct_de and not cde) or (correct_lat and not clat): sub=False
                res.append({'label':rid, 'user_de':ud, 'user_lat':ul, 'correct_de':i.get('de'), 'correct_lat':i.get('lat'), 'is_de_ok':cde, 'is_lat_ok':clat})
            update_progress(current_user, card, sub); award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_multi=True, multi_results=res, all_correct=sub, box=p.box if p else 0, current_category=origin)

        elif card.type=='ordering':
            try: uo = json.loads(request.form.get('order_json', '[]'))
            except: uo = []
            corr = (uo==card_opts)
            update_progress(current_user, card, corr); award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_ordering=True, user_order=uo, correct_order=card_opts, is_correct=corr, box=p.box if p else 0, current_category=origin)

        elif card.type=='assignment':
            try: ud = json.loads(request.form.get('assignment_json', '{}'))
            except: ud = {}
            all_c=True; res=[]
            for g in card_opts:
                gn=g.get('name'); ci=g.get('items',[]); ui=ud.get(gn,[]); gr={'name':gn,'group_items':[],'missing':[]}
                for i, u in enumerate(ui):
                    st={'text':u}; 
                    if u not in ci: all_c=False; st['correct']=False; st['reason']='wrong_group'
                    elif i<len(ci) and ci[i]==u: st['correct']=True
                    else: all_c=False; st['correct']=False; st['reason']='wrong_order'
                    gr['group_items'].append(st)
                for c in ci: 
                    if c not in ui: all_c=False; gr['missing'].append(c)
                res.append(gr)
            update_progress(current_user, card, all_c); award_badges(current_user)
            p = UserProgress.query.filter_by(user_id=current_user.id, card_id=card.id).first()
            return render_template('quiz.html', card=card, finished=False, feedback_assignment=True, all_correct=all_c, assignment_results=res, box=p.box if p else 0, current_category=origin)

        else: # Flashcard
            try: quality = int(request.form.get('result', 0))
            except: quality = 0
            update_progress(current_user, card, quality); award_badges(current_user)
            return redirect(url_for('learn.learn', category_path=origin))
    except Exception as e: print(f"ERROR: {e}"); return "Fehler beim Auswerten", 500

@bp.route('/report/<int:card_id>', methods=['POST'])
@login_required
def report_card(card_id):
    reason = request.form.get('reason')
    if reason:
        db.session.add(CardReport(card_id=card_id, user_id=current_user.id, reason=reason)); db.session.commit()
        flash('Gemeldet.', 'success')
    return redirect(request.referrer or url_for('main.index'))

@bp.route('/learn/errors')
@login_required
def learn_errors():
    sub = UserProgress.query.filter(UserProgress.user_id == current_user.id, or_(UserProgress.box == 0, UserProgress.last_correct == False)).with_entities(UserProgress.card_id)
    card = Card.query.filter(Card.id.in_(sub)).order_by(func.random()).first()
    if not card: flash("Keine Fehler gefunden!", "success"); return redirect(url_for('main.index'))
    return render_learn_card(card, current_user, "errors")

@bp.route('/exam')
@login_required
def exam_index():
    valid = ['mc', 'anatomy', 'anatomy_multi', 'ordering', 'assignment']
    questions = Card.query.filter(Card.type.in_(valid)).order_by(func.random()).limit(30).all()
    prepared = []
    for card in questions:
        opts = []
        if card.options:
            try: opts = json.loads(card.options)
            except: opts = []
        if card.type == 'mc': opts = get_mc_options(card)
        elif card.type == 'ordering': random.shuffle(opts)
        elif card.type == 'assignment':
             pool=[]; [([pool.append({'val':i, 'group':g.get('name')}) for i in g.get('items',[])] if isinstance(opts,list) else None) for g in (opts if isinstance(opts,list) else [])]; random.shuffle(pool); card.temp_pool = pool
        prepared.append({'card': card, 'options': opts})
    return render_template('exam.html', questions=prepared)

@bp.route('/exam/submit', methods=['POST'])
@login_required
def exam_submit():
    score = 0; card_ids = request.form.getlist('card_ids')
    attempt = ExamAttempt(user_id=current_user.id, total_questions=len(card_ids)); db.session.add(attempt); db.session.commit()
    for cid in card_ids:
        card = Card.query.get(int(cid)); is_correct = False
        if card.type == 'mc' and request.form.get(f'q_{cid}') == card.answer: is_correct = True
        # (Weitere Typen für Exam hier)
        if is_correct: score += 1
        db.session.add(ExamDetail(attempt_id=attempt.id, question_text=card.question, question_type=card.type, is_correct=is_correct))
    attempt.score = score; attempt.passed = (score >= (len(card_ids) * 0.6)); db.session.commit()
    return redirect(url_for('learn.review_exam', attempt_id=attempt.id))

@bp.route('/profile/exam/<int:attempt_id>')
@login_required
def review_exam(attempt_id):
    att = ExamAttempt.query.get_or_404(attempt_id)
    if att.user_id != current_user.id and not current_user.is_admin: flash("Verboten", "danger"); return redirect(url_for('main.profile'))
    res = [{'question':d.question_text, 'type':d.question_type, 'is_correct':d.is_correct} for d in att.details]
    return render_template('exam_result.html', score=att.score, total=att.total_questions, passed=att.passed, results=res, date=att.timestamp)

import json
import random
import difflib
from datetime import datetime, timedelta
from flask import render_template, flash
from sqlalchemy import func
from sqlalchemy.sql.expression import or_
from .extensions import db
from .models import UserProgress, Card, Badge

def fuzzy_match(user_input, correct_answer, threshold=0.85):
    """Prüft Übereinstimmung unter Berücksichtigung von Tippfehlern."""
    target = correct_answer.strip().lower() if correct_answer else ""
    if target in ['-', '%', '']: return True
    inp = user_input.strip().lower() if user_input else ""
    if not inp: return False
    return difflib.SequenceMatcher(None, inp, target).ratio() >= threshold

def check_gamification(user):
    """Aktualisiert Streaks und Aktivität."""
    today = datetime.utcnow().date()
    last = user.last_active.date() if user.last_active else None
    if last != today:
        if last == today - timedelta(days=1): user.streak += 1
        else: user.streak = 1
        user.last_active = datetime.utcnow(); db.session.commit()

def add_xp(user, amount):
    """Vergibt XP und prüft Level-Ups."""
    old_level = user.get_level()
    user.xp += amount
    db.session.commit()
    new_level = user.get_level()
    if new_level > old_level:
        flash(f"🎉 LEVEL UP! Du bist jetzt Level {new_level}!", "success")

def award_badges(user):
    """Prüft und vergibt Auszeichnungen."""
    checks = [("Erster Schritt", "Erste Frage", lambda u: UserProgress.query.filter_by(user_id=u.id).count() >= 1),
              ("Dauerbrenner", "5er Streak", lambda u: u.streak >= 5),
              ("Profi", "Level 5 erreicht", lambda u: u.get_level() >= 5)]
    new = []
    for n, d, f in checks:
        if f(user):
            b = Badge.query.filter_by(name=n).first()
            if not b: b = Badge(name=n, description=d); db.session.add(b); db.session.commit()
            if b not in user.badges: user.badges.append(b); new.append(n)
    if new: db.session.commit(); flash(f"🏆 Neue Auszeichnung: {', '.join(new)}", "warning")

def get_next_card(user, paths, force=False, exclude_id=None):
    """Sucht die nächste fällige Karte basierend auf Spaced Repetition."""
    now = datetime.utcnow()
    conditions = [Card.category.like(f"{p}%") for p in paths]
    filter_cond = or_(*conditions)
    due_query = UserProgress.query.join(Card).filter(UserProgress.user_id==user.id, filter_cond)
    if exclude_id: due_query = due_query.filter(Card.id != exclude_id)
    if not force: 
        due = due_query.filter(UserProgress.next_review <= now).order_by(func.random()).first()
        if due: return due.card, due
    sub = db.session.query(UserProgress.card_id).filter(UserProgress.user_id==user.id)
    new_query = Card.query.filter(filter_cond, ~Card.id.in_(sub))
    if exclude_id: new_query = new_query.filter(Card.id != exclude_id)
    new = new_query.order_by(func.random()).first()
    if not new and force:
        fallback_query = UserProgress.query.join(Card).filter(UserProgress.user_id==user.id, filter_cond)
        res = fallback_query.filter(Card.id != exclude_id).order_by(func.random()).first() if exclude_id else fallback_query.order_by(func.random()).first()
        return (res.card, None) if res else (None, None)
    if not new and exclude_id: return get_next_card(user, paths, force=force, exclude_id=None)
    return new, None

def update_progress(user, card, quality):
    """Berechnet das nächste Intervall (SM-2 Algorithmus)."""
    if isinstance(quality, bool): quality = 4 if quality else 0
    xp_map = {0: 1, 3: 5, 4: 10, 5: 15}
    add_xp(user, xp_map.get(quality, 0))
    p = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first()
    if not p: p = UserProgress(user_id=user.id, card_id=card.id, box=0, easiness_factor=2.5, interval=0); db.session.add(p)
    p.last_correct = (quality >= 3)
    if quality >= 3:
        if p.box == 0: p.interval = 1
        elif p.box == 1: p.interval = 6
        else: p.interval = int(p.interval * p.easiness_factor)
        if p.interval > 3: p.interval = int(p.interval * random.uniform(0.9, 1.1))
        p.box += 1
    else:
        p.box = 0; p.interval = 0
    p.easiness_factor = max(1.3, p.easiness_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    delta = timedelta(minutes=5) if p.interval == 0 else timedelta(days=p.interval)
    p.next_review = datetime.utcnow() + delta
    db.session.commit()

def get_learning_stats(user):
    """Berechnet globale Statistiken."""
    if not user.is_authenticated: return {'total':0, 'learned':0, 'due':0, 'new':0, 'f24':0, 'f48':0, 'error_categories':[]}
    now = datetime.utcnow()
    total = Card.query.count()
    learned = UserProgress.query.filter(UserProgress.user_id==user.id, UserProgress.box>0).count()
    due = UserProgress.query.filter(UserProgress.user_id==user.id, UserProgress.next_review <= now).count()
    f24 = UserProgress.query.filter(UserProgress.user_id==user.id, UserProgress.next_review > now, UserProgress.next_review <= now + timedelta(hours=24)).count()
    f48 = UserProgress.query.filter(UserProgress.user_id==user.id, UserProgress.next_review > now, UserProgress.next_review <= now + timedelta(hours=48)).count()
    error_cats = db.session.query(Card.category, func.count(Card.id))\
        .join(UserProgress)\
        .filter(UserProgress.user_id == user.id, or_(UserProgress.box == 0, UserProgress.last_correct == False))\
        .group_by(Card.category)\
        .order_by(func.count(Card.id).desc())\
        .limit(3).all()
    return {
        'total': total, 'learned': learned, 'due': due, 'new': total - UserProgress.query.filter_by(user_id=user.id).count(),
        'f24': f24, 'f48': f48, 'error_categories': error_cats
    }

def build_category_tree(user):
    """OPTIMIERT: Erstellt den Baum mittels Datenbank-Aggregation (extrem schnell bei 5000+ Fragen)."""
    tree = {}
    total_stats = db.session.query(Card.category, func.count(Card.id)).group_by(Card.category).order_by(Card.category).all()
    learned_stats = {}
    if user.is_authenticated:
        learned_results = db.session.query(Card.category, func.count(Card.id))\
            .join(UserProgress, UserProgress.card_id == Card.id)\
            .filter(UserProgress.user_id == user.id, UserProgress.box > 0)\
            .group_by(Card.category).all()
        learned_stats = {cat: count for cat, count in learned_results}
    for category_path, total_count in total_stats:
        if not category_path: continue
        parts = category_path.split('/')
        learned_count = learned_stats.get(category_path, 0)
        current = tree
        for i, part in enumerate(parts):
            if part not in current:
                current[part] = {'_subs': {}, '_stats': {'total': 0, 'learned': 0}, '_path': "/".join(parts[:i+1])}
            current[part]['_stats']['total'] += total_count
            current[part]['_stats']['learned'] += learned_count
            current = current[part]['_subs']
    return tree

def get_mc_options(card):
    """Generiert Multiple-Choice-Optionen."""
    try: opts = json.loads(card.options) if card.options else []
    except: opts = []
    if card.answer and card.answer not in opts: opts.append(card.answer)
    random.shuffle(opts)
    return opts

def prepare_calculation_card(card):
    """Bereitet Rechenaufgaben vor."""
    try: config = json.loads(card.options)
    except: config = {}
    var_name = config.get('var', 'x')
    val = random.randrange(config.get('min', 1), config.get('max', 100) + 1, config.get('step', 1))
    return {'val': val, 'question': card.question.replace(f"{{{var_name}}}", str(val)), 'unit': config.get('unit', '')}

def render_learn_card(card, user, context_path):
    """Rendert die Quiz-Ansicht."""
    p = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first(); box = p.box if p else 0
    opts = []
    
    # HIER FEHLTE 'anatomy_multi' -> Dadurch wurde [] ans Template geschickt!
    if card.type == 'mc': opts = get_mc_options(card)
    elif card.type in ['ordering', 'assignment', 'anatomy_multi']: 
        try: opts = json.loads(card.options)
        except: opts = []
        
    calc_data = prepare_calculation_card(card) if card.type == 'calculation' else None
    pool = []
    if card.type == 'assignment':
        for g in opts:
            for i in g.get('items', []): pool.append({'val': i, 'group': g.get('name')})
        random.shuffle(pool)
    return render_template('quiz.html', card=card, options=opts, pool_items=pool, finished=False, box=box, current_category=context_path, calc_data=calc_data)

import json
import random
from datetime import datetime, timedelta
from flask import render_template, flash
from sqlalchemy.sql.expression import func, or_
from .extensions import db
from .models import UserProgress, Card, Badge

def check_gamification(user):
    today = datetime.utcnow().date()
    last = user.last_active.date() if user.last_active else None
    if last != today:
        if last == today - timedelta(days=1): user.streak += 1
        else: user.streak = 1
        user.last_active = datetime.utcnow(); db.session.commit()

def add_xp(user, amount):
    # XP hinzufügen und prüfen, ob Level-Up
    old_level = user.get_level()
    user.xp += amount
    db.session.commit()
    new_level = user.get_level()
    if new_level > old_level:
        flash(f"🎉 LEVEL UP! Du bist jetzt Level {new_level}!", "success")

def award_badges(user):
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

def get_next_card(user, paths, force=False):
    now = datetime.utcnow()
    conditions = [Card.category.like(f"{p}%") for p in paths]
    filter_cond = or_(*conditions)
    query = UserProgress.query.join(Card).filter(UserProgress.user_id==user.id, filter_cond)
    if not force: due = query.filter(UserProgress.next_review <= now).order_by(func.random()).first()
    else: due = query.order_by(func.random()).first()
    if due: return due.card, due
    sub = db.session.query(UserProgress.card_id).filter(UserProgress.user_id==user.id)
    new = Card.query.filter(filter_cond, ~Card.id.in_(sub)).order_by(func.random()).first()
    return new, None

def update_progress(user, card, quality):
    # XP Vergabe: 10 XP für Richtig, 2 XP für Falsch (Trostpreis)
    if isinstance(quality, bool): 
        quality = 4 if quality else 0
        add_xp(user, 10 if quality >= 3 else 2)
    else:
        # Bei Flashcards: 3-5 gibt mehr XP
        xp_map = {0: 1, 3: 5, 4: 10, 5: 15}
        add_xp(user, xp_map.get(quality, 0))

    p = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first()
    if not p: p = UserProgress(user_id=user.id, card_id=card.id, box=0, easiness_factor=2.5, interval=0); db.session.add(p)
    p.last_correct = (quality >= 3)
    if quality >= 3:
        if p.box == 0: p.interval = 1
        elif p.box == 1: p.interval = 6
        else: p.interval = int(p.interval * p.easiness_factor)
        p.box += 1
    else:
        p.box = 0; p.interval = 0
    p.easiness_factor = p.easiness_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if p.easiness_factor < 1.3: p.easiness_factor = 1.3
    if p.interval == 0: delta = timedelta(minutes=3)
    else: delta = timedelta(days=p.interval)
    p.next_review = datetime.utcnow() + delta; db.session.commit()

def build_category_tree(cards, user):
    tree = {}
    for c in cards:
        parts = c.category.split('/')
        current = tree
        learned = False
        if user.is_authenticated:
            p = UserProgress.query.filter_by(user_id=user.id, card_id=c.id).first()
            if p and p.box > 0: learned = True
        for i, part in enumerate(parts):
            if part not in current: current[part] = {'_subs': {}, '_stats': {'total':0,'learned':0}, '_path': "/".join(parts[:i+1])}
            current[part]['_stats']['total'] += 1
            if learned: current[part]['_stats']['learned'] += 1
            current = current[part]['_subs']
    return tree

def get_mc_options(card):
    try: opts = json.loads(card.options) if card.options else []
    except: opts = []
    if not isinstance(opts, list): opts = []
    if card.answer and card.answer not in opts: opts.append(card.answer)
    random.shuffle(opts)
    return opts

# --- RECHNER LOGIK ---
def prepare_calculation_card(card):
    # Optionen: {"var": "weight", "min": 50, "max": 120, "step": 5}
    # Frage: "Patient {weight} kg..."
    try: config = json.loads(card.options)
    except: config = {}
    
    var_name = config.get('var', 'x')
    min_val = config.get('min', 1)
    max_val = config.get('max', 100)
    step = config.get('step', 1)
    
    # Zufallswert generieren
    val = random.randrange(min_val, max_val + 1, step)
    
    # Platzhalter in Frage ersetzen
    question_text = card.question.replace(f"{{{var_name}}}", str(val))
    
    return {'val': val, 'question': question_text, 'unit': config.get('unit', '')}

def render_learn_card(card, user, context_path):
    p = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first(); box = p.box if p else 0
    try: opts = json.loads(card.options) if card.options else []
    except: opts = []
    
    if card.type == 'mc': opts = get_mc_options(card)
    elif card.type == 'ordering': random.shuffle(opts)
    elif card.type == 'calculation':
        # Spezialfall: Dynamische Berechnung
        calc_data = prepare_calculation_card(card)
        return render_template('quiz.html', card=card, finished=False, box=box, current_category=context_path, calc_data=calc_data)
    elif card.type == 'assignment':
        pool=[]; [([pool.append({'val':i, 'group':g.get('name')}) for i in g.get('items',[])] if isinstance(opts,list) else None) for g in (opts if isinstance(opts,list) else [])]; random.shuffle(pool)
        return render_template('quiz.html', card=card, options=opts, pool_items=pool, finished=False, box=box, current_category=context_path)
    
    return render_template('quiz.html', card=card, options=opts, finished=False, box=box, current_category=context_path)

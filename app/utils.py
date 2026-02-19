import json
import random
import difflib
from datetime import datetime, timedelta, timezone
from flask import render_template, flash
from sqlalchemy import func
from sqlalchemy.sql.expression import or_
from fsrs import FSRS, Card as FSRSCard, Rating, State
from .extensions import db
from .models import UserProgress, Card, Badge

# Globale FSRS Instanz initialisieren
fsrs_scheduler = FSRS()

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
    """Sucht die nächste fällige Karte basierend auf FSRS und Dringlichkeit mit Tageslimits."""
    now = datetime.utcnow()
    conditions = [Card.category.like(f"{p}%") for p in paths]
    filter_cond = or_(*conditions)
    
    due_query = UserProgress.query.join(Card).filter(UserProgress.user_id==user.id, filter_cond)
    if exclude_id: 
        due_query = due_query.filter(Card.id != exclude_id)
        
    # --- TAGESLIMITS DEFINIEREN ---
    MAX_REVIEWS_PER_DAY = 100  # Maximal 100 alte Fragen pro Tag wiederholen
    MAX_NEW_CARDS_PER_DAY = 30 # Maximal 30 komplett neue Fragen pro Tag lernen
    
    # Der Startpunkt des heutigen Tages für die Zählung (00:00 Uhr)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if not force: 
        # 1. PRÜFE WIEDERHOLUNGEN (Reviews)
        # Zähle alle Karten, die heute schon wiederholt wurden (reps > 1 schließt Erstkontakte aus)
        reviews_done_today = UserProgress.query.filter(
            UserProgress.user_id == user.id,
            UserProgress.last_review >= today_start,
            UserProgress.reps > 1  
        ).count()
        
        # Nur wenn das Limit noch nicht erreicht ist, zeigen wir fällige Karten an
        if reviews_done_today < MAX_REVIEWS_PER_DAY:
            due = due_query.filter(UserProgress.next_review <= now)\
                           .order_by(UserProgress.next_review.asc()).first()
            if due: 
                return due.card, due

    # 2. PRÜFE NEUE KARTEN (Wird erreicht, wenn alle Reviews für heute fertig oder limitiert sind)
    new_cards_learned_today = UserProgress.query.filter(
        UserProgress.user_id == user.id,
        UserProgress.reps == 1, 
        UserProgress.last_review >= today_start
    ).count()

    if new_cards_learned_today < MAX_NEW_CARDS_PER_DAY:
        sub = db.session.query(UserProgress.card_id).filter(UserProgress.user_id==user.id)
        new_query = Card.query.filter(filter_cond, ~Card.id.in_(sub))
        if exclude_id: 
            new_query = new_query.filter(Card.id != exclude_id)
            
        new = new_query.order_by(Card.id.asc()).first()
    else:
        new = None # Beide Limits (Reviews und Neue) sind für heute erreicht
    
    # 3. FALLBACKS & ERZWUNGENES LERNEN
    if not new and force:
        res = due_query.order_by(func.random()).first()
        return (res.card, None) if res else (None, None)
        
    if not new and exclude_id: 
        return get_next_card(user, paths, force=force, exclude_id=None)
        
    return new, None

def update_progress(user, card, quality):
    """Berechnet das nächste Intervall (FSRS Algorithmus)."""
    # 1. XP berechnen und vergeben
    xp_map = {0: 1, 3: 5, 4: 10, 5: 15}
    q_val = 4 if isinstance(quality, bool) and quality else (0 if isinstance(quality, bool) else quality)
    add_xp(user, xp_map.get(q_val, 0))
    
    # 2. Progress laden oder neu anlegen
    p = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first()
    if not p: 
        p = UserProgress(user_id=user.id, card_id=card.id)
        db.session.add(p)
        
    # 3. FSRS-Karte initialisieren
    fsrs_card = FSRSCard()
    
    # FIX: "or 0" verhindert Abstürze bei alten Datenbankeinträgen, die noch auf NULL/None stehen
    reps = p.reps or 0
    if reps > 0:
        fsrs_card.state = State(p.state or 0)
        fsrs_card.stability = p.stability or 0.0
        fsrs_card.difficulty = p.difficulty or 0.0
        fsrs_card.elapsed_days = p.elapsed_days or 0
        fsrs_card.scheduled_days = p.scheduled_days or 0
        fsrs_card.reps = reps
        fsrs_card.lapses = p.lapses or 0
        if p.last_review:
            fsrs_card.last_review = p.last_review.replace(tzinfo=timezone.utc)
        
    # 4. Deine Quality-Buttons auf FSRS-Ratings mappen
    if q_val <= 2: rating = Rating.Again
    elif q_val == 3: rating = Rating.Hard
    elif q_val == 4: rating = Rating.Good
    else: rating = Rating.Easy

    # 5. Nächstes Intervall berechnen lassen
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    scheduling_cards = fsrs_scheduler.repeat(fsrs_card, now)
    scheduled_card = scheduling_cards[rating].card
    
    # 6. Ergebnisse zurück in die Datenbank schreiben
    p.state = int(scheduled_card.state)
    p.stability = scheduled_card.stability
    p.difficulty = scheduled_card.difficulty
    p.elapsed_days = scheduled_card.elapsed_days
    p.scheduled_days = scheduled_card.scheduled_days
    p.reps = scheduled_card.reps
    p.lapses = scheduled_card.lapses
    p.last_review = now.replace(tzinfo=None)
    p.next_review = scheduled_card.due.replace(tzinfo=None)
    
    # UI-Box aktualisieren
    p.last_correct = (rating != Rating.Again)
    if rating != Rating.Again:
        p.box = (p.box or 0) + 1 # Auch hier zur Sicherheit "or 0"
    else:
        p.box = 0
        
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

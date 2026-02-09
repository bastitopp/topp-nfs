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

def award_badges(user):
    checks = [("Erster Schritt", "Erste Frage", lambda u: UserProgress.query.filter_by(user_id=u.id).count() >= 1),
              ("Dauerbrenner", "5er Streak", lambda u: u.streak >= 5)]
    new = []
    for n, d, f in checks:
        if f(user):
            b = Badge.query.filter_by(name=n).first()
            if not b: b = Badge(name=n, description=d); db.session.add(b); db.session.commit()
            if b not in user.badges: user.badges.append(b); new.append(n)
    if new: db.session.commit(); flash(f"🎉 Neu: {', '.join(new)}", "warning")

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
    if isinstance(quality, bool): quality = 4 if quality else 0
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

def render_learn_card(card, user, context_path):
    p = UserProgress.query.filter_by(user_id=user.id, card_id=card.id).first(); box = p.box if p else 0
    try: opts = json.loads(card.options) if card.options else []
    except: opts = []
    
    if card.type == 'mc': opts = get_mc_options(card)
    elif card.type=='ordering': random.shuffle(opts)
    elif card.type=='assignment':
        pool=[]; [([pool.append({'val':i, 'group':g.get('name')}) for i in g.get('items',[])] if isinstance(opts,list) else None) for g in (opts if isinstance(opts,list) else [])]; random.shuffle(pool)
        return render_template('quiz.html', card=card, options=opts, pool_items=pool, finished=False, box=box, current_category=context_path)
    
    return render_template('quiz.html', card=card, options=opts, finished=False, box=box, current_category=context_path)

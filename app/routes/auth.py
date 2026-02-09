from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from flask_mail import Message
from ..extensions import db, mail, limiter
from ..models import User
from itsdangerous import URLSafeTimedSerializer
from flask import current_app

bp = Blueprint('auth', __name__)

def get_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method=='POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and u.check_password(request.form['password']): login_user(u); return redirect(url_for('main.index'))
        flash('Fehler: Benutzer oder Passwort falsch', 'danger')
    return render_template('login.html')

@bp.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('main.index'))

@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            s = get_serializer(); token = s.dumps(user.email, salt='password-reset-salt')
            link = url_for('auth.reset_password_with_token', token=token, _external=True)
            try:
                msg = Message('Passwort zurücksetzen', recipients=[user.email])
                msg.body = f'Link: {link}'
                mail.send(msg)
            except Exception as e: print("Mail Error:", e)
        flash('Link gesendet.', 'info'); return redirect(url_for('auth.login'))
    return render_template('forgot_password.html')

@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    s = get_serializer()
    try: email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except: flash('Link ungültig.', 'danger'); return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        if request.form.get('password') != request.form.get('confirm'): flash('Ungleiche Passwörter', 'warning')
        else:
            u = User.query.filter_by(email=email).first()
            if u: u.set_password(request.form.get('password')); db.session.commit(); flash('OK!', 'success'); return redirect(url_for('auth.login'))
    return render_template('reset_password.html')

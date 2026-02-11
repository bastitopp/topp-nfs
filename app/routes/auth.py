from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from flask_mail import Message
from ..extensions import db, mail, limiter
from ..models import User
from itsdangerous import URLSafeTimedSerializer
from flask import current_app
import traceback

bp = Blueprint('auth', __name__)

def get_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method=='POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and u.check_password(request.form['password']): 
            # Checkbox 'remember' auslesen
            remember = True if request.form.get('remember') else False
            login_user(u, remember=remember)
            
            # Aktualisiere last_active für Gamification
            from datetime import datetime
            u.last_active = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('main.index'))
        flash('Fehler: Benutzer oder Passwort falsch', 'danger')
    return render_template('login.html')

@bp.route('/logout')
@login_required
def logout(): 
    logout_user()
    flash('Du wurdest ausgeloggt.', 'info')
    return redirect(url_for('auth.login'))

@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            s = get_serializer()
            token = s.dumps(user.email, salt='password-reset-salt')
            link = url_for('auth.reset_password_with_token', token=token, _external=True)
            
            try:
                print(f"--- VERSUCHE MAIL ZU SENDEN AN: {user.email} ---")
                msg = Message('Passwort zurücksetzen - Topp-NFS', recipients=[user.email])
                msg.body = f'Klicke auf den Link um dein Passwort zurückzusetzen: {link}\n\nLink ist 1 Stunde gültig.'
                mail.send(msg)
                print("--- MAIL ERFOLGREICH AN SMTP ÜBERGEBEN ---")
                flash('Link gesendet. Bitte Postfach prüfen.', 'info')
            except Exception as e:
                print(f"--- MAIL FEHLER: {e} ---")
                traceback.print_exc()
                flash(f'Fehler beim Senden: {str(e)}', 'danger')
        else:
            flash('Wenn die E-Mail existiert, wurde ein Link gesendet.', 'info')
            
        return redirect(url_for('auth.login'))
    return render_template('forgot_password.html')

@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    s = get_serializer()
    try: 
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except: 
        flash('Der Link ist ungültig oder abgelaufen.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        pw = request.form.get('password')
        conf = request.form.get('confirm')
        
        if pw != conf: 
            flash('Passwörter stimmen nicht überein', 'warning')
        else:
            u = User.query.filter_by(email=email).first()
            if u: 
                u.set_password(pw)
                db.session.commit()
                flash('Passwort erfolgreich geändert! Bitte einloggen.', 'success')
                return redirect(url_for('auth.login'))
            else:
                flash('Benutzer nicht gefunden.', 'danger')
                
    return render_template('reset_password.html')

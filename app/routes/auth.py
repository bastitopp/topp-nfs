from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from flask_mail import Message
from ..extensions import db, mail, limiter
from ..models import User
from itsdangerous import URLSafeTimedSerializer
from flask import current_app
import traceback
from datetime import datetime

bp = Blueprint('auth', __name__)

def get_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'POST':
        # Der identifier kann nun Benutzername oder E-Mail sein
        identifier = request.form['username']
        password = request.form['password']
        
        # Suche in der Datenbank nach Übereinstimmung in beiden Spalten
        u = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
        
        if u and u.check_password(password): 
            # Prüfen ob Account freigeschaltet ist
            if not u.is_approved:
                flash('Dein Account muss erst von einem Administrator freigeschaltet werden.', 'warning')
                return redirect(url_for('auth.login'))
                
            remember = True if request.form.get('remember') else False
            login_user(u, remember=remember)
            
            u.last_active = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('main.index'))
            
        flash('Fehler: Benutzer/E-Mail oder Passwort falsch', 'danger')
    return render_template('login.html')

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        real_name = request.form.get('real_name', '').strip()
        password = request.form.get('password', '')
        
        # Validierung
        if len(password) < 8:
            flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'danger')
            return redirect(url_for('auth.register'))
            
        if User.query.filter(User.username.ilike(username)).first():
            flash('Dieser Benutzername ist leider bereits vergeben.', 'danger')
            return redirect(url_for('auth.register'))
            
        if User.query.filter(User.email.ilike(email)).first():
            flash('Diese E-Mail-Adresse ist bereits registriert.', 'danger')
            return redirect(url_for('auth.register'))
            
        # Neuen (nicht freigeschalteten) Nutzer anlegen
        new_user = User(username=username, email=email, real_name=real_name, is_approved=False)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        # Admin-Benachrichtigung senden
        try:
            admins = User.query.filter_by(is_admin=True).all()
            # NEU: Filtert ungültige E-Mails wie "None" heraus
            admin_emails = [a.email for a in admins if a.email and '@' in a.email]
            if admin_emails:
                msg = Message('Neue Registrierung - Freischaltung erforderlich', recipients=admin_emails)
                msg.body = f'Hallo Admin,\n\nein neuer Benutzer "{username}" ({real_name}) hat sich soeben registriert.\nBitte logge dich in das Admin-Dashboard ein, um den Account freizuschalten:\n{url_for("admin.admin_users", _external=True)}'
                mail.send(msg)
        except Exception as e:
            print(f"Fehler beim Senden der Admin-Mail: {e}")
            
        flash('Registrierung abgeschickt. Nach erfolgreicher Freigabe bekommen Sie eine E-Mail zur Bestätigung.', 'success')
        return redirect(url_for('auth.login'))
        
    return render_template('register.html')

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
                msg = Message('Passwort zurücksetzen - Topp-NFS', recipients=[user.email])
                msg.body = f'Klicke auf den Link, um dein Passwort zurückzusetzen: {link}\n\nDer Link ist 1 Stunde gültig.'
                mail.send(msg)
                flash('Link gesendet. Bitte Postfach prüfen.', 'info')
            except Exception as e:
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

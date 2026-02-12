import os
from datetime import datetime
import markdown
from markupsafe import Markup
from flask import Flask
from .extensions import db, mail, login_manager, limiter
from .models import User

def create_app():
    app = Flask(__name__)
    
    # --- BASIS KONFIGURATION ---
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'geheimnis_fuer_topp_nfs_dev_key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///local.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = 'static/uploads'
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

    # --- E-MAIL KONFIGURATION ---
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
    
    try:
        app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    except ValueError:
        app.config['MAIL_PORT'] = 587

    use_tls = os.getenv('MAIL_USE_TLS', 'False').lower() in ['true', 'on', '1']
    use_ssl = os.getenv('MAIL_USE_SSL', 'False').lower() in ['true', 'on', '1']
    
    app.config['MAIL_USE_TLS'] = use_tls
    app.config['MAIL_USE_SSL'] = use_ssl
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])

    # --- PLUGINS INITIALISIEREN ---
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    # --- TEMPLATE FILTER ---
    @app.template_filter('markdown')
    def render_markdown(text):
        if not text: return ""
        allowed_tags = [
            'p', 'strong', 'em', 'ul', 'ol', 'li', 'br', 'h1', 'h2', 'h3', 
            'blockquote', 'code', 'pre', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 
            'details', 'summary'
        ]
        rendered = markdown.markdown(text, extensions=['nl2br', 'tables', 'fenced_code', 'attr_list'])
        return Markup(rendered)

    @app.template_filter('format_duration')
    def format_duration(s):
        if not s: return "0 Min"
        m, s = divmod(int(s), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h} Std {m} Min"
        return f"{m} Min {s} Sek"

    @app.context_processor
    def inject_globals():
        return {'now': datetime.utcnow()}

    @login_manager.user_loader
    def load_user(uid):
        return User.query.get(int(uid))

    # --- BLUEPRINTS ---
    from .routes import auth, main, learn, admin
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(learn.bp)
    app.register_blueprint(admin.bp)

    return app

# --- WICHTIG: Diese Zeile hat gefehlt! ---
# Sie erstellt die 'app' Variable, die Gunicorn sucht.
app = create_app()

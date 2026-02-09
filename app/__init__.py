import os
import time
from datetime import datetime
from flask import Flask
from .extensions import db, mail, login_manager, limiter
from .models import User

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'geheimnis_fuer_topp_nfs_dev_key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///local.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = 'static/uploads'
    
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.example.com')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'user@example.com')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'password')
    app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    # --- HIER FEHLTE DER FILTER ---
    @app.template_filter('format_duration')
    def format_duration(s):
        if not s: return "0 Min"
        m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{h} Std {m} Min" if h>0 else f"{m} Min {s} Sek"
    # -------------------------------

    @app.context_processor
    def inject_globals():
        return {'now': datetime.utcnow()}

    @login_manager.user_loader
    def load_user(uid): return User.query.get(int(uid))

    from .routes import auth, main, learn, admin
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(learn.bp)
    app.register_blueprint(admin.bp)

    with app.app_context():
        for i in range(10):
            try:
                db.create_all()
                if not User.query.filter_by(username='admin').first():
                    u = User(username='admin', is_admin=True)
                    u.set_password('admin123')
                    db.session.add(u)
                    db.session.commit()
                print("DB Ready")
                break
            except Exception as e: 
                print(f"Waiting for DB... ({e})")
                time.sleep(3)

    return app

app = create_app()

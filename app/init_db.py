import time
from app import create_app, db
from app.models import User

app = create_app()

def init_db():
    with app.app_context():
        # 15 Versuche, falls die DB beim Start etwas braucht
        print("--- STARTE DB INITIALISIERUNG ---")
        for i in range(15):
            try:
                db.create_all()
                
                # Admin erstellen
                if not User.query.filter_by(username='admin').first():
                    u = User(username='admin', is_admin=True)
                    u.set_password('admin123')
                    db.session.add(u)
                    db.session.commit()
                    print("--- ADMIN USER ERSTELLT ---")
                
                print("--- DB INITIALISIERUNG FERTIG ---")
                break
            except Exception as e:
                print(f"--- WARTE AUF DB... ({i+1}/15) Fehler: {e}")
                time.sleep(2)

if __name__ == "__main__":
    init_db()

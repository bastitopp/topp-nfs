# Topp-NFS Training - Version 3.0 🚑

Ein Lern-Management-System (LMS) spezialisiert für die Notfallsanitäter-Ausbildung.

## 🌟 Neue Features in v3.0
* **Ordnerstruktur (Nested Categories):** Unendliche Verschachtelung möglich (z.B. `Notfallmedizin/Innere/Herz/EKG`).
* **Multi-Select Learning:** Wähle mehrere Ordner gleichzeitig aus, um sie gemischt zu lernen.
* **Erweiterte Fragetypen:**
    * Drag & Drop Sortierung (Reihenfolge)
    * Zuordnung (Gruppierung)
    * Bildbeschriftung (Anatomie Multi)
    * Audio-Support (z.B. für Lungengeräusche)
* **Gamification:** Leaderboard, Badges und Daily Streaks.
* **Admin Tools:** CSV-Import, JSON-Backup-Export und Dashboard-Nachrichten.

## 🚀 Installation & Start

### Voraussetzungen
* Docker & Docker Compose

### Starten
1.  Repository klonen:
    ```bash
    git clone [https://github.com/DEIN_USERNAME/DEIN_REPO.git](https://github.com/DEIN_USERNAME/DEIN_REPO.git)
    cd DEIN_REPO
    ```

2.  **WICHTIG für v3.0 Update:**
    Wenn du von einer älteren Version kommst, musst du die Datenbank zurücksetzen, da sich die Struktur geändert hat:
    ```bash
    docker-compose down -v
    ```

3.  Starten:
    ```bash
    docker-compose up --build
    ```

4.  Browser öffnen: `http://localhost:5000`

## 👤 Standard-Login
Beim ersten Start wird automatisch ein Admin erstellt:
* **User:** `admin`
* **Pass:** `admin123`

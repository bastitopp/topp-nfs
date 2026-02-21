#!/bin/bash

# Sorgt dafür, dass das Skript bei jedem Fehler in den ERR-Trap springt
set -e

# --- 1. KONFIGURATION ---
APP_DIR="/opt/topp-nfs" 
ENV_FILE="$APP_DIR/.env"
BACKUP_DIR="/tmp/topp-nfs-backups"

# Empfänger-E-Mail eintragen!
RECEIVER_EMAIL="info@bastiantopp.de"

STORAGE_USER="u534947"
STORAGE_HOST="${STORAGE_USER}.your-storagebox.de"
STORAGE_PATH="/home/backup" 

DATE=$(date +"%Y%m%d_%H%M%S")
ARCHIVE_NAME="topp-nfs-backup_$DATE.tar.gz"
LOG_FILE="/tmp/topp-nfs-backup_$DATE.log"

# --- 2. E-MAIL FUNKTION ---
send_mail() {
    local subject="$1"
    local body="$2"
    
    # Python-Skript liest nun zusätzlich die Logdatei ein und fügt sie an
    python3 -c '
import smtplib, sys, os
from email.message import EmailMessage

env_file = sys.argv[1]
subject = sys.argv[2]
body = sys.argv[3]
receiver = sys.argv[4]
log_file = sys.argv[5]

# .env auslesen
env = {}
try:
    with open(env_file) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k] = v.strip("\"'\''")
except Exception as e:
    print("Konnte .env nicht lesen:", e)
    sys.exit(1)

# Log-Datei auslesen
try:
    with open(log_file, "r") as lf:
        log_content = lf.read()
except Exception:
    log_content = "Keine Logs verfügbar."

# E-Mail zusammenbauen
msg = EmailMessage()
msg.set_content(f"{body}\n\n--- SCRIPT LOG ---\n{log_content}")
msg["Subject"] = subject
msg["From"] = env.get("MAIL_DEFAULT_SENDER", env.get("MAIL_USERNAME"))
msg["To"] = receiver

port = int(env.get("MAIL_PORT", 587))
use_ssl = env.get("MAIL_USE_SSL", "False").lower() in ["true", "on", "1"]
use_tls = env.get("MAIL_USE_TLS", "False").lower() in ["true", "on", "1"]

# E-Mail senden
try:
    if use_ssl:
        server = smtplib.SMTP_SSL(env["MAIL_SERVER"], port)
    else:
        server = smtplib.SMTP(env["MAIL_SERVER"], port)
        if use_tls:
            server.starttls()
            
    server.login(env["MAIL_USERNAME"], env["MAIL_PASSWORD"])
    server.send_message(msg)
    server.quit()
except Exception as e:
    print("Fehler beim Senden der E-Mail:", e)
' "$ENV_FILE" "$subject" "$body" "$RECEIVER_EMAIL" "$LOG_FILE"
}

# --- 3. FEHLERBEHANDLUNG ---
error_handler() {
    echo "❌ Ein Fehler ist aufgetreten! Abbruch."
    send_mail "❌ topp-nfs Backup FEHLGESCHLAGEN" "Achtung! Das Backup am $DATE ist mit einem Fehler abgebrochen. Details findest du im Log:"
    rm -f "$LOG_FILE"
}
trap 'error_handler' ERR


# --- LOKALER START ---
echo "Starte Backup-Prozess... (Details werden ins Log und die E-Mail geschrieben)"
# Ab hier: Leite ALLE weiteren Ausgaben und Fehler direkt in die Log-Datei um
exec > "$LOG_FILE" 2>&1


# --- 4. BACKUP ERSTELLEN ---
echo "[$DATE] Starte Backup..."
mkdir -p "$BACKUP_DIR/data"

echo "Erstelle PostgreSQL Dump..."
docker exec topp-nfs-db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$BACKUP_DIR/data/db_backup_$DATE.sql"

echo "Kopiere Upload-Dateien..."
cp -r "$APP_DIR/app_data/uploads" "$BACKUP_DIR/data/uploads"

echo "Komprimiere Daten zu einem Archiv..."
tar -czf "$BACKUP_DIR/$ARCHIVE_NAME" -C "$BACKUP_DIR/data" .

# --- 5. TRANSFER ZUR HETZNER STORAGE BOX ---
echo "Übertrage Archiv zur Storage Box..."
scp -P 23 "$BACKUP_DIR/$ARCHIVE_NAME" "$STORAGE_USER@$STORAGE_HOST:$STORAGE_PATH"

# --- 6. AUFRÄUMEN (LOKAL) ---
echo "Lösche temporäre lokale Dateien..."
rm -rf "$BACKUP_DIR/data"
rm "$BACKUP_DIR/$ARCHIVE_NAME"

# --- 7. ALTE BACKUPS LÖSCHEN (REMOTE) ---
echo "Lösche alte Backups auf der Storage Box (behalte die neuesten 7)..."

# 1. Hole die Dateiliste von der Storage Box.
# Wir filtern lokal mit grep nach unseren Backups und sortieren sie absteigend (neueste oben).
# Das '|| true' ist wichtig, damit das Skript (wegen set -e) nicht abbricht, falls noch keine Backups da sind.
ALL_BACKUPS=$(ssh -p 23 "$STORAGE_USER@$STORAGE_HOST" "ls $STORAGE_PATH" | grep "topp-nfs-backup_" | sort -r || true)

# 2. Überspringe die ersten 7 Dateien und speichere den Rest in OLD_BACKUPS
OLD_BACKUPS=$(echo "$ALL_BACKUPS" | tail -n +8)

# 3. Wenn es alte Dateien gibt, lösche sie einzeln
if [ -n "$OLD_BACKUPS" ]; then
    for FILE in $OLD_BACKUPS; do
        # Entferne eventuelle unsichtbare Zeilenumbrüche aus der SSH-Ausgabe
        CLEAN_FILE=$(echo "$FILE" | tr -d '\r')
        echo "Entferne zu altes Backup: $CLEAN_FILE"
        ssh -p 23 "$STORAGE_USER@$STORAGE_HOST" "rm ${STORAGE_PATH}${CLEAN_FILE}"
    done
else
    echo "Es sind 7 oder weniger Backups vorhanden, es muss nichts aufgeräumt werden."
fi


# --- 8. ERFOLGSMELDUNG SENDEN ---
echo "Backup und Cleanup erfolgreich abgeschlossen!"
send_mail "✅ topp-nfs Backup ERFOLGREICH" "Das Backup ($ARCHIVE_NAME) wurde erfolgreich erstellt, hochgeladen und alte Backups wurden bereinigt. Hier ist der Protokollauszug:"

# Temporäre Log-Datei am Ende wieder löschen
rm -f "$LOG_FILE"

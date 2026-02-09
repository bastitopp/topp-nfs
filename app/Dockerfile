# Basis-Image: Schlankes Python 3.9
FROM python:3.9-slim

# Arbeitsverzeichnis im Container
WORKDIR /service

# System-Abhängigkeiten für PostgreSQL (psycopg2) und Compiler installieren
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Requirements kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# WICHTIG: Wir kopieren den Inhalt des lokalen Ordners (.) 
# in einen Unterordner "app" im Container.
# Dadurch funktionieren die relativen Imports (from .models import ...)
COPY . ./app

# Port freigeben
EXPOSE 5000

# Startbefehl für Gunicorn
# "app:create_app()" bedeutet:
# Suche im Paket "app" nach der Funktion "create_app" und führe sie aus.
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:create_app()"]

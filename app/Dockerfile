FROM python:3.9-slim

# Arbeitsverzeichnis im Container
WORKDIR /app

# Kopiere requirements (die liegen im selben Ordner wie das Dockerfile)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Rest (app.py, templates, etc.)
COPY . .

# WICHTIG: Hier stand vorher "app/app.py". 
# Da wir schon im Ordner sind, reicht "app.py":
CMD ["python", "app.py"]

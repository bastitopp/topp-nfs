from app import create_app
from app.extensions import db
from app.models import Card
import json
import re

app = create_app()

def remove_awkward_phrases(text):
    if not isinstance(text, str) or not text:
        return text
        
    # Entfernt die nervigen Phrasen (case-insensitive) inkl. eventueller "und" davor
    # \s*\b sorgt dafür, dass führende Leerzeichen mitgelöscht werden
    pattern = re.compile(r'(?i)\s*\b(am Ort|am Tag|und sonstiges|sonstiges)\b')
    cleaned = pattern.sub('', text)
    
    # Repariert Satzzeichen, falls ein Leerzeichen davor stehen geblieben ist (z.B. "Satz ." -> "Satz.")
    cleaned = re.sub(r'\s+([.,?!])', r'\1', cleaned)
    
    return cleaned.strip()

with app.app_context():
    # Wir durchlaufen jetzt ALLE Fragen, nicht nur MC
    cards = Card.query.all()
    fixed_count = 0
    
    # Ersetzungen für typische KI-Wörter (nur bei falschen MC-Antworten relevant)
    replacements = {
        r'\bimmer\b': 'in der Regel', r'\bImmer\b': 'In der Regel',
        r'\bnie\b': 'selten', r'\bNie\b': 'Selten',
        r'\bniemals\b': 'kaum', r'\bNiemals\b': 'Kaum',
        r'\bausschließlich\b': 'hauptsächlich', r'\bAusschließlich\b': 'Hauptsächlich',
        r'\bgrundsätzlich\b': 'meist', r'\bGrundsätzlich\b': 'Meist',
        r'\bkeinesfalls\b': 'eher nicht', r'\bKeinesfalls\b': 'Eher nicht'
    }
    
    for c in cards:
        changed = False
        
        # --- 1. Fragen-Text und Standard-Antwort bereinigen ---
        new_q = remove_awkward_phrases(c.question)
        if new_q != c.question:
            c.question = new_q
            changed = True
            
        new_a = remove_awkward_phrases(c.answer)
        if new_a != c.answer:
            c.answer = new_a
            changed = True

        # --- 2. Multiple Choice Optionen bereinigen & fixen ---
        if c.type == 'mc':
            try:
                opts = json.loads(c.options) if c.options else []
            except:
                opts = []
                
            orig_opts = list(opts)
            
            # Richtige Antwort aus Distraktoren entfernen
            if c.answer in opts:
                opts.remove(c.answer)
                
            # Exakt 3 falsche Antworten erzwingen
            if len(opts) > 3:
                opts = opts[:3]
            elif len(opts) < 3:
                while len(opts) < 3:
                    opts.append("Keine der genannten Optionen ist korrekt")
            
            # Jede Option durch die KI-Wort-Korrektur UND die Phrasen-Löschung jagen
            new_opts = []
            for o in opts:
                # Erst KI-Absolut-Wörter umschreiben
                for pattern, repl in replacements.items():
                    o = re.sub(pattern, repl, o)
                # Dann Phrasen löschen
                o = remove_awkward_phrases(o)
                new_opts.append(o)
            
            opts = new_opts
            
            if opts != orig_opts:
                c.options = json.dumps(opts)
                changed = True

        if changed:
            fixed_count += 1
            
    db.session.commit()
    print(f"🎉 Fertig! {fixed_count} Fragen/Antworten wurden repariert und von nervigen Füllwörtern befreit.")

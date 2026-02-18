import json
from app import create_app
from app.extensions import db
from app.models import Scenario, ScenarioNode, ScenarioChoice, ChoiceOutcome

app = create_app()

with app.app_context():
    print("Starte BPR-Import für 'Akutes Koronarsyndrom'...")

    # Altes ACS-Szenario löschen (falls du das Skript mehrfach ausführst)
    old_scenario = Scenario.query.filter_by(title="SAA 1.1 - Akutes Koronarsyndrom (ACS)").first()
    if old_scenario:
        db.session.delete(old_scenario)
        db.session.commit()

    # 1. SZENARIO ANLEGEN
    s = Scenario(
        title="SAA 1.1 - Akutes Koronarsyndrom (ACS)",
        dispatch_text="RD1 - Unklarer Thoraxschmerz, 65-jähriger Patient"
    )
    db.session.add(s)
    db.session.commit()

    # 2. STATIONEN (NODES) ANLEGEN
    node1 = ScenarioNode(
        scenario_id=s.id,
        status_badge="Eintreffen & Diagnostik",
        situation_text="Du triffst auf einen 65-jährigen männlichen Patienten. Er ist blass, kaltschweißig und klagt über einen starken retrosternalen Druck (NRS 8/10), der in den linken Arm ausstrahlt.\n\nXABCDE:\nA: frei\nB: AF 18/min, SpO2 95% (Raumluft)\nC: HF 95/min, RR 140/90 mmHg\nD: GCS 15\nE: unauffällig"
    )
    
    node2 = ScenarioNode(
        scenario_id=s.id,
        status_badge="SAA ACS",
        situation_text="Der i.v.-Zugang liegt. Das 12-Kanal-EKG zeigt deutliche ST-Hebungen in den Ableitungen II, III und aVF (inferiorer STEMI). Der Patient hat weiterhin starke Schmerzen (NRS 8). Wie gehst du gemäß SAA vor?"
    )

    node3 = ScenarioNode(
        scenario_id=s.id,
        status_badge="Spezifische Medikation",
        situation_text="Das EKG wurde telemetrisch an die PCI-Klinik übertragen. Nach fraktionierter Morphin-Gabe i.v. sind die Schmerzen erträglich (NRS 3). RR ist stabil bei 130/80. Welche Medikation forderst du nun zur Vorbereitung auf das HKL an?"
    )

    node4 = ScenarioNode(
        scenario_id=s.id,
        status_badge="Transport PCI-Klinik",
        situation_text="Hervorragend! Der Patient ist schmerzgelindert und kreislaufstabil. Du hast die korrekte SAA-Medikation (ASS + Heparin) verabreicht und transportierst ihn nun unter Voranmeldung direkt in das Herzkatheterlabor (HKL).",
        is_endpoint=True,
        is_success=True
    )

    db.session.add_all([node1, node2, node3, node4])
    db.session.commit()

    # STARTPUNKT SETZEN
    s.first_node_id = node1.id
    db.session.commit()

    # 3. ENTSCHEIDUNGEN & ERGEBNISSE VERKNÜPFEN

    # --- KNOTEN 1: Basismaßnahmen ---
    c1_1 = ScenarioChoice(node_id=node1.id, action_text="i.v.-Zugang legen & 12-Kanal-EKG ableiten")
    c1_2 = ScenarioChoice(node_id=node1.id, action_text="Sauerstoffgabe 15l/min über Maske & i.v.-Zugang")
    c1_3 = ScenarioChoice(node_id=node1.id, action_text="Sofortige Gabe von ASS und Heparin i.v.")
    db.session.add_all([c1_1, c1_2, c1_3])
    db.session.commit()

    db.session.add(ChoiceOutcome(choice_id=c1_1.id, next_node_id=node2.id, set_flags={"zugang": True, "ekg": True}))
    db.session.add(ChoiceOutcome(
        choice_id=c1_2.id, is_fatal_error=True, 
        error_feedback="Falsch! Laut SAA erfolgt keine routinemäßige Gabe von Sauerstoff bei einem SpO2 über 90%. Der Patient hat 95%."
    ))
    db.session.add(ChoiceOutcome(
        choice_id=c1_3.id, is_fatal_error=True, 
        error_feedback="Kritischer Algorithmus-Bruch! Ohne vorheriges EKG und saubere Diagnostik (Ausschluss Aortensyndrom) darf keine Antikoagulation verabreicht werden."
    ))

    # --- KNOTEN 2: Schmerztherapie & Telemetrie ---
    c2_1 = ScenarioChoice(node_id=node2.id, action_text="EKG telemetrisch übertragen & Morphin i.v. zur Schmerztherapie")
    c2_2 = ScenarioChoice(node_id=node2.id, action_text="Nitro-Spray (2 Hübe s.l.) zur schnellen Schmerzsenkung")
    c2_3 = ScenarioChoice(node_id=node2.id, action_text="Nur EKG übertragen, zügiger Transportbeginn ohne Analgesie")
    db.session.add_all([c2_1, c2_2, c2_3])
    db.session.commit()

    db.session.add(ChoiceOutcome(choice_id=c2_1.id, next_node_id=node3.id, required_flags={"zugang": True}))
    db.session.add(ChoiceOutcome(
        choice_id=c2_2.id, is_fatal_error=True, 
        error_feedback="Gefahr! Bei einem inferioren STEMI besteht die Gefahr einer Rechtsherzbeteiligung. Nitro kann hier einen massiven (lebensgefährlichen) Blutdruckabfall auslösen. Bevorzugt ist Morphin i.v."
    ))
    db.session.add(ChoiceOutcome(
        choice_id=c2_3.id, is_fatal_error=True, 
        error_feedback="Fehlerhaftes Patientenmanagement. Der Patient hat stärkste Schmerzen (NRS 8). Eine Schmerztherapie (Morphin) muss laut SAA vor/während des Transports erfolgen."
    ))

    # --- KNOTEN 3: Medikation ---
    c3_1 = ScenarioChoice(node_id=node3.id, action_text="Acetylsalicylsäure i.v. und Heparin i.v.")
    c3_2 = ScenarioChoice(node_id=node3.id, action_text="Nur Acetylsalicylsäure i.v.")
    c3_3 = ScenarioChoice(node_id=node3.id, action_text="Acetylsalicylsäure i.v., Heparin i.v. und Metoprolol i.v.")
    db.session.add_all([c3_1, c3_2, c3_3])
    db.session.commit()

    db.session.add(ChoiceOutcome(choice_id=c3_1.id, next_node_id=node4.id))
    db.session.add(ChoiceOutcome(
        choice_id=c3_2.id, is_fatal_error=True, 
        error_feedback="Fehler im Algorithmus! Bei einem STEMI (oder NSTE-ACS mit Risikofaktoren) müssen laut SAA ASS *und* Heparin gegeben werden. Nur bei einem NSTE-ACS ohne Risiken wird auf Heparin verzichtet."
    ))
    db.session.add(ChoiceOutcome(
        choice_id=c3_3.id, is_fatal_error=True, 
        error_feedback="Kompetenzüberschreitung! Die Gabe eines Beta-Blockers (Metoprolol) bedarf laut BPR einer umfangreichen kardiologischen Kenntnis zum Ausschluss von Kontraindikationen und ist keine pauschale Standardmaßnahme."
    ))

    print("Erfolgreich! SAA 1.1 ACS wurde der Datenbank hinzugefügt.")

function initQuizFeatures() {
    // --- Allgemeine Listen-Features (Ordering & Assignment) ---
    const sortList = document.getElementById('sortable_list');
    if (sortList) {
        new Sortable(sortList, { animation: 150, ghostClass: 'bg-info', dragClass: 'shadow-lg', delay: 100, delayOnTouchOnly: true, fallbackTolerance: 3 });
    }

    const poolEl = document.getElementById('assignment_pool');
    if (poolEl) {
        new Sortable(poolEl, { group: 'shared', animation: 150, ghostClass: 'opacity-50', delay: 100, delayOnTouchOnly: true, fallbackTolerance: 3 });
        document.querySelectorAll('.assignment-dropzone').forEach(dz => {
            new Sortable(dz, { group: 'shared', animation: 150, ghostClass: 'bg-info', delay: 100, delayOnTouchOnly: true, fallbackTolerance: 3 });
        });
    }

    // --- Formular & Beenden-Schutz ---
    let formChanged = false;
    const quizForm = document.getElementById('quizForm');
    if (quizForm) {
        quizForm.addEventListener('input', () => formChanged = true);
        quizForm.addEventListener('submit', function(e) { 
            this.setAttribute('data-submitting', 'true'); 
            const type = this.getAttribute('data-card-type');
            if(type === 'ordering') submitOrdering();
            if(type === 'assignment') submitAssignment();
        });
    }
    window.quizFormChanged = () => formChanged;

    // --- Anatomie Single Logic ---
    if(document.querySelector('.anatomy-single-dropzone')) {
        initAnatomySingle();
    }

    // --- Anatomie Multi Logic ---
    if(document.querySelector('.anatomy-dropzone')) {
        initAnatomyMulti();
    }
}

function submitOrdering() {
    const list = document.getElementById('sortable_list');
    if(!list) return;
    const items = [];
    list.querySelectorAll('li span').forEach(span => items.push(span.innerText.trim()));
    document.getElementById('order_json_input').value = JSON.stringify(items);
}

function submitAssignment() {
    const result = {};
    document.querySelectorAll('.assignment-dropzone').forEach(dz => {
        const groupName = dz.getAttribute('data-group');
        const items = [];
        dz.querySelectorAll('.badge').forEach(b => items.push(b.innerText.trim()));
        result[groupName] = items;
    });
    document.getElementById('assignment_json_input').value = JSON.stringify(result);
}

// --- Ausgelagerte Anatomie (Single) Logik ---
function initAnatomySingle() {
    let selectedSingleLabel = null;
    let correctSingleCount = 0;
    let totalSingleTargets = document.querySelectorAll('.anatomy-single-dropzone').length;

    document.querySelectorAll('.anatomy-single-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.anatomy-single-btn').forEach(b => {
                b.classList.remove('btn-primary', 'btn-secondary', 'text-white');
                let type = b.getAttribute('data-type');
                b.classList.add(type === 'de' ? 'btn-outline-primary' : 'btn-outline-secondary');
            });
            let type = this.getAttribute('data-type');
            this.classList.remove(type === 'de' ? 'btn-outline-primary' : 'btn-outline-secondary');
            this.classList.add(type === 'de' ? 'btn-primary' : 'btn-secondary', 'text-white');
            selectedSingleLabel = this;
        });
    });

    document.querySelectorAll('.anatomy-single-dropzone').forEach(zone => {
        zone.addEventListener('click', function() {
            if(!selectedSingleLabel) return;
            
            let expectedType = this.getAttribute('data-type');
            let expectedVal = this.getAttribute('data-answer');
            let selectedVal = selectedSingleLabel.getAttribute('data-val');
            
            if(expectedVal === selectedVal) {
                this.classList.remove('bg-light');
                this.classList.add('bg-success', 'text-white', 'fw-bold', 'border-success', 'fs-5');
                this.innerHTML = selectedVal;
                this.style.borderStyle = 'solid';
                
                document.getElementById('single_input_' + expectedType).value = selectedVal;
                
                selectedSingleLabel.style.visibility = 'hidden';
                selectedSingleLabel.classList.remove('anatomy-single-btn');
                selectedSingleLabel = null;
                
                correctSingleCount++;
                if(correctSingleCount === totalSingleTargets) {
                    document.getElementById('submit-single-btn').classList.remove('d-none');
                }
            } else {
                this.classList.add('flash-error');
                setTimeout(() => this.classList.remove('flash-error'), 600);
            }
        });
    });
}

// --- Ausgelagerte Anatomie Multi Logik (Legenden-System) ---
function initAnatomyMulti() {
    let selectedLabel = null;
    let correctCount = 0;
    let totalTargets = 0;
    
    document.querySelectorAll('.anatomy-dropzone').forEach(z => {
        let de = z.getAttribute('data-de');
        let lat = z.getAttribute('data-lat');
        if(de && de !== '-' && de !== '%') totalTargets++;
        if(lat && lat !== '-' && lat !== '%') totalTargets++;
    });

    // Event-Listener für das Anklicken der Antwort-Buttons
    document.querySelectorAll('.anatomy-label-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.anatomy-label-btn').forEach(b => {
                b.classList.remove('btn-primary', 'btn-secondary', 'text-white');
                let type = b.getAttribute('data-type');
                b.classList.add(type === 'de' ? 'btn-outline-primary' : 'btn-outline-secondary');
            });
            let type = this.getAttribute('data-type');
            this.classList.remove(type === 'de' ? 'btn-outline-primary' : 'btn-outline-secondary');
            this.classList.add(type === 'de' ? 'btn-primary' : 'btn-secondary', 'text-white');
            selectedLabel = this;
        });
    });

    // Event-Listener für das Ablegen auf dem Bild-Punkt
    document.querySelectorAll('.anatomy-dropzone').forEach(zone => {
        zone.addEventListener('click', function() {
            if(!selectedLabel) return;
            
            let type = selectedLabel.getAttribute('data-type');
            let expected = this.getAttribute('data-' + type);
            let selectedVal = selectedLabel.getAttribute('data-val');
            let id = this.getAttribute('data-id');
            let alreadySolved = this.getAttribute('data-solved-' + type) === '1';
            
            if(!alreadySolved && expected === selectedVal) {
                
                // 1. Prüfen, ob der Punkt 1 oder 2 Labels benötigt
                this.setAttribute('data-solved-' + type, '1');
                this.setAttribute('data-assigned-' + type, selectedVal); // Wert speichern
                
                let needsDe = this.getAttribute('data-de') && this.getAttribute('data-de') !== '-' && this.getAttribute('data-de') !== '%';
                let needsLat = this.getAttribute('data-lat') && this.getAttribute('data-lat') !== '-' && this.getAttribute('data-lat') !== '%';
                
                let solvedDe = this.getAttribute('data-solved-de') === '1';
                let solvedLat = this.getAttribute('data-solved-lat') === '1';
                
                let assignedDe = this.getAttribute('data-assigned-de');
                let assignedLat = this.getAttribute('data-assigned-lat');
                
                // Ist ALLES da, was der Punkt verlangt?
                let isFullySolved = (!needsDe || solvedDe) && (!needsLat || solvedLat);

                if (isFullySolved) {
                    this.classList.remove('partially-solved');
                    this.classList.add('solved');
                } else {
                    this.classList.add('partially-solved');
                }
                
                // Bezeichnungen direkt auf dem Punkt anzeigen (mit Sprachhinweis, ohne Umbruch, untereinander)
                let labelHtml = '';
                if (assignedDe) {
                    labelHtml += `<div class="fw-bold" style="white-space: nowrap; line-height: 1.2;">${assignedDe} <span style="font-weight: normal; font-size: 0.85em; opacity: 0.9;">(DE)</span></div>`;
                }
                if (assignedLat) {
                    labelHtml += `<div style="white-space: nowrap; line-height: 1.2; font-size: 0.9em;">${assignedLat} <span style="font-size: 0.85em; opacity: 0.9;">(LAT)</span></div>`;
                }
                this.innerHTML = labelHtml;
                
                // Button aus der Liste entfernen
                selectedLabel.style.visibility = 'hidden';
                selectedLabel.classList.remove('anatomy-label-btn'); 
                selectedLabel = null;
                
                // Wert für das Formular speichern
                let hiddenInp = document.createElement('input');
                hiddenInp.type = 'hidden'; 
                hiddenInp.name = type + '_' + id; 
                hiddenInp.value = selectedVal;
                document.getElementById('quizForm').appendChild(hiddenInp);

                // --- 2. Legenden-Eintrag (Zusammenfassen bei 2 Begriffen) ---
                const legendContainer = document.getElementById('anatomy-legend-container');
                const legend = document.getElementById('anatomy-legend');
                if(legendContainer) legendContainer.classList.remove('d-none');
                
                let existingLegendItem = document.getElementById('legend-item-' + id);
                let typeLabel = type === 'de' ? 'DE' : 'LAT';

                if (existingLegendItem) {
                    // Wenn der Eintrag für die Nummer schon existiert
                    let textContainer = existingLegendItem.querySelector('.legend-text');
                    textContainer.innerHTML += ` <span class="text-muted mx-1">/</span> ${selectedVal} <small class="text-muted fw-normal">(${typeLabel})</small>`;
                    
                    // Mache die Legende grün
                    let badgeNum = existingLegendItem.querySelector('.badge-num');
                    badgeNum.classList.remove('bg-warning', 'text-dark');
                    badgeNum.classList.add('bg-success', 'text-white');
                    existingLegendItem.classList.remove('border-warning');
                    existingLegendItem.classList.add('border-success');
                    
                } else {
                    // Neu anlegen
                    const legendBadge = document.createElement('div');
                    legendBadge.id = 'legend-item-' + id;
                    
                    // Farbe je nachdem, ob noch ein Begriff fehlt (gelb) oder nicht (grün)
                    let isPartial = !isFullySolved;
                    let borderClass = isPartial ? 'border-warning' : 'border-success';
                    let badgeClass = isPartial ? 'bg-warning text-dark' : 'bg-success text-white';

                    legendBadge.className = `anatomy-legend-item badge bg-white text-dark border ${borderClass} border-opacity-50 d-flex align-items-center gap-2 p-2 shadow-sm fs-6`;
                    legendBadge.innerHTML = `<span class="badge-num badge ${badgeClass} rounded-circle" style="width: 24px; height: 24px; display: flex; align-items: center; justify-content: center;">${id}</span> <span class="legend-text fw-medium">${selectedVal} <small class="text-muted fw-normal">(${typeLabel})</small></span>`;
                    
                    // Hover-Effekte synchronisieren
                    legendBadge.addEventListener('mouseenter', () => this.classList.add('pin-hover'));
                    legendBadge.addEventListener('mouseleave', () => this.classList.remove('pin-hover'));
                    this.addEventListener('mouseenter', () => legendBadge.classList.add('legend-hover'));
                    this.addEventListener('mouseleave', () => legendBadge.classList.remove('legend-hover'));
                    
                    if(legend) legend.appendChild(legendBadge);
                }

                // Checken, ob alle Punkte gelöst sind
                correctCount++;
                if(correctCount === totalTargets) {
                     document.querySelectorAll('.anatomy-dropzone').forEach(z => z.style.borderColor = 'transparent');
                    document.getElementById('submit-btn').classList.remove('d-none');
                }
            } else {
                this.classList.add('flash-error');
                setTimeout(() => this.classList.remove('flash-error'), 600);
            }
        });
    });
}

// --- Event Listeners & Shortcuts ---
document.addEventListener("DOMContentLoaded", initQuizFeatures);
document.addEventListener("htmx:afterSwap", initQuizFeatures);

if (!window.unloadWarningInitialized) {
    window.addEventListener('beforeunload', function (e) {
        const form = document.getElementById('quizForm');
        if (window.quizFormChanged && window.quizFormChanged() && form && !form.hasAttribute('data-submitting')) {
            e.preventDefault(); e.returnValue = '';
        }
    });
    window.unloadWarningInitialized = true;
}

if (!window.keyboardNavInitialized) {
    document.addEventListener('keydown', function(event) {
        if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
        
        if (event.key === 'Enter') {
            const nextBtn = document.querySelector('.btn-next-question');
            const safeBtn = document.querySelector('.btn-quality-safe');
            if (nextBtn) nextBtn.click();
            else if (safeBtn) safeBtn.click();
        }
        if (event.key.toLowerCase() === 's') { const skipBtn = document.getElementById('skipBtn'); if (skipBtn) skipBtn.click(); }
        if (event.key.toLowerCase() === 'r') { const modalTarget = document.querySelector('[data-bs-target="#reportModal"]'); if (modalTarget) modalTarget.click(); }
        if (event.key.toLowerCase() === 'e') { const editBtn = document.querySelector('a[title="Frage bearbeiten"]'); if (editBtn) editBtn.click(); }
        
        const mcBtns = document.querySelectorAll('button[name="mc_answer"]');
        if (mcBtns.length > 0 && event.key > 0 && event.key <= mcBtns.length) mcBtns[event.key - 1].click();
        
        if (document.querySelector('.btn-quality-safe')) {
            if (event.key === '1') { let b = document.querySelector('button[value="3"]'); if(b) b.click(); }
            if (event.key === '2') { let b = document.querySelector('button[value="5"]'); if(b) b.click(); }
        }
    });
    window.keyboardNavInitialized = true;
}
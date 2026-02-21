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

// --- Ausgelagerte Anatomie Multi Logik ---
function initAnatomyMulti() {
    const toggleBtn = document.getElementById('toggle-labels-btn');
    const imgWrapper = document.getElementById('anatomy-img-wrapper');
    
    if(toggleBtn && imgWrapper) {
        toggleBtn.addEventListener('click', function(e) {
            e.preventDefault();
            imgWrapper.classList.toggle('labels-hidden');
            const icon = this.querySelector('i');
            if(imgWrapper.classList.contains('labels-hidden')) {
                icon.classList.replace('bi-eye-slash-fill', 'bi-eye-fill');
                icon.classList.replace('text-secondary', 'text-primary');
                this.innerHTML = '<i class="bi bi-eye-fill text-primary me-1"></i> Einblenden';
            } else {
                icon.classList.replace('bi-eye-fill', 'bi-eye-slash-fill');
                icon.classList.replace('text-primary', 'text-secondary');
                this.innerHTML = '<i class="bi bi-eye-slash-fill text-secondary me-1"></i> Ausblenden';
                setTimeout(resolveAnatomyOverlaps, 50); 
            }
        });
    }

    function resolveAnatomyOverlaps() {
        if(imgWrapper && imgWrapper.classList.contains('labels-hidden')) return;
        const zones = Array.from(document.querySelectorAll('.anatomy-dropzone.solved'));
        let overlap = true;
        let iters = 0;
        
        while(overlap && iters < 50) {
            overlap = false;
            for(let i=0; i<zones.length; i++) {
                for(let j=i+1; j<zones.length; j++) {
                    let l1 = zones[i].querySelector('.solved-label');
                    let l2 = zones[j].querySelector('.solved-label');
                    if(!l1 || !l2) continue;
                    let r1 = l1.getBoundingClientRect();
                    let r2 = l2.getBoundingClientRect();
                    if (!(r1.right < r2.left - 2 || r1.left > r2.right + 2 || r1.bottom < r2.top - 2 || r1.top > r2.bottom + 2)) {
                        overlap = true;
                        let side = zones[j].getAttribute('data-side');
                        let currentOffset = parseInt(zones[j].style.getPropertyValue('--offset')) || 0;
                        let currentLen = parseInt(zones[j].style.getPropertyValue('--line-len')) || 25;
                        if (side === 'left' || side === 'right') {
                            zones[j].style.setProperty('--offset', (currentOffset + (r2.top >= r1.top ? 6 : -6)) + 'px');
                            zones[j].style.setProperty('--line-len', (currentLen + 3) + 'px');
                        } else {
                            zones[j].style.setProperty('--offset', (currentOffset + (r2.left >= r1.left ? 6 : -6)) + 'px');
                            zones[j].style.setProperty('--line-len', (currentLen + 3) + 'px');
                        }
                    }
                }
            }
            iters++;
        }
    }

    let selectedLabel = null;
    let correctCount = 0;
    let totalTargets = 0;
    
    document.querySelectorAll('.anatomy-dropzone').forEach(z => {
        let de = z.getAttribute('data-de');
        let lat = z.getAttribute('data-lat');
        if(de && de !== '-' && de !== '%') totalTargets++;
        if(lat && lat !== '-' && lat !== '%') totalTargets++;
    });

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

    document.querySelectorAll('.anatomy-dropzone').forEach(zone => {
        zone.addEventListener('click', function() {
            if(!selectedLabel) return;
            let type = selectedLabel.getAttribute('data-type');
            let expected = this.getAttribute('data-' + type);
            let selectedVal = selectedLabel.getAttribute('data-val');
            let id = this.getAttribute('data-id');
            let alreadySolved = this.getAttribute('data-solved-' + type) === '1';
            
            if(!alreadySolved && expected === selectedVal) {
                this.classList.add('solved');
                
                let xCoord = parseFloat(this.style.left);
                let yCoord = parseFloat(this.style.top);
                let distTop = yCoord, distBottom = 100 - yCoord, distLeft = xCoord, distRight = 100 - xCoord;
                let min = Math.min(distTop, distBottom, distLeft, distRight);
                let side = 'left';
                if (min === distTop) side = 'top';
                else if (min === distBottom) side = 'bottom';
                else if (min === distRight) side = 'right';
                
                this.setAttribute('data-side', side);
                let icon = this.querySelector('i.bi-question');
                if(icon) icon.remove();
                
                this.innerHTML += `<div class="solved-line"></div><div class="solved-label text-nowrap">${selectedVal}</div>`;
                this.setAttribute('data-solved-' + type, '1');
                
                if(toggleBtn) toggleBtn.classList.remove('d-none');
                
                selectedLabel.style.visibility = 'hidden';
                selectedLabel.classList.remove('anatomy-label-btn'); 
                selectedLabel = null;
                
                let hiddenInp = document.createElement('input');
                hiddenInp.type = 'hidden'; hiddenInp.name = type + '_' + id; hiddenInp.value = selectedVal;
                document.getElementById('quizForm').appendChild(hiddenInp);
                
                setTimeout(resolveAnatomyOverlaps, 50);

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

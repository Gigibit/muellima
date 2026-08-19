/**
 * Quiz manager for Personal School.
 *
 * Handles:
 *  - quiz generation via Django API
 *  - quiz modal display
 *  - question navigation
 *  - answer confirmation and feedback
 *  - score tracking
 *  - final results
 */
(function () {
    'use strict';

    const quizBtn = document.getElementById('quiz-btn');
    const quizModal = document.getElementById('quiz-modal');
    const quizClose = document.getElementById('quiz-close');
    const quizBody = document.getElementById('quiz-body');
    const quizTitle = document.getElementById('quiz-title');
    const quizCorrect = document.getElementById('quiz-correct');
    const quizWrong = document.getElementById('quiz-wrong');
    const quizTotal = document.getElementById('quiz-total');

    let quizData = null;
    let currentQuestion = 0;
    let correctCount = 0;
    let wrongCount = 0;
    let answeredQuestions = [];  // track wrong answers for review

    // ── Open quiz modal ───────────────────────────────────────────
    quizBtn.addEventListener('click', async () => {
        // Mute mic during quiz
        if (window.PS_Realtime) window.PS_Realtime.mute();

        quizModal.hidden = false;
        quizBody.innerHTML = `
            <div class="quiz-loading">
                <div class="loading-spinner"></div>
                <p>Sto preparando il quiz...</p>
            </div>
        `;
        resetScore();

        const lessonId = document.getElementById('lesson-combobox').value;
        if (!lessonId) {
            quizBody.innerHTML = '<p>Seleziona prima una lezione.</p>';
            return;
        }

        try {
            const resp = await fetch(`/api/lessons/${lessonId}/quiz/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.PS_CSRF_TOKEN,
                },
            });
            const data = await resp.json();

            if (data.success) {
                quizData = data;
                quizTitle.textContent = data.title || 'Quiz';
                currentQuestion = 0;
                correctCount = 0;
                wrongCount = 0;
                answeredQuestions = [];
                renderQuestion();
            } else {
                quizBody.innerHTML = `<p>${data.error?.message || 'Errore nella generazione del quiz.'}</p>`;
            }
        } catch (err) {
            quizBody.innerHTML = '<p>Errore di connessione. Riprova.</p>';
        }
    });

    // ── Close quiz ────────────────────────────────────────────────
    quizClose.addEventListener('click', () => {
        quizModal.hidden = true;
        if (window.PS_Realtime) window.PS_Realtime.unmute();
    });

    // Close on backdrop click
    quizModal.addEventListener('click', (e) => {
        if (e.target === quizModal) {
            quizModal.hidden = true;
            if (window.PS_Realtime) window.PS_Realtime.unmute();
        }
    });

    // ── Reset score ───────────────────────────────────────────────
    function resetScore() {
        correctCount = 0;
        wrongCount = 0;
        updateScore();
    }

    function updateScore() {
        quizCorrect.textContent = `✓ ${correctCount}`;
        quizWrong.textContent = `✕ ${wrongCount}`;
        quizTotal.textContent = `${correctCount + wrongCount} / ${quizData ? quizData.questions.length : 0}`;
    }

    // ── Render a question ────────────────────────────────────────
    function renderQuestion() {
        if (!quizData || currentQuestion >= quizData.questions.length) {
            renderResults();
            return;
        }

        const q = quizData.questions[currentQuestion];
        const total = quizData.questions.length;
        const num = currentQuestion + 1;

        let optionsHtml = q.options.map((opt, i) => `
            <div class="quiz-option" data-index="${i}" tabindex="0" role="button">
                <span class="quiz-option-radio"></span>
                <span>${escapeHtml(opt)}</span>
            </div>
        `).join('');

        quizBody.innerHTML = `
            <div class="quiz-question">
                <div class="quiz-question-num">Domanda ${num} di ${total}</div>
                <div class="quiz-question-text">${escapeHtml(q.question)}</div>
                <div class="quiz-options">${optionsHtml}</div>
                <div class="quiz-feedback" id="quiz-feedback" hidden></div>
                <button class="quiz-confirm-btn" id="quiz-confirm" disabled>Conferma</button>
            </div>
        `;

        let selectedIndex = -1;
        const options = quizBody.querySelectorAll('.quiz-option');
        const confirmBtn = document.getElementById('quiz-confirm');
        const feedback = document.getElementById('quiz-feedback');

        options.forEach(opt => {
            opt.addEventListener('click', () => {
                if (confirmBtn.disabled === false && !opt.classList.contains('disabled')) {
                    options.forEach(o => o.classList.remove('selected'));
                    opt.classList.add('selected');
                    selectedIndex = parseInt(opt.dataset.index, 10);
                    confirmBtn.disabled = false;
                }
            });

            // Keyboard support
            opt.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    opt.click();
                }
            });
        });

        confirmBtn.addEventListener('click', () => {
            if (selectedIndex < 0) return;

            // Disable further changes
            options.forEach(o => {
                o.classList.add('disabled');
                o.style.pointerEvents = 'none';
            });
            confirmBtn.disabled = true;

            const isCorrect = selectedIndex === q.correct_index;

            // Mark correct and wrong options
            options[q.correct_index].classList.add('correct');
            if (!isCorrect) {
                options[selectedIndex].classList.add('wrong');
            }

            // Show feedback
            feedback.hidden = false;
            feedback.className = 'quiz-feedback ' + (isCorrect ? 'correct' : 'wrong');
            feedback.innerHTML = `
                <strong>${isCorrect ? '✓ Corretto' : '✕ Non corretato'}</strong>
                ${escapeHtml(q.explanation)}
            `;

            // Update score
            if (isCorrect) {
                correctCount++;
            } else {
                wrongCount++;
                answeredQuestions.push({
                    question: q.question,
                    correct: q.options[q.correct_index],
                    your: q.options[selectedIndex],
                });
            }
            updateScore();

            // Replace confirm button with next button
            confirmBtn.remove();
            const nextBtn = document.createElement('button');
            nextBtn.className = 'quiz-next-btn';
            nextBtn.id = 'quiz-next';
            nextBtn.textContent = num < total ? 'Prossima domanda →' : 'Vedi risultati →';
            nextBtn.addEventListener('click', () => {
                currentQuestion++;
                renderQuestion();
            });
            quizBody.querySelector('.quiz-question').appendChild(nextBtn);
        });
    }

    // ── Render results ────────────────────────────────────────────
    function renderResults() {
        const total = quizData.questions.length;
        const score = correctCount;
        const percent = Math.round((score / total) * 100);

        let feedback = '';
        let reviewHtml = '';

        if (percent >= 80) {
            feedback = 'Ottimo lavoro! 🎉';
        } else if (percent >= 60) {
            feedback = 'Buon lavoro, continua così! 👍';
        } else {
            feedback = 'Potresti ripassare:';
            if (answeredQuestions.length > 0) {
                reviewHtml = `
                    <div class="quiz-result-review">
                        <h4>Ripassa questi argomenti:</h4>
                        <ul>
                            ${answeredQuestions.map(a => `
                                <li><strong>${escapeHtml(a.question)}</strong><br>
                                Risposta corretta: ${escapeHtml(a.correct)}</li>
                            `).join('')}
                        </ul>
                    </div>
                `;
            }
        }

        quizBody.innerHTML = `
            <div class="quiz-result">
                <h3>Quiz completato</h3>
                <div class="quiz-result-score">${score} / ${total}</div>
                <div class="quiz-result-percent">${percent}%</div>
                <div class="quiz-result-feedback">${feedback}</div>
                ${reviewHtml}
                <button class="quiz-next-btn" id="quiz-restart" style="margin-top:1.5rem">Chiudi</button>
            </div>
        `;

        document.getElementById('quiz-restart').addEventListener('click', () => {
            quizModal.hidden = true;
            if (window.PS_Realtime) window.PS_Realtime.unmute();
        });
    }

    // ── Escape HTML ────────────────────────────────────────────────
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

})();

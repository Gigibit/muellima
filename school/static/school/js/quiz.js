/**
 * Quiz manager for Muellima.
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
    const quizToast = document.getElementById('quiz-feedback-toast');
    const quizToastTitle = document.getElementById('quiz-feedback-toast-title');
    const quizToastMessage = document.getElementById('quiz-feedback-toast-message');
    const quizToastClose = document.getElementById('quiz-feedback-toast-close');

    let quizData = null;
    let currentQuestion = 0;
    let correctCount = 0;
    let wrongCount = 0;
    let answeredQuestions = [];  // track wrong answers for review
    let currentQuizLessonId = null;
    let completionReported = false;

    // ── Open quiz modal ───────────────────────────────────────────
    quizBtn.addEventListener('click', async () => {
        if (quizBtn.dataset.action === 'next-lesson' && quizBtn.dataset.nextUrl) {
            window.location.assign(quizBtn.dataset.nextUrl);
            return;
        }
        if (quizBtn.dataset.action === 'course-complete') {
            renderCourseCongratulations();
            return;
        }
        // Mute mic during quiz
        if (window.PS_Realtime) window.PS_Realtime.pauseForQuiz();

        quizModal.hidden = false;
        quizBody.innerHTML = `
            <div class="quiz-loading">
                <div class="loading-spinner"></div>
                <p>Sto preparando il quiz...</p>
            </div>
        `;
        resetScore();
        hideQuizToast();

        const lessonId = document.getElementById('lesson-combobox').value;
        if (!lessonId) {
            quizBody.innerHTML = '<p>Seleziona prima una lezione.</p>';
            return;
        }
        currentQuizLessonId = lessonId;
        completionReported = false;

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

    quizToastClose.addEventListener('click', hideQuizToast);

    function hideQuizToast() {
        quizToast.hidden = true;
    }

    function showQuizToast(isCorrect, explanation) {
        quizToast.className = `quiz-feedback-toast ${isCorrect ? 'correct' : 'wrong'}`;
        quizToastTitle.textContent = isCorrect ? '✓ Risposta corretta' : '✕ Risposta sbagliata';
        quizToastMessage.textContent = explanation || '';
        quizToast.hidden = false;
        quizToastClose.focus({ preventScroll: true });
    }

    // ── Close quiz ────────────────────────────────────────────────
    quizClose.addEventListener('click', () => {
        hideQuizToast();
        quizModal.hidden = true;
        if (window.PS_Realtime) window.PS_Realtime.resumeAfterQuiz();
    });

    // Close on backdrop click
    quizModal.addEventListener('click', (e) => {
        if (e.target === quizModal) {
            hideQuizToast();
            quizModal.hidden = true;
            if (window.PS_Realtime) window.PS_Realtime.resumeAfterQuiz();
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
        hideQuizToast();
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
                <button class="quiz-confirm-btn" id="quiz-confirm" disabled>Conferma</button>
            </div>
        `;

        let selectedIndex = -1;
        const options = quizBody.querySelectorAll('.quiz-option');
        const confirmBtn = document.getElementById('quiz-confirm');

        options.forEach(opt => {
            opt.addEventListener('click', () => {
                if (!opt.classList.contains('disabled')) {
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

            showQuizToast(isCorrect, q.explanation);

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
        hideQuizToast();
        const total = quizData.questions.length;
        const score = correctCount;
        const percent = Math.round((score / total) * 100);
        const passingScore = Math.floor(total / 2) + 1;
        const passedQuiz = total > 0 && score >= passingScore;

        let feedback = '';
        let reviewHtml = '';

        if (passedQuiz) {
            feedback = `Quiz superato! Hai raggiunto la soglia di ${passingScore} risposte corrette. La lezione è completata. 🎉`;
        } else if (percent >= 80) {
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
                <div class="quiz-result-feedback" id="quiz-result-feedback">${feedback}</div>
                <p class="quiz-passing-note"><em>Per superare la lezione devi rispondere correttamente a più della metà delle domande.</em></p>
                ${passedQuiz ? '<div class="quiz-completion-status" id="quiz-completion-status">Salvataggio completamento…</div>' : ''}
                ${reviewHtml}
                <button class="quiz-next-btn" id="quiz-restart" style="margin-top:1.5rem">Chiudi</button>
            </div>
        `;

        if (passedQuiz) completeLessonFromQuiz();

        document.getElementById('quiz-restart').addEventListener('click', () => {
            hideQuizToast();
            quizModal.hidden = true;
            if (window.PS_Realtime) window.PS_Realtime.resumeAfterQuiz();
        });
    }

    async function completeLessonFromQuiz() {
        if (completionReported || !currentQuizLessonId) return;
        completionReported = true;
        const status = document.getElementById('quiz-completion-status');
        try {
            const response = await fetch(`/api/lessons/${encodeURIComponent(currentQuizLessonId)}/complete/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.PS_CSRF_TOKEN,
                },
                body: '{}',
            });
            if (!response.ok) throw new Error('Lesson completion API error');
            const completion = await response.json();
            if (completion.course_completed) {
                quizBtn.textContent = 'Corso completato ✓';
                quizBtn.dataset.action = 'course-complete';
                delete quizBtn.dataset.nextUrl;
                const resultFeedback = document.getElementById('quiz-result-feedback');
                if (resultFeedback) {
                    resultFeedback.textContent = 'Congratulazioni! Hai completato il corso. Ottimo lavoro! 🎉';
                }
                if (status) status.textContent = '✓ Tutte le lezioni del corso sono completate';
            } else if (completion.next_lesson_url) {
                quizBtn.textContent = 'Prossima lezione →';
                quizBtn.dataset.action = 'next-lesson';
                quizBtn.dataset.nextUrl = completion.next_lesson_url;
                if (status) status.textContent = '✓ Lezione completata. Puoi passare alla prossima.';
            } else if (status) {
                status.textContent = '✓ Lezione contrassegnata come completata';
            }
            window.dispatchEvent(new CustomEvent('personal-school:lesson-completed', {
                detail: {
                    lessonId: Number(currentQuizLessonId),
                    summary: 'Hai completato la lezione superando il quiz.',
                    notification: 'Quiz superato: lezione completata!',
                },
            }));
        } catch (error) {
            console.error('Quiz lesson completion failed:', error);
            completionReported = false;
            if (status) status.textContent = 'Non sono riuscito a salvare il completamento. Riprova il quiz.';
        }
    }

    function renderCourseCongratulations() {
        if (window.PS_Realtime) window.PS_Realtime.pauseForQuiz();
        hideQuizToast();
        quizModal.hidden = false;
        quizTitle.textContent = 'Corso completato';
        quizBody.innerHTML = `
            <div class="quiz-result course-congratulations">
                <div class="course-congratulations-icon" aria-hidden="true">🎉</div>
                <h3>Congratulazioni!</h3>
                <p>Hai completato tutte le lezioni del corso. Ottimo lavoro: continua così!</p>
                <button class="quiz-next-btn" id="course-congratulations-close">Chiudi</button>
            </div>
        `;
        document.getElementById('course-congratulations-close').addEventListener('click', () => {
            quizModal.hidden = true;
            if (window.PS_Realtime) window.PS_Realtime.resumeAfterQuiz();
        });
    }

    // ── Escape HTML ────────────────────────────────────────────────
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

})();

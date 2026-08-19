/**
 * Realtime WebRTC manager for Muellima.
 *
 * Handles:
 *  - ephemeral key retrieval from Django backend
 *  - WebRTC PeerConnection setup
 *  - microphone access
 *  - remote audio playback
 *  - DataChannel events (Realtime API)
 *  - function call handling (show_illustration)
 *  - UI state management
 *  - session lifecycle / cleanup
 */
(function () {
    'use strict';

    // ── DOM elements 

    const combobox = document.getElementById('lesson-combobox');
    const startBtn = document.getElementById('start-lesson-btn');
    const micBtn = document.getElementById('mic-btn');
    const quizBtn = document.getElementById('quiz-btn');
    const endBtn = document.getElementById('end-btn');
    const statusText = document.getElementById('status-text');
    const statusDot = document.querySelector('.status-dot');
    const waveform = document.getElementById('waveform');
    const avatarWrap = document.getElementById('professor-avatar-wrap');
    const toast = document.getElementById('toast');
    const remoteAudio = document.getElementById('remote-audio');
    const illustrationArea = document.getElementById('illustration-area');
    const illustrationImg = document.getElementById('illustration-img');
    const illustrationLoader = document.getElementById('illustration-loader');
    const illustrationTitle = document.getElementById('illustration-title');
    const illustrationClose = document.getElementById('illustration-close');
    const writtenExampleArea = document.getElementById('written-example-area');
    const writtenExampleTitle = document.getElementById('written-example-title');
    const writtenExampleMeta = document.getElementById('written-example-meta');
    const writtenExampleContent = document.getElementById('written-example-content');
    const writtenExampleExplanation = document.getElementById('written-example-explanation');
    const writtenExampleClose = document.getElementById('written-example-close');
    const lessonComplete = document.getElementById('lesson-complete');
    const lessonCompleteSummary = document.getElementById('lesson-complete-summary');

    // ── State ─────────────────────────────────────────────────────
    let pc = null;               // RTCPeerConnection
    let dc = null;               // RTCDataChannel
    let localStream = null;      // MediaStream from getUserMedia
    let micEnabled = true;
    let currentLessonId = null;
    let isConnected = false;
    let initialResponseRequested = false;
    let openingInstruction = '';
    let lessonSessionId = null;
    let trialTimer = null;
    let sessionEndReported = false;
    let responseActive = false;
    let quizPaused = false;
    const handledToolCallIds = new Set();

    // ── Status management ──────────────────────────────────────────
    const STATUS_MAP = {
        disconnected:        { text: 'Disconnesso',          dot: 
'status-disconnected' },
        connecting:          { text: 'Connessione...',       dot: 
'status-thinking' },
        connected:           { text: 'Connesso',             dot: 
'status-connected' },
        listening:           { text: 'Ti sto ascoltando...', dot: 
'status-listening' },
        user_speaking:       { text: 'Ti sto ascoltando...', dot: 
'status-listening' },
        professor_thinking:  { text: 'Sto pensando...',      dot: 
'status-thinking' },
        professor_speaking:  { text: 'Professore sta parlando', dot: 
'status-speaking' },
        error:               { text: 'Errore di connessione', dot: 
'status-error' },
    };

    function setStatus(state) {
        const s = STATUS_MAP[state] || STATUS_MAP.disconnected;
        statusText.textContent = s.text;
        statusDot.className = 'status-dot ' + s.dot;

        // Waveform visible only when professor is speaking
        waveform.hidden = state !== 'professor_speaking';
        // Avatar animation when speaking
        avatarWrap.classList.toggle('speaking', state === 
'professor_speaking');
    }

    function showToast(msg, duration = 4000) {
        toast.textContent = msg;
        toast.hidden = false;
        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => { toast.hidden = true; }, duration);
    }

    // ── WebRTC support check ──────────────────────────────────────
    function checkWebRTCSupport() {
        return typeof RTCPeerConnection !== 'undefined' &&
               typeof navigator.mediaDevices !== 'undefined' &&
               typeof navigator.mediaDevices.getUserMedia !== 'undefined';
    }

    // ── Enable controls when lesson selected ──────────────────────
    combobox.addEventListener('change', () => {
        const val = combobox.value;
        startBtn.disabled = !val;
    });

    // Auto-select first lesson
    if (combobox.options.length > 0) {
        combobox.selectedIndex = 0;
        startBtn.disabled = false;
    }

    // ── Start lesson ──────────────────────────────────────────────
    startBtn.addEventListener('click', async () => {
        currentLessonId = combobox.value;
        if (!currentLessonId) return;

        if (!checkWebRTCSupport()) {
            showToast('Il tuo browser non supporta WebRTC. Usa Chrome o Firefox.');
            return;
        }

        startBtn.disabled = true;
        startBtn.textContent = 'Sto preparando il professore...';
        setStatus('connecting');

        try {
            await startRealtimeSession(currentLessonId);
        } catch (err) {
            console.error('Failed to start session:', err);
            setStatus('error');
            showToast(err.message || 'Impossibile avviare la sessione.');
            startBtn.disabled = false;
            startBtn.textContent = 'Inizia lezione';
        }
    });

    // ── Core: start Realtime session ──────────────────────────────
    async function startRealtimeSession(lessonId) {
        lessonComplete.hidden = true;

        // 1. Get ephemeral key from Django backend
        const tokenResp = await fetch('/api/realtime/session/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.PS_CSRF_TOKEN,
            },
            body: JSON.stringify({ lesson_id: parseInt(lessonId, 10) }),
        });

        if (!tokenResp.ok) {
            const errData = await tokenResp.json().catch(() => ({}));
            throw new Error(errData.error?.message || 'Errore nella creazione della sessione.');
        }

        const tokenData = await tokenResp.json();
        const ephemeralKey = tokenData.ephemeral_key;
        const model = tokenData.model;
        lessonSessionId = tokenData.lesson_session_id;
        sessionEndReported = false;
        openingInstruction = tokenData.opening_instruction || (
            `Inizia esclusivamente la lezione "${tokenData.lesson_title || ''}" ` +
            'e introduci subito il primo argomento del suo programma.'
        );

        if (!ephemeralKey) {
            throw new Error('Chiave di sessione non ricevuta.');
        }

        // 2. Get microphone access
        try {
            localStream = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true },
            });
        } catch (err) {
            if (err.name === 'NotAllowedError') {
                throw new Error('Accesso al microfono negato. Abilita il microfono nelle impostazioni del browser.');
            }
            throw new Error('Impossibile accedere al microfono.');
        }

        // 3. Create RTCPeerConnection
        pc = new RTCPeerConnection();

        // Add local audio track
        const audioTrack = localStream.getTracks()[0];
        pc.addTrack(audioTrack, localStream);

        // 4. Set up remote audio
        pc.ontrack = (event) => {
            remoteAudio.srcObject = event.streams[0];
        };

        // 5. Create DataChannel for Realtime events
        dc = pc.createDataChannel('oai-events');
        dc.onopen = () => {
            console.log('DataChannel opened');
            requestInitialProfessorResponse();
        };
        dc.onclose = () => {
            console.log('DataChannel closed');
        };
        dc.onmessage = (event) => {
            handleRealtimeEvent(JSON.parse(event.data));
        };

        // 6. Connection state monitoring
        pc.onconnectionstatechange = () => {
            console.log('Connection state:', pc.connectionState);
            if (pc.connectionState === 'connected') {
                isConnected = true;
                setStatus('connected');
                // Enable controls
                micBtn.disabled = false;
                quizBtn.disabled = false;
                endBtn.hidden = false;
                startBtn.textContent = 'Lezione in corso';
                startTrialCountdown(tokenData.trial_seconds_remaining);
                // Set initial listening state
                setTimeout(() => setStatus('listening'), 1000);
            } else if (pc.connectionState === 'failed' || pc.connectionState 
=== 'disconnected') {
                if (isConnected) {
                    setStatus('error');
                    showToast('Connessione persa. Riprova.');
                    cleanup();
                }
            }
        };

        // 7. Create offer and send to OpenAI
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // Wait for ICE gathering to complete
        await waitForIceGathering(pc);

        const sdpResp = await fetch('https://api.openai.com/v1/realtime/calls', 
{
            method: 'POST',
            body: pc.localDescription.sdp,
            headers: {
                'Authorization': `Bearer ${ephemeralKey}`,
                'Content-Type': 'application/sdp',
            },
        });

        if (!sdpResp.ok) {
            const errText = await sdpResp.text();
            console.error('SDP error:', errText);
            throw new Error('Errore nella connessione al servizio vocale.');
        }

        const answerSdp = await sdpResp.text();
        await pc.setRemoteDescription({
            type: 'answer',
            sdp: answerSdp,
        });
    }

    function startTrialCountdown(secondsRemaining) {
        if (secondsRemaining === null || secondsRemaining === undefined) return;
        clearTimeout(trialTimer);
        const seconds = Math.max(0, Number(secondsRemaining) || 0);
        trialTimer = setTimeout(async () => {
            await reportSessionEnd();
            cleanup();
            setStatus('disconnected');
            showToast('Hai terminato i 5 minuti gratuiti. Scegli un piano per continuare.', 6000);
            setTimeout(() => {
                window.location.href = `/plans/?course_id=${encodeURIComponent(window.PS_COURSE_ID)}`;
            }, 1800);
        }, seconds * 1000);
    }

    async function reportSessionEnd({ keepalive = false } = {}) {
        if (!lessonSessionId || sessionEndReported) return;
        sessionEndReported = true;
        try {
            await fetch('/api/realtime/end/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.PS_CSRF_TOKEN,
                },
                body: JSON.stringify({ lesson_session_id: lessonSessionId }),
                keepalive,
            });
        } catch (err) {
            console.warn('Session duration reporting failed:', err);
        }
    }

    // Start the lesson proactively: the professor takes the first turn as soon
    // as the Realtime data channel can accept client events.
    function requestInitialProfessorResponse() {
        if (!dc || dc.readyState !== 'open' || initialResponseRequested) return;

        initialResponseRequested = true;
        setStatus('professor_thinking');
        dc.send(JSON.stringify({
            type: 'response.create',
            response: {
                instructions: openingInstruction,
            },
        }));
    }

    // ── Wait for ICE gathering ────────────────────────────────────
    function waitForIceGathering(peerConnection, timeout = 5000) {
        return new Promise((resolve) => {
            if (peerConnection.iceGatheringState === 'complete') {
                resolve();
                return;
            }
            const timer = setTimeout(resolve, timeout);
            peerConnection.addEventListener('icegatheringstatechange', () => {
                if (peerConnection.iceGatheringState === 'complete') {
                    clearTimeout(timer);
                    resolve();
                }
            });
        });
    }

    // ── Handle Realtime API events ────────────────────────────────
    function handleRealtimeEvent(data) {
        const type = data.type;

        switch (type) {
            // Session created
            case 'session.created':
                console.log('Realtime session created');
                break;

            // User started speaking (VAD detected speech)
            case 'input_audio_buffer.speech_started':
                setStatus('user_speaking');
                break;

            // User stopped speaking (VAD detected silence)
            case 'input_audio_buffer.speech_stopped':
                setStatus('professor_thinking');
                break;

            // Professor response started
            case 'response.created':
                responseActive = true;
                setStatus('professor_thinking');
                break;

            // Professor audio started playing
            case 'response.output_audio.started':
                setStatus('professor_speaking');
                break;

            // Professor audio delta (for waveform animation)
            case 'response.output_audio.delta':
                setStatus('professor_speaking');
                break;

            // Professor response completed
            case 'response.output_audio.done':
                setStatus('listening');
                break;

            // Response fully done
            case 'response.done':
                responseActive = false;
                setStatus('listening');
                reportRealtimeUsage(data.response?.usage);
                break;

            // Function call from the model (arguments complete)
            case 'response.function_call_arguments.done':
                handleFunctionCall(data);
                break;

            // Some Realtime responses expose the completed function call as an
            // output item rather than through the arguments-done event.
            case 'response.output_item.done':
                if (data.item?.type === 'function_call') {
                    handleFunctionCall(data.item);
                }
                break;

            // Error from Realtime API
            case 'error':
                console.error('Realtime error:', data.error);
                showToast('Errore: ' + (data.error?.message || 'errore sconosciuto'));
                break;

            default:
                // Silently ignore other events
                break;
        }
    }

    function reportRealtimeUsage(usage) {
        if (!usage) return;
        fetch('/api/realtime/usage/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.PS_CSRF_TOKEN,
            },
            body: JSON.stringify({
                lesson_id: currentLessonId,
                input_tokens: usage.input_tokens || 0,
                output_tokens: usage.output_tokens || 0,
                total_tokens: usage.total_tokens || 0,
            }),
        }).catch(err => console.warn('Usage reporting failed:', err));
    }

    // ── Handle function calls ─────────────────────────────────────
    async function handleFunctionCall(data) {
        const callId = data.call_id;
        const name = data.name;
        let args = {};

        // The arguments field contains a JSON string

        try {
            args = JSON.parse(data.arguments || '{}');
        } catch (e) {
            console.error('Failed to parse function arguments:', e);
        }

        if (!callId || !name) {
            console.warn('Function call missing call_id or name:', data);
            return;
        }
        if (handledToolCallIds.has(callId)) return;
        handledToolCallIds.add(callId);

        if (name === 'show_illustration') {
            // Show illustration UI
            showIllustrationUI(args);

            // Generate the illustration via backend
            try {
                const imageResult = await generateIllustration(args);
                displayIllustration(imageResult);
                sendFunctionCallOutput(callId, {
                    shown: true,
                    message: 'L\'illustrazione è stata mostrata allo studente.',
                });
            } catch (err) {
                console.error('Illustration generation failed:', err);
                illustrationLoader.hidden = true;
                showToast('Illustrazione non disponibile.');
                sendFunctionCallOutput(callId, {
                    shown: false,
                    error: 'Non è stato possibile generare l\'illustrazione.',
                });
            }
        } else if (name === 'show_written_example') {
            displayWrittenExample(args);
            sendFunctionCallOutput(callId, {
                shown: true,
                message: 'L\'esempio scritto è stato mostrato allo studente.',
            });
        } else if (name === 'finish_lesson') {
            await finishLesson(callId, args);
        } else {
            // Unknown function — acknowledge with error
            sendFunctionCallOutput(callId, { error: 'Unknown function' });
        }
    }

    // ── Send function call output back to model ──────────────────
    async function finishLesson(callId, args) {
        const summary = args.summary || 'Hai coperto tutti gli argomenti previsti.';

        try {
            const resp = await fetch(`/api/lessons/${encodeURIComponent(currentLessonId)}/complete/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.PS_CSRF_TOKEN,
                },
                body: '{}',
            });
            if (!resp.ok) throw new Error('Lesson completion API error');

            lessonCompleteSummary.textContent = summary;
            lessonComplete.hidden = false;
            quizBtn.disabled = false;
            showToast('Lezione completata. Puoi fare il quiz.');
            window.dispatchEvent(new CustomEvent('personal-school:lesson-completed', {
                detail: { lessonId: Number(currentLessonId), summary },
            }));
            sendFunctionCallOutput(callId, {
                completed: true,
                message: 'La lezione è stata contrassegnata come completata.',
            }, false);
        } catch (err) {
            console.error('Lesson completion failed:', err);
            sendFunctionCallOutput(callId, {
                completed: false,
                error: 'Non è stato possibile salvare il completamento.',
            });
        }
    }

    function sendFunctionCallOutput(callId, output, continueResponse = true) {
        if (!dc || dc.readyState !== 'open') return;

        dc.send(JSON.stringify({
            type: 'conversation.item.create',
            item: {
                type: 'function_call_output',
                call_id: callId,
                output: JSON.stringify(output),
            },
        }));

        // Trigger the model to continue unless this tool ended the lesson.
        if (continueResponse && !quizPaused) {
            dc.send(JSON.stringify({ type: 'response.create' }));
        }
    }

    // ── Illustration handling ─────────────────────────────────────
    function showIllustrationUI(args) {
        illustrationArea.hidden = false;
        illustrationTitle.textContent = args.title || 'Illustrazione';
        illustrationImg.hidden = true;
        illustrationLoader.hidden = false;
    }

    async function generateIllustration(args) {
        const resp = await fetch('/api/illustrations/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.PS_CSRF_TOKEN,
            },
            body: JSON.stringify({
                title: args.title || '',
                concept: args.concept || '',
                visual_type: args.visual_type || 'illustration',
                description: args.description || '',
                lesson_id: Number(currentLessonId),
            }),
        });

        if (!resp.ok) {
            throw new Error('Illustration API error');
        }

        return await resp.json();
    }

    function displayIllustration(result) {
        illustrationLoader.hidden = true;
        if (result.success && result.image_url) {
            illustrationImg.src = result.image_url;
            illustrationImg.hidden = false;
        } else {
            showToast('Non sono riuscito a generare l\'illustrazione.');
        }
    }

    illustrationClose.addEventListener('click', () => {
        illustrationArea.hidden = true;
    });

    // ── Written examples (code, formulas and calculations) ───────
    function displayWrittenExample(args) {
        writtenExampleTitle.textContent = args.title || 'Supporto testuale';
        writtenExampleMeta.textContent = [args.format, args.language]
            .filter(Boolean)
            .join(' · ');
        writtenExampleContent.textContent = args.content || '';
        writtenExampleExplanation.textContent = args.explanation || '';
        writtenExampleExplanation.hidden = !args.explanation;
        writtenExampleArea.hidden = false;
    }

    writtenExampleClose.addEventListener('click', () => {
        writtenExampleArea.hidden = true;
    });

    // ── Microphone toggle ────────────────────────────────────────
    micBtn.addEventListener('click', () => {
        if (!localStream) return;
        micEnabled = !micEnabled;
        localStream.getTracks().forEach(track => {
            track.enabled = micEnabled;
        });
        micBtn.classList.toggle('active', micEnabled);
        micBtn.querySelector('.control-label').textContent = micEnabled ? 
'Microfono' : 'Mutato';
    });

    // Initialize mic button as active
    micBtn.classList.add('active');

    // ── End session ──────────────────────────────────────────────
    endBtn.addEventListener('click', async () => {
        await reportSessionEnd();
        cleanup();
        setStatus('disconnected');
        startBtn.disabled = false;
        startBtn.textContent = 'Inizia lezione';
        showToast('Lezione terminata.');
    });

    // ── Cleanup ───────────────────────────────────────────────────
    function cleanup() {
        isConnected = false;
        initialResponseRequested = false;
        handledToolCallIds.clear();
        openingInstruction = '';
        responseActive = false;
        quizPaused = false;
        clearTimeout(trialTimer);
        trialTimer = null;

        // Close DataChannel
        if (dc) {
            dc.onopen = null;
            dc.onclose = null;
            dc.onmessage = null;
            try { dc.close(); } catch (e) {}
            dc = null;
        }

        // Stop all local tracks (releases microphone)
        if (localStream) {
            localStream.getTracks().forEach(track => track.stop());
            localStream = null;
        }

        // Close PeerConnection
        if (pc) {
            pc.ontrack = null;
            pc.onconnectionstatechange = null;
            try { pc.close(); } catch (e) {}
            pc = null;
        }

        // Reset UI
        micBtn.disabled = true;
        quizBtn.disabled = true;
        endBtn.hidden = true;
        remoteAudio.srcObject = null;
    }

    // ── Cleanup on page unload ───────────────────────────────────
    window.addEventListener('beforeunload', () => {
        reportSessionEnd({ keepalive: true });
        cleanup();
    });

    // Expose cleanup for quiz.js to mute mic during quiz
    window.PS_Realtime = {
        pauseForQuiz: () => {
            quizPaused = true;
            if (localStream) {
                localStream.getTracks().forEach(t => { t.enabled = false; });
            }
            if (dc && dc.readyState === 'open') {
                if (responseActive) dc.send(JSON.stringify({ type: 'response.cancel' }));
                dc.send(JSON.stringify({ type: 'output_audio_buffer.clear' }));
            }
            remoteAudio.pause();
            setStatus('connected');
        },
        resumeAfterQuiz: () => {
            quizPaused = false;
            remoteAudio.play().catch(() => {});
            if (localStream && micEnabled) {
                localStream.getTracks().forEach(t => { t.enabled = true; });
            }
            if (isConnected) setStatus('listening');
        },
        mute: () => {
            if (localStream) {
                localStream.getTracks().forEach(t => { t.enabled = false; });
            }
        },
        unmute: () => {
            if (localStream && micEnabled) {
                localStream.getTracks().forEach(t => { t.enabled = true; });
            }
        },
        isConnected: () => isConnected,
    };

})();

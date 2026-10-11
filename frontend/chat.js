(() => {
    'use strict';

    const byId = id => document.getElementById(id);
    const apiUrl = window.PRINTER_API_URL;
    const input = byId('messageInput');
    const field = byId('messageField');
    const form = byId('messageForm');
    const sendButton = byId('sendButton');
    const plusButton = byId('plusButton');
    const menu = byId('addMenu');
    const micButton = byId('microphoneButton');
    const imageInput = byId('imageInput');
    const imageAttachment = byId('imageAttachment');
    const imagePreview = byId('imagePreview');
    const removeImageButton = byId('removeImageButton');
    const messages = byId('messages');
    const track = byId('messageTrack');
    const recording = byId('recording');
    const recordingLabel = byId('recordingLabel');
    const partialTranscript = byId('partialTranscript');
    const recordingMeter = new window.AudioMeter(byId('recordingAudioMeter'));
    const listeningMeter = new window.AudioMeter(byId('listeningAudioMeter'));
    const mic = { enabled: false, busy: false, session: null, stopping: false,
        baseText: '', partial: '', failures: 0, timer: null, maxSeconds: 30 };
    const listenSettings = byId('listenSettings');
    const liveUI = { busy: true, checking: true, session: null, available: true, error: '',
        history: null, transcript: null, jobs: new Map(), pendingDrafts: [] };
    const liveStorageKey = `samson-live-session:${apiUrl}`;
    let rememberedLiveId = null;
    try { rememberedLiveId = sessionStorage.getItem(liveStorageKey); } catch { /* Storage may be disabled. */ }
    const listener = new window.LiveListening({
        api, onChange: updateLiveControls, onStatus: showLiveSession, onFinish: finishLiveSession,
        rememberedId: rememberedLiveId,
        remember: id => {
            try {
                if (id) sessionStorage.setItem(liveStorageKey, id);
                else sessionStorage.removeItem(liveStorageKey);
            } catch { /* Recovery still discovers active sessions from the Pi. */ }
        }
    });
    let selectedImage = null;
    let imageVersion = 0;
    let imageLoading = false;
    let printQueue = Promise.resolve();
    let contentLoading = null;
    let checkingConnection = false;
    let lastVocabWord = null;
    let lastMemeUrl = null;

    const timeString = () => new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    byId('dayLabel').textContent = `Today · ${timeString()}`;
    const announce = text => { byId('liveStatus').textContent = text; };
    const scrollToLatest = () => { messages.scrollTop = messages.scrollHeight; };

    function element(tag, className, text) {
        const node = document.createElement(tag);
        node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function setConnected(connected) {
        window.SamsonSettings.setApiReachable(connected);
    }

    async function api(path, { method = 'GET', body, timeout = 10000, checkWaits = 0, onWait } = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            const response = await fetch(`${apiUrl}${path}`, {
                method, signal: controller.signal, cache: 'no-store',
                ...(body !== undefined ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
            });
            let data;
            try { data = await response.json(); }
            catch {
                const status = response.status;
                if ([504, 522, 524].includes(status)) {
                    throw new Error(`The connection to Samson timed out (HTTP ${status}).`);
                }
                if (status >= 500) throw new Error(`Samson’s connection failed (HTTP ${status}).`);
                if (response.redirected && /\/login(?:\?|$)/.test(response.url || '')) {
                    throw new Error('Your Samson session expired. Reload the page to sign in again.');
                }
                throw new Error('Samson returned an unreadable reply. Reload the page before trying again.');
            }
            setConnected(true);
            // These admission rejections prove this message has not touched the
            // printer. Wait for the existing job; never replay an attempted print.
            if (path === '/print' && response.status === 503 && data.success === false &&
                ['checking', 'busy'].includes(data.printer_state) &&
                checkWaits < (data.printer_state === 'busy' ? 120 : 10)) {
                clearTimeout(timer);
                onWait?.();
                await new Promise(resolve => setTimeout(resolve, 500));
                return api(path, { method, body, timeout, checkWaits: checkWaits + 1, onWait });
            }
            if (!response.ok || data.success === false) {
                const error = new Error(data.error || 'Samson couldn’t complete that request.');
                error.reachable = true;
                error.status = response.status;
                error.notStarted = response.status === 503 && ['checking', 'busy'].includes(data.printer_state);
                throw error;
            }
            return data;
        } catch (error) {
            if (!error.reachable) setConnected(false);
            if (error.name === 'AbortError') throw new Error('Samson took too long to reply.');
            throw error;
        } finally {
            clearTimeout(timer);
        }
    }

    function updateComposer() {
        const locked = Boolean(mic.busy || contentLoading);
        sendButton.hidden = mic.busy || (!input.value.trim() && !selectedImage);
        sendButton.disabled = locked || imageLoading;
        plusButton.disabled = locked || imageLoading;
        removeImageButton.disabled = locked || imageLoading;
        input.readOnly = locked;
        input.hidden = mic.busy;
        input.placeholder = contentLoading === 'meme' ? 'Finding a meme…'
            : contentLoading === 'word' ? 'Finding a word…'
            : selectedImage ? 'Add a message…' : 'Message Samson';
        recording.hidden = !mic.busy;
        field.classList.toggle('is-recording', mic.busy);
        micButton.disabled = liveUI.busy || imageLoading || contentLoading ||
            (mic.busy ? !mic.session || mic.stopping : !mic.enabled);
        micButton.setAttribute('aria-pressed', String(mic.busy));
        micButton.setAttribute('aria-label', liveUI.busy && !liveUI.checking
            ? 'Microphone is in use by Passive Listening' : mic.busy ? 'Stop recording' : 'Record on Samson');
        byId('startListening').disabled = !mic.enabled || liveUI.busy || !liveUI.available || locked || imageLoading;
        byId('microphoneIcon').toggleAttribute('hidden', mic.busy);
        byId('stopIcon').toggleAttribute('hidden', !mic.busy);
        if (!mic.busy) {
            input.style.height = '25px';
            input.style.height = `${Math.min(140, Math.max(25, input.scrollHeight))}px`;
        }
        const popupHeight = Math.max(100, document.querySelector('.chat-app').clientHeight -
            document.querySelector('.composer-area').offsetHeight - 16);
        listenSettings.style.maxHeight = `${Math.min(610, popupHeight)}px`;
        menu.style.maxHeight = `${popupHeight}px`;
    }

    function closeMenu() {
        menu.hidden = true;
        listenSettings.hidden = true;
        plusButton.setAttribute('aria-expanded', 'false');
    }

    function showError(text, outgoing) {
        const message = element('article', 'message incoming error-message');
        message.append(element('div', 'bubble', text));
        if (outgoing) outgoing.after(message);
        else track.append(message);
        scrollToLatest();
    }

    function addOutgoing(text, image) {
        const message = element('article', 'message outgoing');
        if (image) {
            const preview = element('img', 'message-image');
            preview.alt = image.name;
            preview.src = image.data;
            preview.addEventListener('load', scrollToLatest, { once: true });
            message.append(preview);
        }
        if (text) message.append(element('div', 'bubble', text));
        const status = element('span', 'message-meta', 'Waiting to print…');
        message.append(status);
        track.append(message);
        scrollToLatest();
        return status;
    }

    function addConfirmation(image, testMode, preview, outgoing) {
        const message = element('article', 'message incoming');
        if (testMode) {
            message.append(element('div', 'bubble', 'Ticket logged in test mode. No paper printed.'));
        }
        if (preview?.image?.startsWith('data:image/png;base64,')) {
            const ticket = element('div', 'paper-ticket');
            const printedContent = element('img', 'paper-ticket-image');
            printedContent.alt = `${testMode ? 'Ticket preview' : 'Printed ticket'}:\n${preview.text || ''}${image ? '\nPhoto included below the text.' : ''}`;
            printedContent.width = preview.width;
            printedContent.height = preview.height;
            printedContent.src = preview.image;
            printedContent.addEventListener('load', scrollToLatest, { once: true });
            ticket.append(printedContent);
            message.append(ticket);
        }
        if (!testMode) {
            const confirmation = element('div', 'print-confirmation');
            const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            icon.setAttribute('aria-hidden', 'true');
            const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
            use.setAttribute('href', '#icon-check');
            icon.append(use);
            confirmation.append(icon, element('span', '', '1 ticket printed'));
            message.append(confirmation);
        }
        outgoing.after(message);
        scrollToLatest();
    }

    function sendMessage(event) {
        event.preventDefault();
        if (mic.busy || imageLoading || contentLoading) return;
        const text = input.value.trim();
        const image = selectedImage;
        if (!text && !image) return;
        if (text.length > input.maxLength) {
            showError('Shorten the message to 1,000 characters before sending.');
            input.focus();
            return;
        }
        closeMenu();
        const status = addOutgoing(text, image);
        const body = image ? { type: 'image', content: image.data, caption: text } : { type: 'text', content: text };
        body.include_date = window.SamsonSettings.includeDate;
        body.feed_lines = window.SamsonSettings.feedLines;
        body.font_family = window.SamsonSettings.fontFamily;
        body.font_size = window.SamsonSettings.fontSize;
        input.value = '';
        clearImage();
        input.focus();
        // Snapshot each message and print in submission order while the next draft stays editable.
        printQueue = printQueue.then(() => printMessage(body, image, status));
    }

    async function printMessage(body, image, status) {
        status.textContent = 'Printing…';
        try {
            const data = await api('/print', { method: 'POST', body, timeout: 120000,
                onWait: () => { status.textContent = 'Waiting for printer…'; } });
            if (data.success !== true) throw new Error('Samson did not confirm the print.');
            window.SamsonHistory?.markCurrent(data.history_id);
            const testMode = data.test_mode === true;
            status.textContent = `${testMode ? 'Logged in test mode' : 'Printed'} · ${timeString()}`;
            addConfirmation(image, testMode, data.preview, status.parentNode);
        } catch (error) {
            status.textContent = error.notStarted ? 'Not sent' : 'Print not confirmed';
            status.classList.add('failed');
            showError(error.notStarted
                ? `${error.message} This message was not sent to the printer and is kept above.`
                : `Couldn’t confirm printing. ${error.message} Your message is kept above. Check the printer before sending it again.`, status.parentNode);
        }
    }

    function clearImage() {
        imageVersion++;
        selectedImage = null;
        imageLoading = false;
        imageInput.value = '';
        imagePreview.removeAttribute('src');
        imageAttachment.hidden = true;
        updateComposer();
    }

    async function readImage(file, name = file.name || 'Pasted image') {
        if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type)) {
            throw new Error('Choose a PNG, JPG, WebP, or GIF image.');
        }
        if (file.size > 5 * 1024 * 1024) {
            throw new Error('Choose an image smaller than 5 MB.');
        }
        const data = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error('Couldn’t read that image.'));
            reader.readAsDataURL(file);
        });
        const check = new Image();
        check.src = data;
        try { await check.decode(); }
        catch { throw new Error('Couldn’t open that image. Try another photo.'); }
        return { data, name };
    }

    function setImage(image) {
        selectedImage = image;
        imagePreview.src = image.data;
        imagePreview.alt = image.name;
        imageAttachment.hidden = false;
    }

    async function attachImage(file) {
        if (!file || mic.busy || contentLoading) return;
        const version = ++imageVersion;
        imageLoading = true;
        updateComposer();
        try {
            const image = await readImage(file);
            if (version !== imageVersion) return;
            setImage(image);
            announce('Photo attached. Add a message or send it to Samson.');
        } catch (error) {
            if (version === imageVersion) {
                imageInput.value = '';
                showError(error.message);
            }
        } finally {
            if (version === imageVersion) {
                imageLoading = false;
                updateComposer();
                input.focus();
            }
        }
    }

    async function checkMicrophone() {
        if (checkingConnection || mic.busy) return;
        checkingConnection = true;
        try {
            const data = await api('/microphone');
            mic.enabled = data.success === true && data.enabled === true;
            mic.maxSeconds = data.max_seconds || 30;
            micButton.title = mic.enabled
                ? `Samson’s microphone connected. Record for up to ${mic.maxSeconds} seconds.`
                : 'Samson’s microphone is not enabled. Complete the microphone setup on Samson, then reload.';
        } catch {
            mic.enabled = false;
            micButton.title = 'Samson’s microphone unavailable. Check Samson’s connection and microphone setup.';
        } finally {
            checkingConnection = false;
            micButton.setAttribute('aria-description', micButton.title);
            updateComposer();
            if (!listenSettings.hidden) showListenSettingsError();
        }
    }

    const elapsedTime = seconds => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

    function showListenSettingsError(message = '') {
        const text = message || (!liveUI.available ? 'Passive Listening needs the updated backend on Samson.'
            : liveUI.checking ? 'Checking Samson’s listening status…'
            : liveUI.busy ? 'A listening session is already active. Use Stop to finish it.'
            : !mic.enabled ? 'Samson’s microphone is unavailable. Check its connection and microphone setup.' : '');
        byId('listenSettingsError').textContent = text;
        byId('listenSettingsError').hidden = !text;
    }

    function updateLiveControls(state) {
        Object.assign(liveUI, state);
        const session = state.session;
        const visible = state.busy && state.trackingSession;
        const bar = byId('listeningBar');
        bar.hidden = !visible;
        bar.dataset.offline = String(state.offline);
        listeningMeter.update(visible ? session : null, { offline: state.offline, stopping: state.stopRequested });
        const label = state.offline ? 'Connection lost' : state.stopRequested ? 'Stopping…'
            : session?.state === 'recording' ? 'Listening'
            : session && ['stopping', 'error'].includes(session.state) ? 'Finishing…' : 'Starting…';
        if (byId('listeningLabel').textContent !== label) {
            byId('listeningLabel').textContent = label;
            if (visible) announce(label);
        }
        byId('listeningTime').textContent = elapsedTime(Math.max(0, Math.floor(session?.seconds || 0)));
        const cadence = session?.cadence_seconds;
        const duration = session?.duration_seconds;
        const count = session?.printed_count || 0;
        const summary = session ? [
            `Prints every ${cadence < 60 ? cadence + 's' : cadence % 60 === 0 ? cadence / 60 + 'm' : cadence + 's'}`,
            duration ? `${elapsedTime(Math.max(0, duration - session.seconds))} left` : 'Until stopped',
            `${count} ${session.test_mode ? 'logged in test mode' : 'printed'}`
        ].join(' · ') : 'Connecting to Samson…';
        byId('listeningDetails').textContent = summary;
        const warning = state.error || session?.error || session?.warning || '';
        byId('listeningWarning').textContent = warning;
        byId('listeningWarning').hidden = !warning;
        byId('stopListening').disabled = state.stopRequested || !state.busy;
        byId('stopListening').querySelector('span').textContent = state.stopRequested ? 'Stopping…' : 'Stop';
        updateComposer();
        if (!listenSettings.hidden) showListenSettingsError(state.error);
    }

    function showLiveSession(data) {
        const nearBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 100;
        if (liveUI.history?.dataset.session !== data.id) {
            liveUI.transcript?.remove();
            liveUI.jobs.clear();
            liveUI.history = element('div', 'live-history');
            liveUI.history.dataset.session = data.id;
            liveUI.history.setAttribute('aria-label', 'Tickets from listening');
            liveUI.transcript = element('article', 'message incoming live-transcript');
            liveUI.transcript.setAttribute('aria-live', 'off');
            liveUI.transcript.append(element('p', 'live-transcript-label', 'Listening on Samson'),
                element('p', 'live-transcript-text'));
            track.append(liveUI.history, liveUI.transcript);
        }
        const latestJobs = new Map([...(data.recent_jobs || []), ...(data.queued_jobs || []),
            ...[data.printing, data.failed_job].filter(Boolean)].map(job => [job.id, job]));
        const jobs = [...latestJobs.values()].sort((a, b) => a.id - b.id).slice(-20);
        for (const job of jobs) {
            if (job.state === 'printed' && window.SamsonHistory?.has(job.history_id)) continue;
            let node = liveUI.jobs.get(job.id);
            if (!node) {
                node = element('article', 'message outgoing');
                node.append(element('div', 'bubble', job.text), element('span', 'message-meta'));
                liveUI.jobs.set(job.id, node);
            }
            const meta = node.querySelector('.message-meta');
            const label = { queued: 'Waiting to print…', printing: 'Printing…',
                printed: data.test_mode ? 'Logged in test mode · no paper printed' : 'Printed from listening',
                cancelled: 'Cancelled · not printed', failed: 'Print not confirmed · check the printer' }[job.state];
            if (meta.textContent !== label) meta.textContent = label;
            meta.classList.toggle('failed', job.state === 'failed');
            if (!node.parentNode) liveUI.history.append(node);
        }
        // An indefinite session must not grow the DOM without limit.
        while (liveUI.jobs.size > 20) {
            const oldest = Math.min(...liveUI.jobs.keys());
            liveUI.jobs.get(oldest).remove();
            liveUI.jobs.delete(oldest);
        }
        liveUI.transcript.hidden = ['done', 'error'].includes(data.state) || data.state === 'stopping';
        liveUI.transcript.querySelector('.live-transcript-text').textContent = data.text || 'Speak to add to the next ticket.';
        if (nearBottom) scrollToLatest();
    }

    function restoreLiveDrafts() {
        if (mic.busy || !liveUI.pendingDrafts.length) return;
        input.value = [input.value, ...liveUI.pendingDrafts].filter(Boolean).join('\n');
        liveUI.pendingDrafts = [];
        updateComposer();
        if (input.value.length > input.maxLength) showError('The unprinted words are in your draft. Shorten it to 1,000 characters before sending.');
    }

    function finishLiveSession(data) {
        liveUI.transcript?.remove();
        if (document.activeElement === byId('stopListening')) plusButton.focus();
        if (data.text?.trim()) liveUI.pendingDrafts.push(data.text.trim());
        restoreLiveDrafts();
        if (data.error) showError(`${data.error}${data.text ? ' Unprinted words are kept in your draft.' : ''}`);
        else {
            const message = element('article', 'message incoming');
            const ended = data.stop_reason === 'duration' ? 'Listening finished.' : 'Listening stopped.';
            const text = data.text ? ' I kept the unprinted words in your draft.' : '';
            const cancelled = data.cancelled_count ? ` ${data.cancelled_count} queued ${data.cancelled_count === 1 ? 'ticket was' : 'tickets were'} cancelled.` : '';
            const warning = data.warning ? ` ${data.warning}` : '';
            message.append(element('div', 'bubble', ended + text + cancelled + warning));
            track.append(message);
            scrollToLatest();
            announce(ended);
        }
    }

    async function startListening(event) {
        event.preventDefault();
        if (byId('startListening').disabled) return;
        const cadence = Number(byId('listenCadence').value === 'custom' ? byId('customCadence').value : byId('listenCadence').value);
        const customDuration = byId('listenDuration').value === 'custom';
        const duration = Number(customDuration ? Number(byId('customDuration').value) * 60 : byId('listenDuration').value);
        if (!Number.isInteger(cadence) || cadence < 1 || cadence > 300 || !Number.isInteger(duration) ||
            duration < (customDuration ? 60 : 0) || duration > 86400 || (customDuration && duration % 60 !== 0)) {
            showListenSettingsError('Choose a print interval from 1–300 seconds and a duration up to 24 hours.');
            return;
        }
        closeMenu();
        const started = await listener.start({ cadence_seconds: cadence, duration_seconds: duration || null,
            include_date: window.SamsonSettings.includeDate });
        if (started || listener.busy) byId('stopListening').focus();
        else {
            listenSettings.hidden = false;
            plusButton.setAttribute('aria-expanded', 'true');
            showListenSettingsError(liveUI.error);
        }
    }

    function setRecordingLabel(text) {
        if (recordingLabel.textContent !== text) {
            recordingLabel.textContent = text;
            announce(text);
        }
    }

    function finishMicrophone(data) {
        clearTimeout(mic.timer);
        recordingMeter.update(null);
        const text = data.text || (data.error ? mic.partial : '');
        // Keep the complete transcript, even when it needs shortening before sending.
        input.value = [mic.baseText, text].filter(Boolean).join('\n');
        mic.session = null;
        mic.busy = false;
        mic.stopping = false;
        restoreLiveDrafts();
        partialTranscript.hidden = true;
        updateComposer();
        if (data.error) showError(data.error);
        else if (data.warning) showError(data.warning);
        else if (!text) showError('No speech detected. Move closer to Samson’s microphone and try again.');
        else announce('Recording finished. Review your message, then send it to Samson.');
        if (input.value.length > input.maxLength) {
            showError('The complete transcript is in the message box. Shorten it to 1,000 characters before sending.');
        }
        input.focus();
    }

    async function pollMicrophone() {
        const session = mic.session;
        if (!session) return;
        try {
            const data = await api(`/microphone/${encodeURIComponent(session)}`);
            if (session !== mic.session) return;
            mic.failures = 0;
            recordingMeter.update(data, { stopping: mic.stopping });
            mic.partial = data.text || '';
            partialTranscript.textContent = mic.partial;
            partialTranscript.hidden = !mic.partial;
            const seconds = Math.max(0, Math.floor(data.seconds || 0));
            byId('recordingTime').textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
            if (data.state === 'done' || data.state === 'error') {
                finishMicrophone(data);
                return;
            }
            setRecordingLabel(mic.stopping || ['stopping', 'transcribing'].includes(data.state) ? 'Finishing…'
                : data.state === 'recording' ? 'Listening…' : 'Starting…');
            mic.timer = setTimeout(pollMicrophone, data.state === 'recording' ? 250 : 500);
        } catch {
            if (session !== mic.session) return;
            mic.failures++;
            recordingMeter.update({ state: 'recording' }, { offline: true, stopping: mic.stopping });
            if (mic.failures >= 3) {
                // Best effort release; Samson also enforces its own recording deadline.
                api(`/microphone/${encodeURIComponent(session)}/stop`, { method: 'POST', body: {} }).catch(() => {});
                finishMicrophone({ text: mic.partial, error: `Connection lost. Any transcript received is kept in your draft and may be incomplete. Samson stops recording after ${mic.maxSeconds} seconds.` });
                return;
            }
            setRecordingLabel('Reconnecting…');
            mic.timer = setTimeout(pollMicrophone, 1000);
        }
    }

    async function toggleMicrophone() {
        if (liveUI.busy || imageLoading || contentLoading || !mic.enabled || mic.stopping) return;
        if (mic.session) {
            const session = mic.session;
            mic.stopping = true;
            recordingMeter.update(null);
            setRecordingLabel('Finishing…');
            updateComposer();
            try {
                await api(`/microphone/${encodeURIComponent(session)}/stop`, { method: 'POST', body: {} });
            } catch {
                if (session !== mic.session) return;
                mic.stopping = false;
                setRecordingLabel('Tap stop again');
                announce(`Could not send Stop. Try again; Samson stops after ${mic.maxSeconds} seconds.`);
                updateComposer();
            }
            return;
        }
        if (mic.busy) return;
        closeMenu();
        mic.baseText = input.value;
        mic.partial = '';
        mic.failures = 0;
        mic.busy = true;
        recordingMeter.update(null);
        partialTranscript.textContent = '';
        partialTranscript.hidden = true;
        byId('recordingTime').textContent = '0:00';
        setRecordingLabel('Starting…');
        updateComposer();
        try {
            const data = await api('/microphone/start', { method: 'POST', body: {} });
            if (!data.id) throw new Error('Samson didn’t provide a recording session.');
            mic.session = data.id;
            updateComposer();
            pollMicrophone();
        } catch (error) {
            finishMicrophone({ error: `${error.message} If recording started, Samson stops after ${mic.maxSeconds} seconds.` });
        }
    }

    // Backup definitions keep the picker useful when the dictionary is offline.
    const vocabWords = [
        ['ephemeral', 'adjective', 'Lasting for a very short time.'],
        ['serendipity', 'noun', 'The chance discovery of something pleasant or valuable.'],
        ['eloquent', 'adjective', 'Expressing ideas clearly and persuasively.'],
        ['ubiquitous', 'adjective', 'Present or found almost everywhere.'],
        ['pragmatic', 'adjective', 'Focused on practical results and real circumstances.'],
        ['resilient', 'adjective', 'Able to recover after difficulty or change.'],
        ['meticulous', 'adjective', 'Extremely careful and attentive to detail.'],
        ['candid', 'adjective', 'Honest and direct in expressing thoughts.'],
        ['diligent', 'adjective', 'Showing steady care and effort in a task.'],
        ['empathy', 'noun', 'The ability to understand and share another person’s feelings.'],
        ['ambiguous', 'adjective', 'Open to more than one interpretation.'],
        ['benevolent', 'adjective', 'Kind and wishing to help others.'],
        ['capricious', 'adjective', 'Changing suddenly and unpredictably.'],
        ['deferential', 'adjective', 'Showing respect for another person’s judgment or wishes.'],
        ['ebullient', 'adjective', 'Full of cheerful energy and enthusiasm.'],
        ['fastidious', 'adjective', 'Very particular about details, accuracy, or cleanliness.'],
        ['gregarious', 'adjective', 'Enjoying the company of other people.'],
        ['hackneyed', 'adjective', 'Overused and lacking freshness or originality.'],
        ['iconoclast', 'noun', 'Someone who challenges established beliefs or traditions.'],
        ['juxtapose', 'verb', 'To place things side by side to highlight their differences or similarities.'],
        ['kinetic', 'adjective', 'Relating to motion.'],
        ['lucid', 'adjective', 'Clear and easy to understand.'],
        ['malleable', 'adjective', 'Easily shaped, changed, or influenced.'],
        ['nonchalant', 'adjective', 'Appearing calm and unconcerned.'],
        ['obstinate', 'adjective', 'Stubbornly refusing to change an opinion or course of action.'],
        ['penchant', 'noun', 'A strong liking or habitual preference for something.'],
        ['quintessential', 'adjective', 'Representing the most typical or perfect example of something.'],
        ['reticent', 'adjective', 'Reluctant to reveal thoughts or feelings.'],
        ['sanguine', 'adjective', 'Optimistic and confident, especially in a difficult situation.'],
        ['tenacious', 'adjective', 'Determined and unwilling to give up.'],
        ['verbose', 'adjective', 'Using more words than necessary.'],
        ['whimsical', 'adjective', 'Playfully imaginative or unusual.'],
        ['zealous', 'adjective', 'Showing great enthusiasm and dedication.'],
        ['aesthetic', 'adjective', 'Relating to beauty or the appreciation of art.'],
        ['brevity', 'noun', 'Shortness in time or expression.'],
        ['cogent', 'adjective', 'Clear, logical, and convincing.'],
        ['disparate', 'adjective', 'Fundamentally different in kind or character.'],
        ['exacerbate', 'verb', 'To make a problem or unpleasant situation worse.'],
        ['fortuitous', 'adjective', 'Happening by chance rather than by design.'],
        ['gratuitous', 'adjective', 'Unnecessary or lacking a good reason.'],
        ['hyperbole', 'noun', 'Deliberate exaggeration used for emphasis.'],
        ['innate', 'adjective', 'Present from birth rather than learned.'],
        ['jovial', 'adjective', 'Cheerful and friendly.'],
        ['keen', 'adjective', 'Showing strong interest, enthusiasm, or sharp perception.'],
        ['lethargic', 'adjective', 'Lacking energy or alertness.'],
        ['mundane', 'adjective', 'Ordinary and lacking excitement.'],
        ['nuance', 'noun', 'A subtle difference in meaning, feeling, or appearance.'],
        ['ostentatious', 'adjective', 'Designed to attract attention or impress others through display.'],
        ['paradox', 'noun', 'A statement or situation that seems contradictory but may reveal a truth.'],
        ['querulous', 'adjective', 'Frequently complaining or expressing dissatisfaction.']
    ].map(([word, partOfSpeech, definition]) => ({
        word, meanings: [{ partOfSpeech, definitions: [{ definition }] }]
    }));

    function ipaToAscii(ipa) {
        const conversions = {
            'ˈ': "'", 'ˌ': ',', 'ː': ':', 'ʰ': 'h', 'ə': 'uh', 'ɜ': 'er',
            'ɐ': 'a', 'ʌ': 'u', 'æ': 'a', 'ɑ': 'ah', 'ɒ': 'o', 'ɔ': 'aw',
            'ɛ': 'e', 'ɪ': 'i', 'ʊ': 'oo', 'ʉ': 'oo', 'ɹ': 'r', 'ɾ': 'r',
            'ɽ': 'r', 'ʁ': 'r', 'ŋ': 'ng', 'ɲ': 'ny', 'ɳ': 'n', 'θ': 'th',
            'ð': 'th', 'ʃ': 'sh', 'ʒ': 'zh', 'tʃ': 'ch', 'dʒ': 'j', 'ʔ': "'",
            'j': 'y', 'ɫ': 'l', 'ɬ': 'l', 'β': 'b', 'ɸ': 'f', 'χ': 'kh',
            'ɣ': 'g', 'ʍ': 'wh', 'ʋ': 'v', 'ɥ': 'y'
        };
        return ipa.replace(/tʃ|dʒ|./gu, symbol => conversions[symbol] || symbol);
    }

    async function addVocabulary() {
        if (mic.busy || imageLoading || contentLoading) return;
        closeMenu();
        contentLoading = 'word';
        updateComposer();
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3000);
        try {
            const choices = vocabWords.filter(entry => entry.word !== lastVocabWord);
            let entry = choices[Math.floor(Math.random() * choices.length)];
            const word = entry.word;
            try {
                const response = await fetch(`https://api.dictionaryapi.dev/api/v2/entries/en/${word}`, { signal: controller.signal });
                if (!response.ok) throw new Error('Word unavailable');
                const [onlineEntry] = await response.json();
                if (onlineEntry?.word && onlineEntry.meanings?.[0]?.definitions?.[0]?.definition) entry = onlineEntry;
            } catch { /* Use the bundled definition if the dictionary is unavailable. */ }
            const meaning = entry.meanings[0];
            const definition = meaning.definitions[0];
            const phonetic = entry.phonetic || entry.phonetics?.find(item => item.text)?.text;
            const lines = [entry.word.toUpperCase()];
            if (phonetic) lines.push(ipaToAscii(phonetic));
            lines.push(`\n[${meaning.partOfSpeech}]`, `\n${definition.definition}`);
            if (definition.example) lines.push(`\nExample: "${definition.example}"`);
            input.value = [input.value.trim(), lines.join('\n')].filter(Boolean).join('\n\n');
            lastVocabWord = word;
            announce('Vocab word added to your draft. Review it before sending.');
            if (input.value.length > input.maxLength) showError('Shorten the message to 1,000 characters before sending.');
        } catch {
            showError('Couldn’t load a vocab word. Check your connection and try again.');
        } finally {
            clearTimeout(timeout);
            contentLoading = null;
            updateComposer();
            input.focus();
        }
    }

    async function addMeme() {
        if (mic.busy || imageLoading || contentLoading) return;
        closeMenu();
        contentLoading = 'meme';
        updateComposer();
        announce('Finding a random meme…');
        try {
            const query = lastMemeUrl ? `?exclude=${encodeURIComponent(lastMemeUrl)}` : '';
            const data = await api(`/random-meme${query}`, { timeout: 20000 });
            if (typeof data.image !== 'string' || !/^data:image\/(png|jpeg|webp|gif);base64,/.test(data.image)) {
                throw new Error('Invalid meme image');
            }
            const check = new Image();
            check.src = data.image;
            await check.decode();
            setImage({ data: data.image, name: data.title || 'Random meme' });
            lastMemeUrl = data.url;
            announce('Random meme attached. Review it before sending.');
        } catch (error) {
            console.warn('Could not load a random meme:', error);
            const message = 'Couldn’t load a random meme. Your draft is kept. Try again.';
            showError(message);
            announce(message);
        } finally {
            contentLoading = null;
            updateComposer();
            input.focus();
        }
    }

    form.addEventListener('submit', sendMessage);
    input.addEventListener('input', updateComposer);
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
    plusButton.addEventListener('click', () => {
        const wasOpen = !menu.hidden || !listenSettings.hidden;
        closeMenu();
        menu.hidden = wasOpen;
        plusButton.setAttribute('aria-expanded', String(!menu.hidden));
        if (!menu.hidden) byId('photoButton').focus();
    });
    document.addEventListener('click', event => {
        if (!menu.contains(event.target) && !listenSettings.contains(event.target) && !plusButton.contains(event.target)) closeMenu();
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        if (!menu.hidden || !listenSettings.hidden) { closeMenu(); plusButton.focus(); }
    });
    byId('listenButton').addEventListener('click', () => {
        menu.hidden = true;
        listenSettings.hidden = false;
        plusButton.setAttribute('aria-expanded', 'true');
        showListenSettingsError();
        byId('listenCadence').focus();
    });
    byId('closeListenSettings').addEventListener('click', () => {
        listenSettings.hidden = true;
        menu.hidden = false;
        byId('listenButton').focus();
    });
    for (const name of ['Cadence', 'Duration']) byId(`listen${name}`).addEventListener('change', () => {
        const custom = byId(`listen${name}`).value === 'custom';
        byId(`custom${name}Row`).hidden = !custom;
        byId(`custom${name}`).disabled = !custom;
        showListenSettingsError();
    });
    listenSettings.addEventListener('submit', startListening);
    byId('stopListening').addEventListener('click', () => listener.stop());
    byId('photoButton').addEventListener('click', () => { closeMenu(); imageInput.click(); });
    byId('vocabButton').addEventListener('click', addVocabulary);
    byId('memeButton').addEventListener('click', addMeme);
    imageInput.addEventListener('change', () => attachImage(imageInput.files[0]));
    removeImageButton.addEventListener('click', () => { clearImage(); input.focus(); });
    field.addEventListener('dragover', event => {
        event.preventDefault();
        if (!mic.busy && !contentLoading) field.classList.add('dragging');
    });
    field.addEventListener('dragleave', event => {
        if (!field.contains(event.relatedTarget)) field.classList.remove('dragging');
    });
    field.addEventListener('drop', event => {
        event.preventDefault();
        field.classList.remove('dragging');
        attachImage(event.dataTransfer.files[0]);
    });
    input.addEventListener('paste', event => {
        const image = [...(event.clipboardData?.items || [])].find(item => item.type.startsWith('image/'));
        if (image) { event.preventDefault(); attachImage(image.getAsFile()); }
    });
    micButton.addEventListener('click', toggleMicrophone);
    window.addEventListener('focus', checkMicrophone);
    window.addEventListener('focus', () => listener.refresh());
    window.addEventListener('pageshow', () => listener.resume());
    window.addEventListener('resize', updateComposer);
    window.addEventListener('pagehide', () => {
        clearTimeout(mic.timer);
        recordingMeter.update(null);
        listeningMeter.update(null);
        listener.suspend(); // Live mode runs on the Pi until stopped or its duration expires.
        if (mic.session) {
            fetch(`${apiUrl}/microphone/${encodeURIComponent(mic.session)}/stop`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', keepalive: true
            }).catch(() => {});
        }
    });
    updateComposer();
    checkMicrophone();
    if (window.SamsonHistory) window.SamsonHistory.ready.then(() => listener.refresh());
    else listener.refresh();
})();

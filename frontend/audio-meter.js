/* Audio activity measured on Samson, shared by both recording modes. */
(() => {
    'use strict';

    class AudioMeter {
        constructor(root, { schedule = (fn, delay) => setTimeout(fn, delay), cancel = id => clearTimeout(id) } = {}) {
            Object.assign(this, { root, schedule, cancel, timer: null });
            const document = root.ownerDocument;
            const waveform = document.createElement('span');
            waveform.className = 'audio-meter-bars';
            waveform.setAttribute('aria-hidden', 'true');
            this.bars = Array.from({ length: 7 }, () => {
                const bar = document.createElement('span');
                waveform.append(bar);
                return bar;
            });
            root.setAttribute('role', 'img');
            root.append(waveform);
            this.update(null);
        }

        update(session, { offline = false, stopping = false } = {}) {
            this.cancel(this.timer);
            this.root.hidden = !session || session.state !== 'recording' || stopping;
            const audio = session?.audio;
            const valid = !this.root.hidden && !offline && Array.isArray(audio?.levels) &&
                audio.levels.length === this.bars.length && audio.levels.every(Number.isFinite);
            this.render(valid ? audio : null);
            // A slow or disconnected request must never leave old sound on screen.
            if (valid) this.timer = this.schedule(() => this.render(null), 1500);
        }

        render(audio) {
            const state = !audio ? 'unavailable' : audio.detected ? 'sound' : 'quiet';
            const label = { sound: 'Sound detected', quiet: 'Quiet', unavailable: 'Audio level unavailable' }[state];
            this.root.dataset.state = state;
            this.root.setAttribute('aria-label', `Samson microphone: ${label}`);
            this.bars.forEach((bar, index) => {
                const level = audio ? Math.max(0, Math.min(1, audio.levels[index])) : 0;
                bar.style.transform = `scaleY(${0.12 + level * 0.88})`;
            });
        }
    }

    if (typeof module !== 'undefined' && module.exports) module.exports = { AudioMeter };
    else window.AudioMeter = AudioMeter;
})();

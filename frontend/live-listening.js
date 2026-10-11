/* Session lifecycle shared by the chat UI and dependency-free Node tests. */
(() => {
    'use strict';

    const finished = session => session && ['done', 'error'].includes(session.state) && !session.printing;

    class LiveListening {
        constructor({ api, onChange, onStatus, onFinish, remember, rememberedId = null,
                      schedule = (fn, delay) => setTimeout(fn, delay), cancel = id => clearTimeout(id) }) {
            Object.assign(this, { api, onChange, onStatus, onFinish, remember, schedule, cancel, rememberedId });
            this.state = { session: null, checking: true, starting: false, uncertain: Boolean(rememberedId),
                stopRequested: false, offline: false, error: '', available: true };
            this.latestId = null;
            this.finishedId = null;
            this.revision = 0;
            this.polling = false;
            this.mutating = false;
            this.stopSending = false;
            this.suspended = false;
            this.timer = null;
        }

        get trackingSession() {
            return this.state.starting || this.state.uncertain ||
                Boolean(this.state.session && !finished(this.state.session));
        }

        get busy() { return this.state.checking || this.trackingSession; }

        notify() { this.onChange({ ...this.state, busy: this.busy, trackingSession: this.trackingSession }); }

        later(delay = this.state.session?.state === 'recording' && !this.state.stopRequested
            ? 250 : this.busy ? 1000 : 5000) {
            this.cancel(this.timer);
            if (!this.suspended) this.timer = this.schedule(() => this.refresh(), delay);
        }

        accept(data) {
            const current = this.state.session;
            const expected = data.id && (data.id === current?.id || data.id === this.rememberedId ||
                (this.state.uncertain && data.id !== this.latestId));
            this.latestId = data.id || null;
            if (data.id && (!finished(data) || expected)) {
                this.state.session = data;
                this.state.uncertain = false;
                this.onStatus(data);
                if (finished(data)) {
                    this.state.stopRequested = false;
                    this.rememberedId = null;
                    this.remember(null);
                    if (this.finishedId !== data.id) {
                        this.finishedId = data.id;
                        this.onFinish(data);
                    }
                } else {
                    this.rememberedId = data.id;
                    this.remember(data.id);
                }
            } else {
                // A previous completed session is not a new recording or a new draft.
                this.state.uncertain = false;
                this.state.stopRequested = false;
                this.rememberedId = null;
                this.remember(null);
            }
        }

        async refresh() {
            if (this.suspended || this.polling || this.mutating) return;
            this.cancel(this.timer);
            this.polling = true;
            const revision = this.revision;
            const session = this.state.session;
            try {
                const data = await this.api(session && !finished(session)
                    ? `/microphone/${encodeURIComponent(session.id)}` : '/microphone/live');
                if (revision !== this.revision) return;
                this.state.checking = false;
                this.state.available = true;
                this.state.offline = false;
                this.state.error = '';
                this.accept(data);
            } catch (error) {
                if (revision !== this.revision) return;
                if (error.status === 404 && session && !finished(session)) {
                    // The Pi may have restarted. Discover current state before declaring it stopped.
                    this.state.session = null;
                    this.state.uncertain = true;
                } else if (error.status === 404 && !this.state.uncertain) {
                    this.state.available = false;
                    this.state.checking = false;
                }
                this.state.offline = true;
                this.state.error = !this.state.available
                    ? 'Passive Listening needs the updated backend on Samson.'
                    : this.trackingSession ? 'Connection lost. Samson may still be listening. Reconnecting…'
                    : 'Couldn’t check Samson’s listening status. Retrying…';
            } finally {
                this.polling = false;
                this.notify();
                this.later(this.state.offline ? 3000 : undefined);
            }
            if (this.state.stopRequested && this.state.session &&
                ['starting', 'recording'].includes(this.state.session.state)) this.sendStop();
        }

        async start(options) {
            if (this.busy || !this.state.available || this.mutating) return false;
            this.revision++;
            this.mutating = true;
            this.cancel(this.timer);
            this.state.starting = true;
            this.state.session = null;
            this.state.offline = false;
            this.state.error = '';
            this.state.stopRequested = false;
            this.notify();
            let accepted = false;
            try {
                const data = await this.api('/microphone/live/start', { method: 'POST', body: options });
                if (!data.id) throw new Error('Samson did not return a listening session.');
                this.state.session = data;
                this.accept(data);
                accepted = true;
            } catch (error) {
                // Never repeat a start after a lost response. Find the session with a GET.
                this.state.error = error.message;
                this.state.uncertain = !error.status || error.status >= 500;
                this.state.offline = this.state.uncertain;
            } finally {
                this.state.starting = false;
                this.mutating = false;
                this.notify();
                this.later(0);
            }
            return accepted;
        }

        stop() {
            if (!this.busy || this.state.stopRequested) return;
            this.revision++; // Ignore any GET which began before this Stop.
            this.state.stopRequested = true;
            this.state.error = '';
            this.notify();
            if (this.state.session && !finished(this.state.session)) this.sendStop();
            else this.later(0);
        }

        async sendStop() {
            if (this.stopSending || this.mutating || this.suspended) return;
            const session = this.state.session;
            if (!session || finished(session)) return;
            this.stopSending = true;
            this.mutating = true;
            this.revision++;
            this.cancel(this.timer);
            try {
                const data = await this.api(`/microphone/live/${encodeURIComponent(session.id)}/stop`, {
                    method: 'POST', body: { flush: false }
                });
                this.state.offline = false;
                this.state.error = '';
                this.accept(data);
            } catch {
                // Stop is idempotent. Preserve the user's intent and retry after reconnecting.
                this.state.offline = true;
                this.state.error = 'Stop not confirmed. Samson may still be listening. Retrying…';
            } finally {
                this.stopSending = false;
                this.mutating = false;
                this.notify();
                this.later(this.state.offline ? 3000 : 500);
            }
        }

        suspend() {
            this.suspended = true;
            this.cancel(this.timer);
        }

        resume() {
            this.suspended = false;
            this.refresh();
        }
    }

    if (typeof module !== 'undefined' && module.exports) module.exports = { LiveListening };
    else window.LiveListening = LiveListening;
})();

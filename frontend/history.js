(() => {
    'use strict';
    const byId = id => document.getElementById(id);
    const entries = byId('historyEntries');
    const notice = byId('historyNotice');
    const noticeText = byId('historyNoticeText');
    const retry = byId('historyRetry');
    const more = byId('historyMore');
    const messages = byId('messages');
    const savedIds = new Set();
    const currentIds = new Set();
    const rows = new Map();
    let before = null;
    let loading = false;
    let initialized = false;

    function element(tag, className, text) {
        const node = document.createElement(tag);
        node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function render(entry) {
        const article = element('article', 'history-entry');
        const outgoing = element('div', 'message outgoing');
        const date = new Date(entry.created_at);
        const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
        const timestamp = `${time} on ${date.toLocaleDateString('en-US')}`;
        const status = { printed: 'Printed', test_mode: 'Test preview · no paper printed',
            failed: 'Print not confirmed',
            unconfirmed: 'Print not confirmed' }[entry.status] || 'Print not confirmed';
        outgoing.append(element('div', 'bubble', entry.text || 'Photo'));
        article.append(outgoing);
        if (entry.preview?.image?.startsWith('data:image/png;base64,')) {
            const incoming = element('div', 'message incoming');
            const paper = element('div', 'paper-ticket');
            const image = element('img', 'paper-ticket-image');
            image.alt = entry.kind === 'image' ? 'Saved ticket including photo' : 'Saved ticket';
            image.width = entry.preview.width;
            image.height = entry.preview.height;
            image.loading = 'lazy';
            image.src = entry.preview.image;
            paper.append(image);
            incoming.append(paper);
            article.append(incoming);
        }
        const meta = element('time', 'message-meta', `${status} · ${timestamp}`);
        meta.dateTime = entry.created_at;
        meta.title = timestamp;
        if (['failed', 'unconfirmed'].includes(entry.status)) meta.classList.add('failed');
        outgoing.append(meta);
        return article;
    }

    async function load() {
        if (loading) return;
        loading = true;
        more.disabled = true;
        retry.disabled = true;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const query = before ? `?before=${before}` : '';
            const response = await fetch(`${window.PRINTER_API_URL}/history${query}`, {
                cache: 'no-store', signal: controller.signal
            });
            const data = await response.json();
            if (!response.ok || data.success !== true || !Array.isArray(data.entries)) {
                throw new Error('History unavailable');
            }
            const height = messages.scrollHeight;
            const top = messages.scrollTop;
            const nodes = [];
            for (const entry of data.entries) {
                if (savedIds.has(entry.id)) continue;
                savedIds.add(entry.id);
                if (currentIds.has(entry.id)) continue;
                const row = render(entry);
                rows.set(entry.id, row);
                nodes.push(row);
            }
            entries.prepend(...nodes);
            before = data.next_before;
            more.hidden = !before;
            more.textContent = 'Load older tickets';
            byId('historyTitle').hidden = false;
            notice.hidden = savedIds.size > 0;
            noticeText.textContent = 'No saved tickets yet. New prints will appear here when you return.';
            retry.hidden = true;
            // Preserve the reading position while adding earlier pages. On first
            // load, land at the newest saved tickets and the composer.
            messages.scrollTop = initialized ? top + messages.scrollHeight - height : messages.scrollHeight;
            initialized = true;
        } catch {
            byId('historyTitle').hidden = true;
            notice.hidden = false;
            noticeText.textContent = 'Couldn’t load message history.';
            retry.hidden = false;
            more.hidden = true;
        } finally {
            clearTimeout(timer);
            more.disabled = false;
            retry.disabled = false;
            loading = false;
        }
    }

    more.addEventListener('click', load);
    retry.addEventListener('click', load);
    window.SamsonHistory = {
        has: id => savedIds.has(id),
        markCurrent(id) {
            if (!Number.isInteger(id)) return;
            currentIds.add(id);
            rows.get(id)?.remove();
            rows.delete(id);
            if (initialized) notice.hidden = true;
        },
        ready: load()
    };
})();

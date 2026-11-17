function showError(msg, retryable) {
    let banner = document.querySelector('.error-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.className = 'error-banner';
        document.querySelector('.container').prepend(banner);
    }
    banner.innerHTML = `<span>${msg}</span>` + (retryable ? '<button onclick="location.reload()">Retry</button>' : '');
}

async function api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch('/api' + path, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        showError(err.error || 'Request failed', err.retryable);
        throw new Error(err.error);
    }
    const banner = document.querySelector('.error-banner');
    if (banner) banner.remove();
    if (res.status === 204) return null;
    return res.json();
}

async function completeTodo(id) {
    await api('PATCH', '/todos/' + id, { status: 'done' });
    location.reload();
}

async function reopenTodo(id) {
    await api('PATCH', '/todos/' + id, { status: 'pending' });
    location.reload();
}

async function waitTodo(id) {
    const target = prompt('Waiting for whom/what?');
    if (target === null) return;
    await api('PATCH', '/todos/' + id, { status: 'waiting', wait_target: target });
    location.reload();
}

async function deleteTodo(id) {
    if (!confirm('Delete this to-do?')) return;
    await api('DELETE', '/todos/' + id);
    location.reload();
}

async function addTodo(e) {
    e.preventDefault();
    const f = e.target;
    await api('POST', '/todos', {
        title: f.title.value,
        next_followup: f.next_followup.value || null,
    });
    location.reload();
    return false;
}

async function addTodoFull(e) {
    e.preventDefault();
    const f = e.target;
    await api('POST', '/todos', {
        title: f.title.value,
        description: f.description.value || null,
        status: f.status.value,
        wait_target: f.wait_target.value || null,
        due_date: f.due_date.value || null,
        next_followup: f.next_followup.value || null,
    });
    location.reload();
    return false;
}

async function saveEvent(e, id) {
    e.preventDefault();
    const f = e.target;
    await api('PATCH', '/events/' + id, {
        summary: f.summary.value,
        detail: f.detail.value || null,
        evidence_url: f.evidence_url.value || null,
        root_cause: f.root_cause.value || null,
        root_cause_confirmed: f.root_cause_confirmed.checked,
    });
    location.reload();
    return false;
}

async function addAccomplishment(e) {
    e.preventDefault();
    const f = e.target;
    await api('POST', '/accomplishments', {
        title: f.title.value,
        occurred_at: f.occurred_at.value + 'T00:00:00',
        impact: f.impact.value || null,
        impact_evidence_url: f.impact_evidence_url.value || null,
        is_highlight: f.is_highlight.checked,
    });
    location.reload();
    return false;
}

async function generateNarrative(period) {
    const box = document.getElementById('narrative-box');
    box.innerHTML = '<div class="card"><p>Synthesizing narrative…</p></div>';
    try {
        const res = await api('POST', '/export/narrative', { period });
        box.innerHTML = '<div class="card highlight"><div class="card-header"><strong>Narrative</strong></div><p style="white-space:pre-wrap">' +
            res.narrative.replace(/</g, '&lt;') + '</p></div>';
    } catch (err) {
        box.innerHTML = '';
    }
}
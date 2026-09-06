"""The console's client-side script.

Plain JavaScript, no build step and no dependency, for the same reason the
rest of the project has none: a reviewer should be able to open this from a
clean checkout. Every mutation goes through the server, which is the only
thing allowed to touch the decision log.
"""

CONSOLE_JS = """
const TOKEN = document.body.dataset.token;
let state = null;
let previousQueue = null;
const reopened = new Set();

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function call(path, body) {
  const res = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: {'Content-Type': 'application/json', 'X-Recon-Token': TOKEN},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({error: res.statusText}));
    throw new Error(detail.error || 'request failed');
  }
  return res.json();
}

function card(label, value, note, tone, moved) {
  return `<div class="card${moved ? ' moved' : ''}">
    <div class="label">${esc(label)}</div>
    <div class="value ${tone || ''}">${esc(value)}</div>
    <div class="note">${note}</div></div>`;
}

function metrics() {
  const now = state.now, base = state.baseline;
  const gain = (now.rate - base.rate).toFixed(1);
  const shrunk = base.human_queue - now.human_queue;
  const moved = previousQueue !== null && previousQueue !== now.human_queue;
  return [
    card('straight through', now.rate + '%',
      gain > 0 ? `<span class="delta">+${gain} pts from ${base.rate}%</span>`
               : `${now.straight_through} of ${now.total_cases} cases`,
      'good', moved),
    card('human queue', String(now.human_queue),
      shrunk > 0 ? `<span class="delta">${shrunk} fewer than at the start</span>`
                 : 'cases waiting on a person',
      now.human_queue ? 'warn' : 'good', moved),
    card('incorrect postings', String(now.incorrect),
      'wrong links applied without review', now.incorrect ? 'bad' : 'good', false),
    card('rules learned', String(state.knowledge.facts.length),
      `${state.confirmed} confirmed, ${state.rejected} rejected`, '', moved),
  ].join('');
}

function caseRow(item) {
  const open = !item.decision || reopened.has(item.case_ref);
  const settled = open ? '' : ` settled ${item.decision}`;
  const buttons = open
    ? `<div class="buttons">
         <button class="yes" data-yes="${esc(item.case_ref)}">Confirm</button>
         <button class="no" data-no="${esc(item.case_ref)}">Reject</button></div>`
    : `<span class="verdict ${item.decision}">${esc(item.decision)}</span>
       <button class="ghost" data-change="${esc(item.case_ref)}">Change</button>`;
  return `<div class="case${settled}">
    <div>
      <h4><span class="pill ${esc(item.disposition)}">${esc(item.disposition)}</span>
        ${esc(item.break_type)}</h4>
      <p>${esc(item.rationale)}</p>
      <div class="why mono">${esc(item.records.join(', '))}</div>
      <div class="why">${item.blockers.map(esc).join(' &middot; ')}</div>
    </div>
    <div class="side">
      <span class="amount">${esc(item.residual)}</span>
      <span class="why">confidence ${item.confidence.toFixed(2)}</span>
      ${buttons}
    </div></div>`;
}

function learned() {
  if (!state.knowledge.facts.length) {
    return `<p class="sub">Nothing learned yet. Confirm at least
      ${state.min_support} cases that share a pattern, then promote.</p>`;
  }
  return `<ul class="facts">${state.knowledge.facts.map((f) =>
    `<li><strong>${esc(f.kind)}</strong> &mdash; ${esc(f.note)}</li>`).join('')}</ul>`;
}

function banner() {
  if (!state.promotions.length) return '';
  return `<div class="banner"><h3>Promoted into deterministic rules</h3><ul>${
    state.promotions.map((p) => `<li>${esc(p.note)}</li>`).join('')}</ul></div>`;
}

function render() {
  document.getElementById('metrics').innerHTML = metrics();
  document.getElementById('banner').innerHTML = banner();
  document.getElementById('learned').innerHTML = learned();
  const open = state.queue;
  document.getElementById('queue').innerHTML = open.length
    ? open.map(caseRow).join('')
    : `<div class="empty">The queue is empty. Every case was cleared without a
       person, and nothing was posted wrongly.</div>`;
  document.getElementById('count').textContent =
    `${open.length} case${open.length === 1 ? '' : 's'}`;
  document.getElementById('promote').disabled = state.confirmed === 0;
  previousQueue = state.now.human_queue;
}

async function act(fn) {
  document.body.style.cursor = 'progress';
  try { state = await fn(); render(); }
  catch (err) { alert(err.message); }
  finally { document.body.style.cursor = ''; }
}

document.addEventListener('click', (event) => {
  const yes = event.target.closest('[data-yes]');
  const no = event.target.closest('[data-no]');
  if (yes) { reopened.delete(yes.dataset.yes); act(() => call('/api/decision',
    {case_ref: yes.dataset.yes, outcome: 'confirmed'})); }
  if (no) { reopened.delete(no.dataset.no); act(() => call('/api/decision',
    {case_ref: no.dataset.no, outcome: 'rejected'})); }
  const change = event.target.closest('[data-change]');
  if (change) { reopened.add(change.dataset.change); render(); }
  if (event.target.id === 'promote') act(() => call('/api/promote', {}));
  if (event.target.id === 'reset') act(() => call('/api/reset', {}));
});

act(() => call('/api/state'));
"""

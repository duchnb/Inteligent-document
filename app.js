const el = id => document.getElementById(id);
const $out = el('out');

// Show JS/promise errors in the Status bar
window.addEventListener('error', e => setStatus(`JS error: ${e.message}`, false));
window.addEventListener('unhandledrejection', e => setStatus(`Promise error: ${e.reason}`, false));

function setStatus(msg, good = true) {
  const s = el('status');
  s.textContent = msg;
  s.className = good ? 'ok' : 'warn';
}

function clearOut() {
  $out.innerHTML = '';
  setStatus('Ready', true);
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, m => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[m]));
}

function fmt(n) { return (typeof n === 'number') ? n.toFixed(4) : n; }

function renderMD(md) {
  if (!md) return '';
  try {
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
      console.warn('Markdown libs missing; falling back to plaintext.');
      return `<pre>${escapeHtml(md)}</pre>`;
    }
    const html = marked.parse(md);
    return DOMPurify.sanitize(html);
  } catch (err) {
    console.error('renderMD failed:', err);
    setStatus('Markdown render error — fell back to raw', false);
    return `<pre>${escapeHtml(md)}</pre>`;
  }
}

function renderAnswer(data) {
  const md = data.answer_md || '';
  const raw = data.answer_raw || data.answer || '(no answer)';
  const isPolished = Boolean(data.answer_md);

  const div = document.createElement('div');
  div.className = 'card grid';
  div.innerHTML = `
    <h1>Answer</h1>
    <div class="result">
        ${
      isPolished
        ? `<div class="muted" style="margin-bottom:6px">Polished (Markdown)</div>
               <div class="md">${renderMD(md)}</div>`
        : `<div class="muted" style="margin-bottom:6px">Raw</div>
               <div>${escapeHtml(raw)}</div>`
    }
      </div>

      <div class="stack">
        <div class="muted">Citations</div>
        ${(data.citations || []).map(c => `
          <div class="result">
            <div class="kvs">
              <div>Score</div><div>${fmt(c.score)}</div>
              <div>Page</div><div>${c.page ?? '-'}</div>
              <div>Chunk</div><div><code>${c.chunkId}</code></div>
              <div>Source</div><div><code>${c.source}</code></div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  $out.prepend(div);
}

function renderSearch(data) {
  const div = document.createElement('div');
  div.className = 'card grid';
  div.innerHTML = `
      <h1>Top Matches</h1>
      ${(data.top_k || []).map(t => `
        <div class="result">
          <div class="kvs">
            <div>Score</div><div>${fmt(t.score)}</div>
            <div>Page</div><div>${t.page ?? '-'}</div>
            <div>Chunk</div><div><code>${t.chunkId}</code></div>
            <div>Source</div><div><code>${t.source}</code></div>
          </div>
          <div class="muted" style="margin-top:8px">Preview</div>
          <div>${escapeHtml((t.text || '').slice(0, 800))}</div>
        </div>
      `).join('')}
    `;
  $out.prepend(div);
}

// ----- Busy overlay + control locking -----
let BUSY = false;
function setBusy(on, text) {
  BUSY = !!on;
  const layer = document.getElementById('busy-layer');
  if (!layer) return;
  const label = layer.querySelector('.label');
  if (text && label) label.textContent = text;

  // Disable all buttons while busy
  document.querySelectorAll('button').forEach(b => b.disabled = !!on);

  // Toggle overlay visibility
  layer.classList.toggle('show', !!on);
}

// ----- API base handling -----
function getApiBase() {
  const v = el('apiBase')?.value?.trim();
  if (v) return v.replace(/\/+$/, '');
  // default to same-origin (CloudFront routes /answer|/search|/upload to API)
  return location.origin;
}

(function bootstrapApiBase() {
  const params = new URLSearchParams(location.search);
  const override = params.get('api');
  if (override) {
    el('apiBase').value = override;
    el('apiRow').style.display = ''; // show field when overriding
    setStatus('Using API override from ?api=', true);
  } else {
    // keep hidden and use same-origin
    el('apiRow').style.display = 'none';
  }
})();

// ----- Fetch with guards -----
async function doFetch(path, payload) {
  const base = getApiBase();
  const url  = base + path;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload || {})
    });
    const txt = await res.text();
    let data = {};
    try { data = JSON.parse(txt); } catch {}
    if (!res.ok) {
      setStatus(`HTTP ${res.status} — see console`, false);
      console.warn('Error response body:', txt);
      return null;
    }
    setStatus('OK', true);
    return data;
  } catch (err) {
    setStatus('Network/CORS error — see console', false);
    console.error('Fetch failed:', err);
    return null;
  }
}

// ----- Actions (with busy overlay & double-click guard) -----
async function doSearch() {
  if (BUSY) { setStatus('Please wait — still processing…', false); return; }
  const q = el('query').value.trim();
  const k = parseInt(el('topk').value || '5', 10);
  if (!q) { setStatus('Enter a query', false); return; }

  // Auto-clear previous results if present (same as clicking Clear)
  if ($out && $out.childElementCount > 0) { clearOut(); }

  setBusy(true, 'Searching…');
  try {
    const data = await doFetch('/search', {query: q, top_k: k});
    if (data) renderSearch(data);
  } finally {
    setBusy(false);
  }
}

async function doAnswer() {
  if (BUSY) { setStatus('Please wait — still processing…', false); return; }
  const q = el('query').value.trim();
  const k = parseInt(el('topk').value || '5', 10);
  if (!q) { setStatus('Enter a query', false); return; }

  // Auto-clear previous results if present (same as clicking Clear)
  if ($out && $out.childElementCount > 0) { clearOut(); }

  setBusy(true, 'Answering…');
  try {
    const data = await doFetch('/answer', {query: q, top_k: k});
    if (data) renderAnswer(data);
  } finally {
    setBusy(false);
  }
}

async function doUpload() {
  if (BUSY) { setStatus('Please wait — still processing…', false); return; }
  const base = getApiBase();
  const f = document.getElementById('file').files[0];
  if (!f) { setStatus('Choose a file', false); return; }

  setBusy(true, 'Requesting upload URL…');
  try {
    // 1) Ask API for a signed URL
    const upMetaRes = await fetch(base.replace(/\/+$/, '') + '/upload', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({ filename: f.name, contentType: f.type || 'application/pdf' })
    }).catch(err => {
      console.error('upload/meta fetch error', err);
      return null;
    });

    if (!upMetaRes) { setStatus('Upload URL error (network)', false); return; }

    let upMeta = {};
    try { upMeta = await upMetaRes.json(); } catch { upMeta = {}; }
    if (!upMeta.uploadUrl || !upMeta.key) {
      setStatus('Upload URL error (payload)', false);
      console.warn('upload/meta error', upMeta);
      return;
    }

    // 2) PUT file directly to S3
    setBusy(true, 'Uploading to S3…');
    const putRes = await fetch(upMeta.uploadUrl, {
      method: 'PUT',
      headers: {'content-type': f.type || 'application/pdf'},
      body: f
    });

    if (!putRes.ok) {
      setStatus('S3 PUT failed', false);
      console.warn('S3 PUT error', await putRes.text());
      return;
    }

    setStatus('Uploaded OK — processing…', true);

    // Show where it went
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
        <div class="kvs">
        <div>Key</div><div><code>${upMeta.key}</code></div>
        <div>S3 URI</div><div><code>${upMeta.s3Uri}</code></div>
    <div>Type</div><div>${upMeta.contentType}</div>
    </div>`;
    document.getElementById('out').prepend(card);
  } catch (err) {
    setStatus('Upload failed — see console', false);
    console.error(err);
  } finally {
    setBusy(false);
  }
}

// Sync the Top-K numeric display with the slider
(function initTopK() {
  const slider = el('topk');
  const label = document.getElementById('topkVal');
  if (slider && label) {
    const sync = () => { label.textContent = String(slider.value); };
    slider.addEventListener('input', sync);
    slider.addEventListener('change', sync);
    sync();
  }
})();

const $ = (id) => document.getElementById(id);
const urlInput = $('url'), qlist = $('qlist'), statusEl = $('status'), metaEl = $('meta');
const barWrap = $('barWrap'), bar = $('bar');
const videoBox = $('video'), thumb = $('thumb'), vtitle = $('vtitle'), vmeta = $('vmeta');
const dlBtn = $('dlBtn'), pauseBtn = $('pauseBtn'), cancelBtn = $('cancelBtn');
const SERVER = 'http://127.0.0.1:8000';

let qualities = [], selected = 'best', jobId = null, timer = null, isPaused = false;
let lastInfo = null;

function setStatus(s) { statusEl.textContent = s || ''; }
function setMeta(s) { metaEl.textContent = s || ''; }
function setBar(pct) {
  barWrap.style.display = pct == null ? 'none' : 'block';
  if (pct != null) bar.style.width = `${Math.min(100, pct)}%`;
}
function fmtSpeed(bps) { return bps ? `${(bps/1000/1000).toFixed(2)} MB/s` : ''; }
function fmtMB(b) { return b ? `${(b/1000/1000).toFixed(1)} MB` : ''; }
function fmtDur(s) { if (!s) return ''; const m = Math.floor(s/60), r = Math.floor(s%60); return `${m}:${String(r).padStart(2,'0')}`; }

function renderQualities() {
  qlist.innerHTML = '';
  qualities.forEach(q => {
    const div = document.createElement('label');
    div.className = 'q' + (q.key === selected ? ' sel' : '');
    // sizes from /api/info are estimates (filesize_approx) -> prefix ≈
    const sz = q.size ? `≈${q.size}` : '—';
    div.innerHTML = `<input type="radio" name="q" ${q.key===selected?'checked':''}><span class="lbl">${q.label}</span><span class="size">${sz}</span>`;
    div.onclick = () => { selected = q.key; renderQualities(); };
    qlist.appendChild(div);
  });
}

async function loadInfo(auto = false) {
  const url = urlInput.value.trim();
  if (!url) { if (!auto) setStatus('Paste a URL first'); return; }
  setStatus('Fetching qualities…'); setMeta('');
  try {
    const r = await fetch(`${SERVER}/api/info?url=${encodeURIComponent(url)}`);
    const j = await r.json();
    if (!r.ok) return setStatus('Error: ' + (j.error || r.status));
    lastInfo = j;
    vtitle.textContent = j.title || '';
    vmeta.textContent = `${j.uploader || ''} ${j.duration ? '• ' + fmtDur(j.duration) : ''}`;
    if (j.thumbnail) thumb.src = j.thumbnail;
    videoBox.style.display = 'flex';
    qualities = j.qualities || [];
    // Backward compat: old server returns `formats` not `qualities`
    if (!qualities.length && j.formats?.length) {
      qualities = [{ key: 'best', label: 'Best • auto merge', size: '' },
        { key: '1080p', label: '1080p • mp4', size: '' },
        { key: '720p', label: '720p • mp4', size: '' },
        { key: '480p', label: '480p • mp4', size: '' },
        { key: 'audio', label: 'Audio only • mp3', size: '' }];
    }
    // If server still old / restart pending
    if (!qualities.length) {
      setStatus('Server outdated — restart python server.py, using defaults');
      qualities = [{ key: 'best', label: 'Best • auto merge', size: '' },
        { key: '1080p', label: '1080p • mp4', size: '' },
        { key: '720p', label: '720p • mp4', size: '' },
        { key: 'audio', label: 'Audio only • mp3', size: '' }];
    }
    if (!qualities.find(q => q.key === selected)) selected = (qualities[0] || {}).key || 'best';
    renderQualities();
    setStatus(`Found ${qualities.length} options`);
  } catch (e) {
    setStatus('Server not running? Start: python server.py');
  }
}

async function downloadThumbnail() {
  const url = urlInput.value.trim();
  if (!url) return setStatus('Paste a URL first');
  setStatus('Fetching HD thumbnail…');
  try {
    // Ask server for direct JPG URL + video filename first.
    // This avoids the old thumbnail.htm failure where chrome.downloads
    // saved a JSON error as .htm.
    const title = lastInfo?.title || vtitle.textContent || '';
    const r = await fetch(`${SERVER}/api/thumbnail?url=${encodeURIComponent(url)}&title=${encodeURIComponent(title)}&json=1`);
    const j = await r.json();
    if (!r.ok) return setStatus('Thumb failed: ' + (j.error || r.status));
    await chrome.downloads.download({
      url: j.thumb_url,
      filename: j.filename || 'thumbnail.jpg',
      saveAs: true
    });
    setStatus('Thumbnail JPG save started ✓');
  } catch (e) {
    setStatus('Thumb failed, is server.py running? ' + e.message);
  }
}

$('thumbBtn').onclick = () => downloadThumbnail(false);
thumb.style.cursor = 'pointer';
thumb.onclick = () => downloadThumbnail(false);
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  if (tabs[0]?.url && tabs[0].url.startsWith('http')) {
    urlInput.value = tabs[0].url;
    loadInfo(true);
  }
});

function showActive(active) {
  cancelBtn.style.display = active ? 'block' : 'none';
  pauseBtn.style.display = active ? 'block' : 'none';
  dlBtn.disabled = active;
  dlBtn.style.opacity = active ? .5 : 1;
}

function stopPoll() { if (timer) clearInterval(timer); timer = null; }

dlBtn.onclick = async () => {
  const url = urlInput.value.trim();
  if (!url) return setStatus('Paste a URL first');
  stopPoll(); setBar(0); setMeta('queued…'); setStatus('Starting…');
  try {
    const r = await fetch(`${SERVER}/api/start`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, quality: selected })
    });
    const j = await r.json();
    if (!r.ok) return setStatus('Error: ' + j.error);
    jobId = j.job_id; isPaused = false; pauseBtn.textContent = '⏸ Pause';
    showActive(true);
    timer = setInterval(poll, 600);
  } catch (e) { setStatus('Server not running?'); }
};

async function poll() {
  if (!jobId) return;
  try {
    const pr = await fetch(`${SERVER}/api/progress?job_id=${jobId}`);
    const p = await pr.json();
    if (!pr.ok) { stopPoll(); showActive(false); return setStatus('Error: ' + p.error); }
    const pct = p.pct || 0;
    setBar(pct);
    if (['downloading','starting','queued','merging'].includes(p.status)) {
      setMeta(`${pct.toFixed(1)}% • ${fmtMB(p.downloaded)} / ${fmtMB(p.total)} • ${fmtSpeed(p.speed)} ${p.eta!=null?'• ETA '+p.eta+'s':''}\n${p.status} ${p.title||''}`);
      setStatus(`${p.title || ''}`);
    } else if (p.status === 'paused' || p.status === 'pausing') {
      setMeta(`Paused at ${pct.toFixed(1)}% — resume anytime, .part kept`);
      setStatus('Paused');
    } else if (p.status === 'done') {
      stopPoll(); setBar(100);
      const actual = p.file_size_str ? `Actual ${p.file_size_str}` : '';
      setMeta(`Done • ${actual}\nStarting browser save…`);
      await chrome.downloads.download({ url: `${SERVER}/api/file?job_id=${jobId}`, saveAs: true });
      setStatus(`Saved ✓ ${actual} — check downloads bar`);
      showActive(false); jobId = null;
    } else if (p.status === 'cancelled' || p.status === 'cancelling') {
      stopPoll(); showActive(false); setBar(null); setMeta(''); setStatus('Cancelled'); jobId = null;
    } else if (p.status === 'error') {
      stopPoll(); showActive(false); setStatus('Failed: ' + (p.error || 'unknown'));
    }
  } catch (e) { stopPoll(); showActive(false); setStatus('Poll failed: ' + e.message); }
}

cancelBtn.onclick = async () => {
  if (!jobId) return;
  await fetch(`${SERVER}/api/cancel`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ job_id: jobId }) });
  setStatus('Cancelling…');
};

pauseBtn.onclick = async () => {
  if (!jobId) return;
  if (!isPaused) {
    await fetch(`${SERVER}/api/pause`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ job_id: jobId }) });
    isPaused = true; pauseBtn.textContent = '▶ Resume';
    setStatus('Pausing… (.part kept for resume)');
  } else {
    await fetch(`${SERVER}/api/resume`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ job_id: jobId }) });
    isPaused = false; pauseBtn.textContent = '⏸ Pause';
    setStatus('Resumed…');
    if (!timer) timer = setInterval(poll, 600);
  }
};

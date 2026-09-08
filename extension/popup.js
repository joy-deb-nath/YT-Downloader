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
  // Instant server-free preview (thumb + title via i.ytimg.com + oEmbed).
  // Fire-and-forget: server response below overwrites with richer data.
  showServerFreePreview(url);
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
    // Server down (needed for video qualities), but thumb + title preview
    // already attempted above — make sure they finished before reporting.
    const vid = extractVideoId(urlInput.value.trim());
    if (vid) {
      await showServerFreePreview(urlInput.value.trim());
      setStatus('Server not running — video needs python server.py, but Thumb + title work ✓');
      return;
    }
    setStatus('Server not running? Start: python server.py');
  }
}

function extractVideoId(url) {
  if (!url) return '';
  try {
    const u = new URL(url);
    if (u.hostname.includes('youtu.be')) return u.pathname.split('/')[1]?.split('?')[0] || '';
    const v = u.searchParams.get('v');
    if (v) return v;
    const m = url.match(/(?:\/shorts\/|\/embed\/|\/live\/|\/v\/)([A-Za-z0-9_-]{6,})/);
    if (m) return m[1];
  } catch { /* fall through to regex */ }
  const m = String(url).match(/(?:v=|\/shorts\/|\/embed\/|\/live\/|youtu\.be\/)([A-Za-z0-9_-]{6,})/);
  return m ? m[1] : '';
}

function thumbCandidates(vid) {
  const base = `https://i.ytimg.com/vi/${vid}`;
  return [`${base}/maxresdefault.jpg`, `${base}/sddefault.jpg`,
          `${base}/hqdefault.jpg`, `${base}/mqdefault.jpg`];
}

// Probe via <img> load (no CORS needed). Rejects 404s and the tiny
// 120x90 placeholder YouTube serves when a size is missing.
function probeImage(url, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    let done = false;
    const to = setTimeout(() => { if (!done) { done = true; img.src = ''; reject(new Error('timeout')); } }, timeoutMs);
    img.onload = () => {
      if (done) return; done = true; clearTimeout(to);
      if ((img.naturalWidth || 0) <= 120) reject(new Error('placeholder'));
      else resolve(url);
    };
    img.onerror = () => { if (done) return; done = true; clearTimeout(to); reject(new Error('not found')); };
    img.src = url;
  });
}

async function resolveBestThumbUrl(vid) {
  for (const u of thumbCandidates(vid)) {
    try { await probeImage(u); return u; } catch { /* try next size down */ }
  }
  throw new Error('No thumbnail found');
}

// Server-free title/author via YouTube oEmbed (no key needed).
// Shorts/embed/live IDs are normalized to a watch URL first.
async function fetchOembedPreview(vid) {
  const watchUrl = `https://www.youtube.com/watch?v=${vid}`;
  try {
    const r = await fetch(`https://www.youtube.com/oembed?url=${encodeURIComponent(watchUrl)}&format=json`);
    if (r.ok) {
      const j = await r.json();
      if (j.title) return { title: j.title, uploader: j.author_name || '' };
    }
  } catch { /* fall through to proxy */ }
  try {
    const r2 = await fetch(`https://noembed.com/embed?url=${encodeURIComponent(watchUrl)}`);
    if (r2.ok) {
      const j2 = await r2.json();
      if (j2.title) return { title: j2.title, uploader: j2.author_name || '' };
    }
  } catch { /* offline / blocked */ }
  return null;
}

// Best-effort preview without server.py: thumbnail + title + author.
// Never throws; safe to fire-and-forget. Returns true if YouTube ID found.
async function showServerFreePreview(pageUrl) {
  const vid = extractVideoId(pageUrl);
  if (!vid) return false;
  videoBox.style.display = 'flex';
  const thumbP = resolveBestThumbUrl(vid).then(u => { thumb.src = u; }).catch(() => {});
  const metaP = fetchOembedPreview(vid).then(p => {
    if (p?.title) {
      vtitle.textContent = p.title;
      vmeta.textContent = p.uploader || '';
      // Seed lastInfo so the Thumb filename works with no server
      lastInfo = { ...(lastInfo || {}), title: p.title, uploader: p.uploader };
    }
  }).catch(() => {});
  await Promise.allSettled([thumbP, metaP]);
  return true;
}

function sanitizeTitle(s) {
  return (s || '').replace(/[\\/*?:"<>|]/g, '').trim().slice(0, 80);
}

async function downloadThumbnailViaServer(pageUrl, title) {
  // Fallback for non-YouTube URLs (yt-dlp thumbnail pick). Needs server.py.
  const r = await fetch(`${SERVER}/api/thumbnail?url=${encodeURIComponent(pageUrl)}&title=${encodeURIComponent(title)}&json=1`);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.status);
  await chrome.downloads.download({
    url: j.thumb_url,
    filename: j.filename || 'thumbnail.jpg',
    saveAs: true
  });
}

async function downloadThumbnail() {
  const pageUrl = urlInput.value.trim();
  if (!pageUrl) return setStatus('Paste a URL first');
  const vid = extractVideoId(pageUrl);
  // Non-YouTube URL: direct thumbs don't exist, fall back to server.
  if (!vid) {
    const serverTitle = sanitizeTitle(lastInfo?.title || vtitle.textContent) || 'thumbnail';
    setStatus('Non-YouTube URL — trying server…');
    try {
      await downloadThumbnailViaServer(pageUrl, serverTitle);
      setStatus('Thumbnail JPG save started ✓');
    } catch (e) {
      setStatus('Thumb needs a YouTube URL, or start server.py: ' + e.message);
    }
    return;
  }
  // YouTube: fully client-side, no server needed.
  setStatus('Finding HD thumbnail… (no server needed)');
  try {
    // If preview hasn't resolved a title yet (fast click), fetch it now
    // so the JPG filename still matches the video.
    if (!lastInfo?.title && !vtitle.textContent) {
      try {
        const p = await fetchOembedPreview(vid);
        if (p?.title) {
          vtitle.textContent = p.title;
          vmeta.textContent = p.uploader || '';
          lastInfo = { ...(lastInfo || {}), title: p.title, uploader: p.uploader };
        }
      } catch { /* filename falls back to video id */ }
    }
    const thumbUrl = await resolveBestThumbUrl(vid);
    // Show preview too, even if server is down
    thumb.src = thumbUrl;
    videoBox.style.display = 'flex';
    await chrome.downloads.download({
      url: thumbUrl,
      filename: `Thumbnail-${vid}.jpg`,
      saveAs: true
    });
    setStatus('Thumbnail JPG save started ✓');
  } catch (e) {
    setStatus('Thumb failed: ' + e.message);
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

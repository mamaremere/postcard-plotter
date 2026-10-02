/* Postcard Plotter — browser front-end.
 *
 * All geometry comes from text2gcode.py running in Pyodide; this file only
 * collects parameters, draws the card around the ink, and hands you files.
 * Nothing is uploaded and nothing is written to disk: previews are strings,
 * downloads are Blobs whose object URLs are revoked straight after saving.
 */
'use strict';

const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v0.28.0/full/';

const SAMPLE = `Dear friend,

Thank you for your faithful partnership in the Gospel with us. Please pray that the Lord will continue to open hearts through our work, drawing many to faith.

Yours,

The team`;

/* id -> how to read it out of the DOM */
const FIELDS = {
  font: 'str', box_w: 'num', box_h: 'num', box_x: 'num', box_y: 'num',
  card_w: 'num', card_h: 'num', height: 'num', max_width: 'numOrNull',
  align: 'str', valign: 'str', line_spacing: 'num', paragraph_gap: 'num',
  char_spacing: 'num', zero_at: 'str', draw_feed: 'num', travel_feed: 'num',
  power: 'num', pen_delay: 'num', pen_down_cmd: 'str', pen_up_cmd: 'str',
  go_home: 'bool', smooth: 'bool',
  addr_w: 'num', addr_h: 'num', addr_x: 'num', addr_y: 'num',
  addr_height: 'num', addr_lines: 'num', addr_valign: 'str'
};

/* the two free-text boxes: kept out of presets and share links */
const TEXTS = ['text', 'address'];
const MODES = ['mode', 'addr_mode'];

let pyodide = null, webapi = null, DEFAULTS = {}, FONTS = [];
let uploadedId = null, pending = null, lastPreview = null;

const $ = id => document.getElementById(id);

/* ─────────────────────────────── boot ─────────────────────────────── */

function progress(pct, msg) {
  $('boot-bar').style.width = pct + '%';
  if (msg) $('boot-msg').textContent = msg;
}

async function boot() {
  try {
    progress(8, 'Loading the Python runtime…');
    pyodide = await loadPyodide({ indexURL: PYODIDE_URL });

    progress(65, 'Loading fonts…');
    const buf = await (await fetch('bundle.zip', { cache: 'default' })).arrayBuffer();
    await pyodide.unpackArchive(buf, 'zip');

    progress(85, 'Warming up…');
    pyodide.runPython(`
import sys, os
d = os.getcwd()
if d not in sys.path:
    sys.path.insert(0, d)
`);
    webapi = pyodide.pyimport('webapi');
    DEFAULTS = JSON.parse(webapi.defaults());
    FONTS = JSON.parse(webapi.list_fonts());

    initForm();
    progress(100, 'Ready');
    setTimeout(() => $('boot').classList.add('done'), 250);
    setTimeout(() => $('boot').remove(), 900);
    update();
  } catch (err) {
    console.error(err);
    $('boot-msg').innerHTML =
      '<strong>Could not start.</strong><br>' + String(err).slice(0, 200);
    $('boot-bar').style.background = 'var(--danger)';
  }
}

/* ────────────────────────────── the form ──────────────────────────── */

function fillFontSelect() {
  const sel = $('font');
  sel.innerHTML = '';
  const groups = [...new Set(FONTS.map(f => f.group))];
  for (const g of groups) {
    const og = document.createElement('optgroup');
    og.label = g;
    for (const f of FONTS.filter(x => x.group === g)) {
      const o = document.createElement('option');
      o.value = f.id;
      o.textContent = f.note ? `${f.label} — ${f.note}` : f.label;
      og.appendChild(o);
    }
    sel.appendChild(og);
  }
}

function initForm() {
  fillFontSelect();
  applyParams(DEFAULTS);
  $('text').value = SAMPLE;

  const fromUrl = readHash();
  if (fromUrl) applyParams(fromUrl);

  for (const id of Object.keys(FIELDS)) {
    const el = $(id);
    if (!el) continue;
    el.addEventListener(el.tagName === 'SELECT' || el.type === 'checkbox'
      ? 'change' : 'input', update);
  }
  for (const id of TEXTS) $(id).addEventListener('input', update);
  $('show_furniture').addEventListener('change', update);
  for (const r of document.querySelectorAll('input[name=mode], input[name=addr_mode]')) {
    r.addEventListener('change', update);
  }

  $('dl-gcode').addEventListener('click', downloadGcode);
  $('dl-svg').addEventListener('click', downloadSvg);
  $('font-file').addEventListener('change', onFontUpload);
  $('font-forget').addEventListener('click', forgetFont);
  $('preset-save').addEventListener('click', savePreset);
  $('preset-load').addEventListener('click', loadPreset);
  $('preset-delete').addEventListener('click', deletePreset);
  $('copy-link').addEventListener('click', copyLink);
  refreshPresetList();
}

function applyParams(p) {
  for (const [id, kind] of Object.entries(FIELDS)) {
    const el = $(id);
    if (!el || !(id in p) || p[id] === null || p[id] === undefined) {
      if (el && kind === 'numOrNull' && (p[id] === null)) el.value = '';
      continue;
    }
    if (kind === 'bool') el.checked = !!p[id];
    else el.value = p[id];
  }
  for (const name of MODES) {
    if (!p[name]) continue;
    const r = document.querySelector(`input[name=${name}][value="${p[name]}"]`);
    if (r) r.checked = true;
  }
  for (const id of TEXTS) {
    if (typeof p[id] === 'string') $(id).value = p[id];
  }
}

function getParams() {
  const p = {};
  for (const [id, kind] of Object.entries(FIELDS)) {
    const el = $(id);
    if (!el) continue;
    if (kind === 'bool') { p[id] = el.checked; continue; }
    if (kind === 'str') { p[id] = el.value; continue; }
    if (el.value.trim() === '') { p[id] = kind === 'numOrNull' ? null : DEFAULTS[id]; continue; }
    const v = parseFloat(el.value);
    p[id] = Number.isFinite(v) ? v : DEFAULTS[id];
  }
  for (const name of MODES) {
    p[name] = document.querySelector(`input[name=${name}]:checked`).value;
  }
  for (const id of TEXTS) p[id] = $(id).value;
  return p;
}

function syncModeUI(p) {
  const fit = p.mode === 'fit';
  $('height').disabled = fit;
  $('max_width').disabled = fit;
  const afit = p.addr_mode === 'fit';
  $('addr_lines').disabled = !afit;
  $('addr_height').disabled = afit;
  const note = FONTS.find(f => f.id === $('font').value);
  $('font-note').textContent = note && note.note ? note.note : '';
}

/* ──────────────────────────── preview loop ────────────────────────── */

function update() {
  clearTimeout(pending);
  pending = setTimeout(run, 220);
}

function run() {
  if (!webapi) return;
  const p = getParams();
  syncModeUI(p);

  let res;
  try {
    res = JSON.parse(webapi.preview(JSON.stringify(p)));
  } catch (err) {
    console.error(err);
    showMessages([{ kind: 'error', text: 'Layout failed: ' + err }]);
    return;
  }

  if (res.empty || !res.ok) {
    lastPreview = null;
    drawCard(p, '', '');
    $('stats').innerHTML = '';
    $('fit-readout').textContent = '';
    $('addr-readout').textContent = '';
    showMessages([res.empty
      ? { kind: 'msg', text: 'Type a message or an address to see it on the card.' }
      : { kind: 'error', text: res.error }]);
    $('dl-gcode').disabled = true;
    return;
  }

  lastPreview = { params: p, res };
  $('dl-gcode').disabled = false;
  const msg = res.message, addr = res.address;
  drawCard(p, msg ? msg.ink_path_d : '', addr ? addr.ink_path_d : '');

  $('fit-readout').textContent = msg && p.mode === 'fit'
    ? `Auto size: ${msg.info.cap_height} mm capitals, ${msg.info.lines} lines`
    : '';
  $('addr-readout').textContent = addr && p.addr_mode === 'fit'
    ? `Auto size: ${addr.info.cap_height} mm capitals, ${addr.info.lines} lines`
    : '';

  const i = res.info, pills = [];
  if (msg) {
    pills.push(`message <b>${msg.info.width}</b> × <b>${msg.info.height}</b> mm`,
               `<b>${msg.info.cap_height}</b> mm capitals`,
               `<b>${msg.info.lines}</b> lines`);
  }
  if (addr) {
    pills.push(`address <b>${addr.info.cap_height}</b> mm capitals`,
               `<b>${addr.info.lines}</b> address lines`);
  }
  pills.push(`<b>${i.strokes}</b> pen strokes`,
             `<b>${(i.ink_mm / 1000).toFixed(1)}</b> m of ink`,
             `about <b>${i.minutes}</b> min`);
  $('stats').innerHTML = pills.map(s => `<span>${s}</span>`).join('');

  showMessages(res.warnings.map(w => ({ kind: 'msg', text: w })));

  $('zero-hint').textContent = p.zero_at === 'box'
    ? 'Before plotting: jog the pen to the bottom-left corner of the writing area (the dashed box) and zero X and Y there.'
    : 'Before plotting: jog the pen to the bottom-left corner of the card and zero X and Y there.';
}

function showMessages(list) {
  $('messages').innerHTML = list
    .map(m => `<div class="msg ${m.kind === 'error' ? 'error' : ''}">${escapeHtml(m.text)}</div>`)
    .join('');
}

const escapeHtml = s => s.replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* ───────────────────────── card illustration ──────────────────────── */

function drawCard(p, inkPathD, addrPathD) {
  const cw = p.card_w, ch = p.card_h, pad = 7;
  const bx = p.box_x, bw = p.box_w, bh = p.box_h;
  const byTop = ch - p.box_y - bh;                    // box top edge, SVG space
  const ax = p.addr_x, aw = p.addr_w, ah = p.addr_h;
  const ayTop = ch - p.addr_y - ah;
  const zx = p.zero_at === 'box' ? bx : 0;
  const zy = p.zero_at === 'box' ? ch - p.box_y : ch;

  let furniture = '';
  if ($('show_furniture').checked) {
    // The divider is real; the stamp box is a guess at where a stamp goes.
    furniture = `
      <g class="furniture">
        <line x1="${cw / 2}" y1="8" x2="${cw / 2}" y2="${ch - 8}"/>
        <rect x="${cw - 26}" y="7" width="19" height="23" rx="1.5"/>
      </g>`;
  }

  // While no address is typed, rule the address area with as many faint
  // lines as the fit reserves room for, so you can see what "room for
  // 6 lines" means on the card. The ink replaces them once you type.
  let guides = '';
  if (!addrPathD) {
    const n = Math.max(1, Math.round(p.addr_lines || 1));
    const pitch = ah / n;
    const rows = [];
    for (let k = 1; k <= n; k++) {
      const y = ayTop + k * pitch - pitch * 0.25;     // roughly a baseline
      rows.push(`<line x1="${ax}" y1="${y}" x2="${ax + aw}" y2="${y}"/>`);
    }
    guides = `<g class="guides">${rows.join('')}</g>`;
  }

  const ticks = [];
  for (let x = 0; x <= cw; x += 10) ticks.push(`<line x1="${x}" y1="${ch}" x2="${x}" y2="${ch + 2}"/>`);
  for (let y = 0; y <= ch; y += 10) ticks.push(`<line x1="-2" y1="${y}" x2="0" y2="${y}"/>`);

  $('preview').setAttribute('viewBox',
    `${-pad} ${-pad} ${cw + pad * 2} ${ch + pad * 2}`);
  $('preview').innerHTML = `
    <style>
      .card  { fill: var(--paper); stroke: #c9bda9; stroke-width: .4; }
      .furniture { stroke: #c9bda9; stroke-width: .3; fill: none; opacity: .8; }
      .box   { fill: none; stroke: var(--accent); stroke-width: .35;
               stroke-dasharray: 2 1.6; opacity: .75; }
      .box.addr { opacity: .45; }
      .guides { stroke: #c9bda9; stroke-width: .3; opacity: .8; }
      .ink   { fill: none; stroke: #1c1c1c; stroke-width: .32;
               stroke-linecap: round; stroke-linejoin: round; }
      .ticks { stroke: #b9ad99; stroke-width: .25; }
      .zero  { stroke: #c0392b; stroke-width: .5; }
      .zlabel{ fill: #c0392b; font: 2.6px ui-sans-serif, sans-serif; }
    </style>
    <rect class="card" x="0" y="0" width="${cw}" height="${ch}" rx="2"/>
    ${furniture}
    <g class="ticks">${ticks.join('')}</g>
    <rect class="box" x="${bx}" y="${byTop}" width="${bw}" height="${bh}"/>
    <rect class="box addr" x="${ax}" y="${ayTop}" width="${aw}" height="${ah}"/>
    ${guides}
    <path class="ink" d="${inkPathD}"/>
    <path class="ink" d="${addrPathD}"/>
    <g class="zero">
      <line x1="${zx - 3}" y1="${zy}" x2="${zx + 3}" y2="${zy}"/>
      <line x1="${zx}" y1="${zy - 3}" x2="${zx}" y2="${zy + 3}"/>
    </g>
    <text class="zlabel" x="${zx + 4}" y="${Math.min(zy + 3.4, ch - 1)}">0,0</text>
  `;
}

/* ───────────────────────────── downloads ──────────────────────────── */

function saveBlob(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);   // free it again
}

function stamp() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
}

function downloadGcode() {
  if (!lastPreview) return;
  let res;
  try {
    res = JSON.parse(webapi.generate(JSON.stringify(lastPreview.params)));
  } catch (err) {
    showMessages([{ kind: 'error', text: 'Could not generate G-code: ' + err }]);
    return;
  }
  if (!res.ok) { showMessages([{ kind: 'error', text: res.error }]); return; }
  saveBlob(`postcard-${stamp()}.gcode`, res.gcode, 'text/plain');
  toast(`Saved · starts at X${res.starts_at[0]} Y${res.starts_at[1]} mm`);
}

function downloadSvg() {
  const svg = $('preview');
  if (!svg.innerHTML.trim()) return;
  const clone = `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${svg.getAttribute('viewBox')}" ` +
    `width="${lastPreview ? lastPreview.params.card_w : 150}mm" ` +
    `height="${lastPreview ? lastPreview.params.card_h : 105}mm">` +
    svg.innerHTML.replace(/var\(--paper\)/g, '#ffffff')
                 .replace(/var\(--accent\)/g, '#8a6a4a') +
    `</svg>`;
  saveBlob(`postcard-${stamp()}.svg`, clone, 'image/svg+xml');
}

/* ──────────────────────────── font upload ─────────────────────────── */

async function onFontUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  if (file.size > 4 * 1024 * 1024) {
    showMessages([{ kind: 'error', text: 'That font file is unusually large (over 4 MB) — not loading it.' }]);
    e.target.value = '';
    return;
  }
  const text = await file.text();
  let res;
  try {
    res = JSON.parse(webapi.add_font(file.name, text));
  } catch (err) {
    res = { ok: false, error: String(err) };
  }
  e.target.value = '';

  if (!res.ok) { showMessages([{ kind: 'error', text: res.error }]); return; }

  if (uploadedId) webapi.forget_font(uploadedId);
  uploadedId = res.id;
  FONTS = JSON.parse(webapi.list_fonts());
  fillFontSelect();
  $('font').value = res.id;
  $('font-forget').hidden = false;
  update();
  if (res.warnings.length) {
    showMessages(res.warnings.map(w => ({ kind: 'msg', text: w })));
  } else {
    toast('Font loaded — it stays in this tab only');
  }
}

function forgetFont() {
  if (!uploadedId) return;
  webapi.forget_font(uploadedId);
  uploadedId = null;
  FONTS = JSON.parse(webapi.list_fonts());
  fillFontSelect();
  $('font').value = DEFAULTS.font;
  $('font-forget').hidden = true;
  update();
  toast('Uploaded font removed');
}

/* ───────────────────────── presets & sharing ──────────────────────── */

const PRESET_KEY = 'postcard-plotter.presets';
const readPresets = () => {
  try { return JSON.parse(localStorage.getItem(PRESET_KEY)) || {}; }
  catch { return {}; }
};

function refreshPresetList() {
  const sel = $('preset-list');
  const names = Object.keys(readPresets()).sort();
  sel.innerHTML = '<option value="">— saved settings —</option>' +
    names.map(n => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
}

function savePreset() {
  const name = $('preset-name').value.trim();
  if (!name) { toast('Give the settings a name first'); return; }
  const all = readPresets();
  const p = getParams();
  for (const id of TEXTS) delete p[id];     // settings only, never the words
  all[name] = p;
  localStorage.setItem(PRESET_KEY, JSON.stringify(all));
  $('preset-name').value = '';
  refreshPresetList();
  toast(`Saved “${name}”`);
}

function loadPreset() {
  const name = $('preset-list').value;
  if (!name) return;
  const p = readPresets()[name];
  if (!p) return;
  applyParams(p);
  update();
  toast(`Loaded “${name}”`);
}

function deletePreset() {
  const name = $('preset-list').value;
  if (!name) return;
  const all = readPresets();
  delete all[name];
  localStorage.setItem(PRESET_KEY, JSON.stringify(all));
  refreshPresetList();
  toast(`Deleted “${name}”`);
}

function copyLink() {
  const p = getParams();
  for (const id of TEXTS) delete p[id];     // the message and address stay private
  const url = location.origin + location.pathname +
    '#p=' + encodeURIComponent(JSON.stringify(p));
  navigator.clipboard.writeText(url)
    .then(() => toast('Link copied — it carries the settings, not your text'))
    .catch(() => toast('Could not copy automatically'));
}

function readHash() {
  const m = location.hash.match(/[#&]p=([^&]+)/);
  if (!m) return null;
  try { return JSON.parse(decodeURIComponent(m[1])); }
  catch { return null; }
}

/* ─────────────────────────────── toast ────────────────────────────── */

let toastTimer = null;
function toast(msg) {
  let el = $('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

boot();

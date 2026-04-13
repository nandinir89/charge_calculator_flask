/* ═══════════════════════════════════════════════════════════════
   Furnace Charge Calculator — app.js
   Features: Calculator, Trim Correction, Ladle Additions, Heat Log
═══════════════════════════════════════════════════════════════ */

/* ── State ───────────────────────────────────────────────────── */
let grades        = [];
let materials     = [];
let selectedGrade = null;
let chargeRows    = [];
let alloyRows     = [];
let lastCalcResult = null;
let allHeats      = [];
let allGrades     = [];

// Trim correction state
let trimGrade        = null;
let committedRows    = [];

// Argon purging
let argonPurging = false;

// Heat info taps (from heat info card buttons)
let heatTaps = 1;

const ELEMENTS    = ['C','Si','Mn','S','P','Cr','Ni','Mo','Cu'];
const ALLOY_CODES = ['GRAF','FESI','HCMN','LCMN','HCCR','LCCR','NI','FEMO','CU'];

/* ── Init ────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  await loadGrades();
  await loadMaterials();
  initAdditionsTable();
  addChargeRow();
  addChargeRow();
  buildSpectroInputs();
  updateTotals();
});

async function loadGrades() {
  const res = await fetch('/api/grades');
  grades = await res.json();
  allGrades = grades;
  // Build both searchable dropdowns
  buildGradeDropdown('gsw-main',  'grade-select',      onGradeChange);
  buildGradeDropdown('gsw-trim',  'trim-grade-select', onTrimGradeChange);
  renderGradeTable(grades);
  gmRenderTable(grades);
}

/* ── Searchable grade dropdown ─────────────────────────────── */
function buildGradeDropdown(wrapId, hiddenId, onSelect) {
  const wrap = document.getElementById(wrapId);
  if (!wrap) return;
  const dd = wrap.querySelector('.grade-dropdown');
  renderGradeDropdownItems(dd, grades, hiddenId, onSelect);
}

function renderGradeDropdownItems(dd, items, hiddenId, onSelect) {
  if (!items.length) {
    dd.innerHTML = `<div class="gd-empty">No grades found</div>`;
    return;
  }
  dd.innerHTML = items.map(g => {
    const chem = [g.C,g.Cr,g.Ni,g.Mo].filter(v=>v>0)
      .map((v,i)=>['C','Cr','Ni','Mo'][i]+v.toFixed(2)).join(' ');
    return `<div class="gd-item" data-code="${g.code}" data-desc="${g.description}"
      onmousedown="selectGradeItem(event,'${hiddenId}','${g.code}','${g.description.replace(/'/g,"\'")}')">
      <span class="gd-code">${g.code}</span>
      <span class="gd-desc">${g.description}</span>
      <span class="gd-chem">${chem}</span>
    </div>`;
  }).join('');
}

function filterGradeDropdown(wrapId, hiddenId) {
  const wrap = document.getElementById(wrapId);
  const input = wrap.querySelector('input[type="text"]');
  const dd    = wrap.querySelector('.grade-dropdown');
  const q     = (input.value || '').toLowerCase();
  const onSelect = hiddenId === 'grade-select' ? onGradeChange : onTrimGradeChange;
  const filtered = q
    ? grades.filter(g =>
        g.code.toLowerCase().includes(q) ||
        g.description.toLowerCase().includes(q))
    : grades;
  renderGradeDropdownItems(dd, filtered, hiddenId, onSelect);
  dd.classList.add('open');
}

function openGradeDropdown(wrapId) {
  const wrap = document.getElementById(wrapId);
  const dd   = wrap.querySelector('.grade-dropdown');
  dd.classList.add('open');
}

function closeGradeDropdownDelayed(wrapId) {
  setTimeout(() => {
    const wrap = document.getElementById(wrapId);
    if (wrap) wrap.querySelector('.grade-dropdown').classList.remove('open');
  }, 200);
}

function selectGradeItem(e, hiddenId, code, desc) {
  e.preventDefault();
  const hidden = document.getElementById(hiddenId);
  hidden.value = code;
  // Update the text input display
  const wrapId = hiddenId === 'grade-select' ? 'gsw-main' : 'gsw-trim';
  const wrap   = document.getElementById(wrapId);
  const input  = wrap.querySelector('input[type="text"]');
  input.value  = `${code} — ${desc}`;
  wrap.querySelector('.grade-dropdown').classList.remove('open');
  // Trigger selection
  if (hiddenId === 'grade-select') onGradeChange();
  else onTrimGradeChange();
}

async function loadMaterials() {
  const res  = await fetch('/api/materials');
  materials  = await res.json();
  allMaterials = materials;
  mmRenderTable(materials);
}

/* ── Navigation ──────────────────────────────────────────────── */
function showSection(id, btn) {
  document.querySelectorAll('.section').forEach(s => s.style.display = 'none');
  document.getElementById(id).style.display = '';
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  if (id === 'heat-log')         loadHeatLog();
  if (id === 'material-manager') { mmRenderTable(allMaterials); }
  if (id === 'grade-manager')    { gmRenderTable(allGrades); }
}

/* ═══════════════════════════════════════════════════════════════
   CALCULATOR
═══════════════════════════════════════════════════════════════ */

function onGradeChange() {
  const code = (document.getElementById('grade-select').value || '').trim();
  selectedGrade = grades.find(g => g.code === code) || null;
  const aimBlock = document.getElementById('grade-aim');
  if (!selectedGrade) {
    aimBlock.style.display = 'none';
    document.getElementById('ladle-card').style.display = 'none';
    return;
  }
  aimBlock.style.display = '';
  renderChemCells('aim-cells', ELEMENTS.map(el => ({
    el, value: selectedGrade[el] || 0, status: ''
  })));
  renderLaddleAdditions();
  updateTotals();
}

function onTapWeightChange() { updateTotals(); }

/* ── Charge rows ─────────────────────────────────────────────── */
function buildMatOptions() {
  const scraps = materials.filter(m => m.category === 'scrap' || m.category === 'grade_return');
  const alloys = materials.filter(m => m.category === 'alloy');
  let html = '<option value="">— select —</option>';
  html += '<optgroup label="Scraps / Returns">';
  scraps.forEach(m => { html += `<option value="${m.code}">${m.code} — ${m.description}</option>`; });
  html += '</optgroup><optgroup label="Alloy Additions">';
  alloys.forEach(m => { html += `<option value="${m.code}">${m.code} — ${m.description}</option>`; });
  html += '</optgroup>';
  return html;
}

function addChargeRow() {
  const id = 'r' + Date.now() + Math.random().toString(36).slice(2,5);
  chargeRows.push(id);
  const div = document.createElement('div');
  div.className = 'charge-row';
  div.id = 'crow-' + id;
  // hidden input stores code; text input is the search box
  div.innerHTML = `
    <div class="grade-search-wrap" id="msw-${id}" style="position:relative">
      <input type="text" id="msi-${id}" placeholder="🔍 Search material…" autocomplete="off"
             oninput="filterMatDropdown('${id}')"
             onfocus="openMatDropdown('${id}')"
             onblur="closeMatDropdownDelayed('${id}')">
      <div class="grade-dropdown" id="mdd-${id}"></div>
    </div>
    <input type="hidden" id="mat-${id}">
    <input type="number" id="wt-${id}" value="0" min="0" step="10" oninput="updateTotals()" placeholder="kg">
    <button class="remove-btn" onclick="removeChargeRow('${id}')">×</button>`;
  document.getElementById('charge-rows').appendChild(div);
  buildMatDropdown(id);
}

/* ── Material searchable dropdown helpers ─────────────────── */
function buildMatDropdown(rowId) {
  const dd = document.getElementById('mdd-' + rowId);
  if (!dd) return;
  renderMatDropdownItems(dd, materials, rowId);
}

function renderMatDropdownItems(dd, items, rowId) {
  const scraps = items.filter(m => m.category === 'scrap' || m.category === 'grade_return');
  const alloys = items.filter(m => m.category === 'alloy');
  let html = '';
  if (scraps.length) {
    html += `<div class="gd-group-label">Scraps / Returns</div>`;
    html += scraps.map(m => matItem(m, rowId)).join('');
  }
  if (alloys.length) {
    html += `<div class="gd-group-label">Alloy Additions</div>`;
    html += alloys.map(m => matItem(m, rowId)).join('');
  }
  if (!html) html = `<div class="gd-empty">No materials found</div>`;
  dd.innerHTML = html;
}

function matItem(m, rowId) {
  const chem = ['C','Cr','Ni','Mo'].filter(e=>(m[e]||0)>0)
    .map(e=>e+(m[e]).toFixed(1)).join(' ');
  const safeDesc = (m.description||'').replace(/'/g,"\'");
  return `<div class="gd-item"
    onmousedown="selectMatItem(event,'${rowId}','${m.code}','${safeDesc}')">
    <span class="gd-code">${m.code}</span>
    <span class="gd-desc">${m.description}</span>
    <span class="gd-chem">${chem}</span>
  </div>`;
}

function filterMatDropdown(rowId) {
  const input = document.getElementById('msi-' + rowId);
  const dd    = document.getElementById('mdd-' + rowId);
  const q     = (input.value || '').toLowerCase();
  const filtered = q
    ? materials.filter(m =>
        m.code.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q))
    : materials;
  renderMatDropdownItems(dd, filtered, rowId);
  dd.classList.add('open');
}

function openMatDropdown(rowId) {
  document.getElementById('mdd-' + rowId)?.classList.add('open');
}

function closeMatDropdownDelayed(rowId) {
  setTimeout(() => {
    document.getElementById('mdd-' + rowId)?.classList.remove('open');
  }, 200);
}

function selectMatItem(e, rowId, code, desc) {
  e.preventDefault();
  document.getElementById('mat-' + rowId).value = code;
  document.getElementById('msi-' + rowId).value = `${code} — ${desc}`;
  document.getElementById('mdd-' + rowId)?.classList.remove('open');
  updateTotals();
}

function removeChargeRow(id) {
  chargeRows = chargeRows.filter(r => r !== id);
  document.getElementById('crow-' + id)?.remove();
  updateTotals();
}

function getChargeItems() {
  return chargeRows.map(id => ({
    code:   document.getElementById('mat-' + id)?.value || '',
    weight: parseFloat(document.getElementById('wt-' + id)?.value) || 0,
  })).filter(i => i.code && i.weight > 0);
}

function updateTotals() {
  const tapWt = parseFloat(document.getElementById('tap-weight').value) || 0;
  document.getElementById('target-wt-disp').textContent = tapWt.toFixed(0) + ' kg';

  let totalCharge = 0;
  const chemKg = Object.fromEntries(ELEMENTS.map(e => [e, 0]));

  chargeRows.forEach(id => {
    const code = document.getElementById('mat-' + id)?.value || '';
    const wt   = parseFloat(document.getElementById('wt-' + id)?.value) || 0;
    totalCharge += wt;
    const mat = materials.find(m => m.code === code);
    if (mat && wt > 0) {
      ELEMENTS.forEach(el => { chemKg[el] += (mat[el] || 0) / 100 * wt; });
    }
  });

  document.getElementById('total-charge-disp').textContent = totalCharge.toFixed(0) + ' kg';
  const diff   = tapWt - totalCharge;
  const diffEl = document.getElementById('diff-disp');
  diffEl.textContent = (diff >= 0 ? '+' : '') + diff.toFixed(0) + ' kg';
  diffEl.className = Math.abs(diff) < 5 ? 'diff-ok' : diff > 0 ? 'diff-warn' : 'diff-bad';

  const baseWt = totalCharge || 1;

  // Charge chemistry cells
  const chargeCellData = ELEMENTS.map(el => {
    const pct = chemKg[el] / baseWt * 100;
    const aim = selectedGrade ? (selectedGrade[el] || 0) : null;
    let status = '';
    if (aim !== null && aim > 0) {
      const tol = aim * 0.15 + 0.02;
      status = Math.abs(pct - aim) <= tol ? 'ok' : pct < aim ? 'low' : 'high';
    }
    return { el, value: pct, status };
  });
  renderChemCells('charge-cells', chargeCellData);

  // Bars vs aim
  if (selectedGrade) {
    const activeEls = ELEMENTS.filter(el => (selectedGrade[el] || 0) > 0);
    const maxV = Math.max(...activeEls.map(el =>
      Math.max(selectedGrade[el] || 0, chemKg[el] / baseWt * 100)), 0.01);
    document.getElementById('chem-bars').innerHTML = activeEls.map(el => {
      const aim    = selectedGrade[el] || 0;
      const actual = chemKg[el] / baseWt * 100;
      const tol    = aim * 0.15 + 0.02;
      const cls    = Math.abs(actual - aim) <= tol ? 'ok' : actual < aim ? 'low' : 'high';
      return barRow(el, aim, actual, maxV, cls);
    }).join('');
  } else {
    document.getElementById('chem-bars').innerHTML = '';
  }

  updateAdditionTotals();
}

/* ── Additions table ─────────────────────────────────────────── */
function initAdditionsTable() {
  alloyRows = materials.filter(m => m.category === 'alloy').map(m => ({ ...m, planned: 0, trim: 0 }));
  renderAdditionsBody();
}

function renderAdditionsBody() {
  const tbody = document.getElementById('additions-body');
  tbody.innerHTML = alloyRows.map((a, i) => `<tr>
    <td>${a.description}</td>
    <td style="color:var(--text2);font-size:12px">${a.code}</td>
    <td class="num-col">
      <input type="number" value="${a.planned.toFixed(2)}" min="0" step="0.1"
        onchange="alloyRows[${i}].planned=parseFloat(this.value)||0;updateAdditionTotals();runFullCalc()">
    </td>
    <td class="num-col">
      <input type="number" value="${a.trim.toFixed(2)}" min="0" step="0.1"
        onchange="alloyRows[${i}].trim=parseFloat(this.value)||0;updateAdditionTotals();runFullCalc()">
    </td>
    <td class="num-col" id="add-total-${i}">${(a.planned + a.trim).toFixed(2)}</td>
    <td class="num-col" id="add-cost-${i}">$${((a.cost||0)*(a.planned+a.trim)).toFixed(2)}</td>
  </tr>`).join('');
  updateAdditionTotals();
}

function updateAdditionTotals() {
  let totalKg = 0, totalCost = 0;
  alloyRows.forEach((a, i) => {
    const tot = a.planned + a.trim;
    totalKg   += tot;
    totalCost += (a.cost || 0) * tot;
    const tk = document.getElementById('add-total-' + i);
    const tc = document.getElementById('add-cost-'  + i);
    if (tk) tk.textContent = tot.toFixed(2);
    if (tc) tc.textContent = '$' + ((a.cost || 0) * tot).toFixed(2);
  });
  document.getElementById('total-add-kg').textContent   = totalKg.toFixed(2);
  document.getElementById('total-add-cost').textContent = '$' + totalCost.toFixed(2);
  // Grand total: base charge + additions
  const tapWt2     = parseFloat(document.getElementById('tap-weight').value) || 0;
  let baseCharge   = 0;
  chargeRows.forEach(id => { baseCharge += parseFloat(document.getElementById('wt-'+id)?.value) || 0; });
  const combined   = baseCharge + totalKg;
  const gtEl       = document.getElementById('total-combined-kg');
  if (gtEl) gtEl.textContent = combined.toFixed(2) + ' kg';
}

/* ── Ladle / deoxidation additions ───────────────────────────── */
async function renderLaddleAdditions() {
  if (!selectedGrade) return;
  const tapWt = parseFloat(document.getElementById('tap-weight').value) || 1000;
  const res   = await fetch(`/api/ladle_additions/${selectedGrade.code}?tap_weight=${tapWt}`);
  const data  = await res.json();

  const card = document.getElementById('ladle-card');
  const tbody = document.getElementById('ladle-body');

  if (!data.length) { card.style.display = 'none'; return; }

  card.style.display = '';
  tbody.innerHTML = data.map(a => `<tr>
    <td>${a.name}</td>
    <td style="font-size:12px;color:var(--text2)">${a.fa_code}</td>
    <td><span class="loc-badge ${a.location}">${a.location}</span></td>
    <td class="num-col">${a.rate_kg_per_tonne.toFixed(3)}</td>
    <td class="num-col"><strong>${a.kg.toFixed(3)}</strong></td>
  </tr>`).join('');
}

/* ── Auto-calculate additions ────────────────────────────────── */
async function calcAdditions() {
  if (!selectedGrade) { showToast('Select a metal grade first.', 'error'); return; }

  const res = await fetch('/api/calculate', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      grade_code:   selectedGrade.code,
      tap_weight:   parseFloat(document.getElementById('tap-weight').value) || 1000,
      charge_items: getChargeItems(),
      addition_items: [],
    }),
  });
  const data = await res.json();

  // Apply auto suggestions
  data.auto_additions.forEach(s => {
    const idx = alloyRows.findIndex(a => a.code === s.addition_code);
    if (idx >= 0) { alloyRows[idx].planned = s.addition_kg; alloyRows[idx].trim = 0; }
  });
  renderAdditionsBody();
  await runFullCalc();
}

async function runFullCalc() {
  if (!selectedGrade) return;
  const res = await fetch('/api/calculate', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      grade_code:   selectedGrade.code,
      tap_weight:   parseFloat(document.getElementById('tap-weight').value) || 1000,
      charge_items: getChargeItems(),
      addition_items: alloyRows.filter(a => a.planned + a.trim > 0).map(a => ({
        code: a.code, planned: a.planned, trim: a.trim,
      })),
    }),
  });
  const data = await res.json();
  lastCalcResult = data;
  renderResults(data);
  renderLaddleAdditions();
}

/* ── Results ─────────────────────────────────────────────────── */
function renderResults(data) {
  document.getElementById('result-card').style.display = '';
  const cmp = data.comparison;

  const cellData = ELEMENTS.map(el => {
    const c = cmp[el] || { aim:0, actual:0, status:'ok' };
    return { el, value: c.actual, status: c.status, aim: c.aim,
             icon: c.status === 'ok' ? '✓' : c.status === 'low' ? '↓' : '↑' };
  });
  renderChemCells('result-cells', cellData, true);

  const allOk = Object.values(cmp).every(c => c.status === 'ok' || c.aim === 0);
  setBadge('result-status-badge', allOk ? '✓ Within aim' : '⚠ Outside aim', allOk ? 'ok' : 'err');

  const activeEls = ELEMENTS.filter(el => (cmp[el]?.aim || 0) > 0);
  const maxV = Math.max(...activeEls.map(el => Math.max(cmp[el].aim, cmp[el].actual)), 0.01);
  document.getElementById('result-bars').innerHTML = activeEls.map(el => {
    const c = cmp[el];
    return barRow(el, c.aim, c.actual, maxV, c.status);
  }).join('');
}

/* ═══════════════════════════════════════════════════════════════
   TRIM CORRECTION
═══════════════════════════════════════════════════════════════ */

function buildSpectroInputs() {
  document.getElementById('spectro-inputs').innerHTML = ELEMENTS.map(el => `
    <div class="spectro-field" id="sf-${el}">
      <label>${el} %</label>
      <input type="number" id="spectro-${el}" value="0" min="0" step="0.001" placeholder="0.000"
             oninput="highlightSpectroField('${el}')">
    </div>`).join('');
}

function highlightSpectroField(el) {
  if (!trimGrade) return;
  const aim   = trimGrade[el] || 0;
  const val   = parseFloat(document.getElementById('spectro-' + el).value) || 0;
  const field = document.getElementById('sf-' + el);
  field.className = 'spectro-field';
  if (aim > 0) {
    const tol = aim * 0.15 + 0.02;
    field.classList.add(Math.abs(val - aim) <= tol ? 'on' : val < aim ? 'under' : 'over');
  }
}

function onTrimGradeChange() {
  const code = (document.getElementById('trim-grade-select').value || '').trim();
  trimGrade = grades.find(g => g.code === code) || null;
  const block = document.getElementById('trim-aim-block');
  if (!trimGrade) { block.style.display = 'none'; return; }
  block.style.display = '';
  renderChemCells('trim-aim-cells', ELEMENTS.map(el => ({ el, value: trimGrade[el] || 0, status: '' })));
  ELEMENTS.forEach(el => highlightSpectroField(el));
}

/* ── Committed trim rows ─────────────────────────────────────── */
function buildAlloyOptions() {
  let html = '<option value="">— select —</option>';
  materials.filter(m => m.category === 'alloy').forEach(m => {
    html += `<option value="${m.code}">${m.code} — ${m.description}</option>`;
  });
  return html;
}

function addCommittedRow() {
  const id = 'ct' + Date.now();
  committedRows.push(id);
  const div = document.createElement('div');
  div.className = 'committed-row';
  div.id = 'ctr-' + id;
  div.innerHTML = `
    <div class="grade-search-wrap" id="ctsw-${id}" style="position:relative">
      <input type="text" id="ctsi-${id}" placeholder="🔍 Search alloy…" autocomplete="off"
             oninput="filterCtDropdown('${id}')"
             onfocus="openCtDropdown('${id}')"
             onblur="closeCtDropdownDelayed('${id}')">
      <div class="grade-dropdown" id="ctdd-${id}"></div>
    </div>
    <input type="hidden" id="ctmat-${id}">
    <input type="number" id="ctwt-${id}" value="0" min="0" step="0.1" placeholder="kg">
    <button class="remove-btn" onclick="removeCommittedRow('${id}')">×</button>`;
  document.getElementById('committed-trim-rows').appendChild(div);
  buildCtDropdown(id);
}

function buildCtDropdown(id) {
  const dd = document.getElementById('ctdd-' + id);
  if (!dd) return;
  const alloys = materials.filter(m => m.category === 'alloy');
  dd.innerHTML = alloys.map(m => {
    const safeDesc = (m.description||'').replace(/'/g,"\'");
    return `<div class="gd-item"
      onmousedown="selectCtItem(event,'${id}','${m.code}','${safeDesc}')">
      <span class="gd-code">${m.code}</span>
      <span class="gd-desc">${m.description}</span>
    </div>`;
  }).join('');
}

function filterCtDropdown(id) {
  const input = document.getElementById('ctsi-' + id);
  const dd    = document.getElementById('ctdd-' + id);
  const q     = (input.value || '').toLowerCase();
  const alloys = q
    ? materials.filter(m => m.category==='alloy' && (
        m.code.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q)))
    : materials.filter(m => m.category === 'alloy');
  dd.innerHTML = alloys.map(m => {
    const safeDesc = (m.description||'').replace(/'/g,"\'");
    return `<div class="gd-item"
      onmousedown="selectCtItem(event,'${id}','${m.code}','${safeDesc}')">
      <span class="gd-code">${m.code}</span>
      <span class="gd-desc">${m.description}</span>
    </div>`;
  }).join('') || `<div class="gd-empty">No alloys found</div>`;
  dd.classList.add('open');
}

function openCtDropdown(id) {
  document.getElementById('ctdd-' + id)?.classList.add('open');
}
function closeCtDropdownDelayed(id) {
  setTimeout(() => { document.getElementById('ctdd-' + id)?.classList.remove('open'); }, 200);
}
function selectCtItem(e, id, code, desc) {
  e.preventDefault();
  document.getElementById('ctmat-' + id).value = code;
  document.getElementById('ctsi-' + id).value  = `${code} — ${desc}`;
  document.getElementById('ctdd-' + id)?.classList.remove('open');
}

function removeCommittedRow(id) {
  committedRows = committedRows.filter(r => r !== id);
  document.getElementById('ctr-' + id)?.remove();
}

function getCommittedItems() {
  return committedRows.map(id => ({
    code: document.getElementById('ctmat-' + id)?.value || '',
    kg:   parseFloat(document.getElementById('ctwt-' + id)?.value) || 0,
  })).filter(i => i.code && i.kg > 0);
}

/* ── Run trim calculation ────────────────────────────────────── */
async function runTrimCalc() {
  if (!trimGrade) { showToast('Select a grade first.', 'error'); return; }

  const furnaceKg = parseFloat(document.getElementById('trim-furnace-kg').value) || 0;
  if (furnaceKg <= 0) { showToast('Enter furnace weight > 0.', 'error'); return; }

  const spectro = {};
  ELEMENTS.forEach(el => {
    spectro[el] = parseFloat(document.getElementById('spectro-' + el).value) || 0;
  });

  const res = await fetch('/api/trim_correction', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      grade_code:    trimGrade.code.trim(),
      furnace_kg:    furnaceKg,
      spectro:       spectro,
      existing_trim: getCommittedItems(),
    }),
  });
  const data = await res.json();
  if (data.error) { showToast('Trim error: ' + data.error, 'error'); return; }

  window._lastTrimData = data;   // store for printTrimReport
  renderTrimResults(data);
  renderTrimProjected(data);
  renderTrimLadle(data);
  checkShowDilution(data);
}

function renderTrimResults(data) {
  const card = document.getElementById('trim-result-card');
  card.style.display = '';

  const tbody  = document.getElementById('trim-body');
  const noMsg  = document.getElementById('no-trim-msg');

  if (!data.trim_needed.length) {
    tbody.innerHTML = '';
    noMsg.style.display = '';
    setBadge('trim-total-badge', '✓ On aim', 'ok');
    document.getElementById('trim-total-kg').textContent   = '0.00 kg';
    document.getElementById('trim-total-cost').textContent = '$0.00';
  } else {
    noMsg.style.display = 'none';
    tbody.innerHTML = data.trim_needed.map(t => `<tr>
      <td><strong>${t.element}</strong></td>
      <td class="num-col">${t.aim.toFixed(3)}</td>
      <td class="num-col ${t.deficit > 0 ? 'status-warn-text' : ''}">${t.actual.toFixed(3)}</td>
      <td class="num-col status-warn-text">${t.deficit.toFixed(3)}</td>
      <td>${t.addition_desc} <small style="color:var(--text3)">(${t.addition_code})</small></td>
      <td class="num-col"><strong>${t.addition_kg.toFixed(2)}</strong></td>
      <td class="num-col">$${t.cost.toFixed(2)}</td>
    </tr>`).join('');
    setBadge('trim-total-badge', `${data.trim_needed.length} element${data.trim_needed.length>1?'s':''} need trim`, 'err');
    document.getElementById('trim-total-kg').textContent   = data.total_trim_kg.toFixed(2) + ' kg';
    document.getElementById('trim-total-cost').textContent = '$' + data.total_trim_cost.toFixed(2);
  }
}

function renderTrimProjected(data) {
  const card = document.getElementById('trim-proj-card');
  card.style.display = '';

  const cmp      = data.comparison;
  const cellData = ELEMENTS.map(el => {
    const c = cmp[el] || { aim:0, actual:0, status:'ok' };
    return { el, value: c.actual, status: c.status, aim: c.aim,
             icon: c.status === 'ok' ? '✓' : c.status === 'low' ? '↓' : '↑' };
  });
  renderChemCells('trim-proj-cells', cellData, true);

  const allOk = Object.values(cmp).every(c => c.status === 'ok' || c.aim === 0);
  setBadge('trim-proj-badge', allOk ? '✓ Within aim' : '⚠ Outside aim', allOk ? 'ok' : 'err');

  const activeEls = ELEMENTS.filter(el => (cmp[el]?.aim || 0) > 0);
  const maxV = Math.max(...activeEls.map(el => Math.max(cmp[el].aim, cmp[el].actual)), 0.01);
  document.getElementById('trim-proj-bars').innerHTML = activeEls.map(el => {
    const c = cmp[el];
    return barRow(el, c.aim, c.actual, maxV, c.status);
  }).join('');
}

async function renderTrimLadle(data) {
  if (!trimGrade) return;
  const furnaceKg = parseFloat(document.getElementById('trim-furnace-kg').value) || 1000;
  const res       = await fetch(`/api/ladle_additions/${trimGrade.code}?tap_weight=${furnaceKg}`);
  const ladle     = await res.json();

  const block = document.getElementById('trim-ladle-block');
  const tbody = document.getElementById('trim-ladle-body');

  if (!ladle.length) { block.style.display = 'none'; }
  else {
    block.style.display = '';
    tbody.innerHTML = ladle.map(a => `<tr>
      <td>${a.name}</td>
      <td style="font-size:12px;color:var(--text2)">${a.fa_code}</td>
      <td><span class="loc-badge ${a.location}">${a.location}</span></td>
      <td class="num-col">${a.rate_kg_per_tonne.toFixed(3)}</td>
      <td class="num-col"><strong>${a.kg.toFixed(3)}</strong></td>
    </tr>`).join('');
  }

  // Show the trim print card after ladle renders
  const trimPrintCard = document.getElementById('trim-print-card');
  if (trimPrintCard) trimPrintCard.style.display = '';

  // Store ladle for print report
  window._lastTrimLadle = ladle;
}

/* ── Print trim report ──────────────────────────────────────────── */
async function printTrimReport() {
  if (!trimGrade) { showToast('Select a grade first.', 'error'); return; }
  if (!window._lastTrimData) { showToast('Run trim calculation first.', 'error'); return; }

  const data      = window._lastTrimData;
  const furnaceKg = parseFloat(document.getElementById('trim-furnace-kg').value) || 0;
  const pourTemp  = parseFloat(document.getElementById('tap-temp').value) || 0;

  const spectro = {};
  ELEMENTS.forEach(el => {
    spectro[el] = parseFloat(document.getElementById('spectro-' + el).value) || 0;
  });

  const payload = {
    grade_code:     trimGrade.code,
    furnace_kg:     furnaceKg,
    spectro:        spectro,
    trim_needed:    data.trim_needed || [],
    projected_pct:  data.projected_pct || {},
    comparison:     data.comparison || {},
    ladle_additions: window._lastTrimLadle || [],
    heat_info: {
      heat_no:    document.getElementById('heat-no')?.value || '',
      furnace_no: document.getElementById('furnace-no')?.value || '',
      operator:   document.getElementById('operator')?.value || '',
      pour_temp:  pourTemp,
      ladle:      document.getElementById('ladle')?.value || '',
      melt_date:  new Date().toISOString().split('T')[0],
    },
  };

  try {
    const res  = await fetch('/api/prepare_trim_report', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if (d.token) {
      window.open('/trim_report?token=' + d.token, '_blank');
    } else {
      showToast('Failed to prepare trim report.', 'error');
    }
  } catch(e) {
    showToast('Error: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════════
   SAVE HEAT
═══════════════════════════════════════════════════════════════ */
async function saveHeat() {
  if (!selectedGrade) { showToast('Select a grade first.', 'error'); return; }
  const heatNo = document.getElementById('heat-no').value.trim();
  if (!heatNo) { showToast('Enter a heat number.', 'error'); return; }

  const cmp     = lastCalcResult?.comparison || {};
  const payload = {
    melt_date:  new Date().toISOString().split('T')[0],
    grade_name: selectedGrade.description,
    grade_code: selectedGrade.code,
    heat_no:    heatNo,
    furnace_no: document.getElementById('furnace-no').value,
    operator:   document.getElementById('operator').value,
    ladle:      document.getElementById('ladle').value,
    tap_wt:     parseFloat(document.getElementById('tap-weight').value) || 0,
    tap_temp:   parseFloat(document.getElementById('tap-temp').value) || 0,
    melt_wt:    lastCalcResult?.total_charge_kg || 0,
  };

  ELEMENTS.forEach(el => { payload[el] = cmp[el]?.actual || 0; });
  alloyRows.filter(a => ALLOY_CODES.includes(a.code)).forEach(a => {
    payload[a.code] = a.planned + a.trim;
  });

  const ci = getChargeItems();
  ['heel','scrap_1','scrap_2','scrap_3','scrap_4'].forEach((key, idx) => {
    payload[key + '_mat'] = ci[idx]?.code   || '';
    payload[key + '_wt']  = ci[idx]?.weight || 0;
  });

  const res  = await fetch('/api/heats', {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload),
  });
  const resp = await res.json();
  showToast(resp.status === 'saved' ? 'Heat saved to Excel!' : 'Error: ' + resp.error,
            resp.status === 'saved' ? 'success' : 'error');
}

/* ═══════════════════════════════════════════════════════════════
   HEAT LOG
═══════════════════════════════════════════════════════════════ */
async function loadHeatLog() {
  const res  = await fetch('/api/heats');
  allHeats   = await res.json();
  renderHeatTable(allHeats);
  updateFurnaceMonitor(allHeats);
}

function updateFurnaceMonitor(heats) {
  // Group by furnace, sum tap_wt, show alerts
  const furnaceTotals = {};
  heats.forEach(h => {
    const fn = (h.furnace_no || '').trim();
    if (!fn) return;
    furnaceTotals[fn] = (furnaceTotals[fn] || 0) + (h.tap_wt || 0);
  });
  const mon = document.getElementById('furnace-monitor');
  if (!mon) return;

  const alerts = [];
  Object.entries(furnaceTotals).forEach(([fn, kg]) => {
    const t = kg / 1000;
    if (t >= 200) {
      alerts.push('<span style="color:#b91c1c;font-weight:700">🚨 ' + fn + ': ' + t.toFixed(1) + 'T — MUST RELINE NOW!</span>');
    } else if (t >= 180) {
      alerts.push('<span style="color:#d97706;font-weight:700">⚠ ' + fn + ': ' + t.toFixed(1) + 'T — Reline approaching (200T)</span>');
    }
  });

  if (alerts.length) {
    mon.innerHTML = alerts.join('  &nbsp;|&nbsp;  ');
    mon.style.display = '';
    mon.style.background = 'var(--warn-bg)';
    mon.style.color = 'var(--warn)';
    mon.style.padding = '5px 12px';
    mon.style.borderRadius = 'var(--radius)';
    mon.style.fontSize = '12px';
  } else {
    mon.style.display = 'none';
  }
}

function renderHeatTable(heats) {
  const tbody = document.getElementById('heats-body');
  if (!heats.length) {
    tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;color:var(--text2);padding:24px">No heats saved yet.</td></tr>';
    return;
  }
  tbody.innerHTML = heats.map(function(h) {
    return '<tr>'
      + '<td><a href="#" class="heat-no-link" style="color:var(--accent);text-decoration:none;font-weight:600" '
      + 'onclick="loadHeatFromLog(' + JSON.stringify(h.heat_no) + ');return false;">'
      + (h.heat_no||'') + '</a></td>'
      + '<td>' + (h.melt_date||'—') + '</td>'
      + '<td>' + (h.grade_code||'') + ' — ' + (h.grade_name||'') + '</td>'
      + '<td>' + (h.furnace_no||'—') + '</td>'
      + '<td>' + (h.operator||'—') + '</td>'
      + '<td class="num-col">' + (h.tap_wt||0) + '</td>'
      + '<td class="num-col">' + (h.C||0).toFixed(2) + '</td>'
      + '<td class="num-col">' + (h.Si||0).toFixed(2) + '</td>'
      + '<td class="num-col">' + (h.Mn||0).toFixed(2) + '</td>'
      + '<td class="num-col">' + (h.Cr||0).toFixed(2) + '</td>'
      + '<td class="num-col">' + (h.Ni||0).toFixed(2) + '</td>'
      + '<td class="num-col">' + (h.Mo||0).toFixed(2) + '</td>'
      + '</tr>';
  }).join('');
}

function filterHeats() {
  const q = document.getElementById('heat-search').value.toLowerCase();
  const filtered = allHeats.filter(h =>
    (h.heat_no||'').toLowerCase().includes(q) ||
    (h.grade_name||'').toLowerCase().includes(q) ||
    (h.grade_code||'').toLowerCase().includes(q));
  renderHeatTable(filtered);
}

async function loadHeatFromLog(heatNo) {
  // Navigate to Calculator and populate all fields from saved heat
  try {
    const res  = await fetch('/api/heats/' + encodeURIComponent(heatNo));
    if (!res.ok) { showToast('Heat not found: ' + heatNo, 'error'); return; }
    const h = await res.json();

    // Switch to calculator tab
    const calcBtn = document.querySelector('.nav-btn.active');
    showSection('calculator', document.querySelector('[onclick*="calculator"]'));

    // Populate heat info fields
    document.getElementById('furnace-no').value = h.furnace_no || '';
    document.getElementById('heat-no').value    = h.heat_no   || '';
    document.getElementById('operator').value   = h.operator  || '';
    document.getElementById('tap-weight').value = h.tap_wt    || 1000;
    document.getElementById('tap-temp').value   = h.tap_temp  || 1550;
    document.getElementById('ladle').value      = h.ladle     || '';

    // Hide heat-no uniqueness warning (it already exists, that's expected)
    const warn = document.getElementById('heat-no-warn');
    if (warn) warn.style.display = 'none';

    // Set grade
    if (h.grade_code) {
      const g = grades.find(x => x.code === h.grade_code);
      if (g) {
        document.getElementById('grade-select').value = h.grade_code;
        // Update grade search input display
        const inp = document.getElementById('grade-search-input');
        if (inp) inp.value = h.grade_code + ' — ' + h.grade_name;
        selectedGrade = g;
        const aimBlock = document.getElementById('grade-aim');
        if (aimBlock) aimBlock.style.display = '';
        renderChemCells('aim-cells', ELEMENTS.map(el => ({ el, value: g[el]||0, status:'' })));
        renderLaddleAdditions();
      }
    }

    updateTotals();
    showToast('Loaded heat ' + heatNo + ' into calculator', 'success');
  } catch(e) {
    showToast('Error loading heat: ' + e.message, 'error');
  }
}

async function checkHeatNoUnique(val) {
  const warn = document.getElementById('heat-no-warn');
  if (!val || !val.trim()) { if (warn) warn.style.display = 'none'; return; }
  try {
    const res = await fetch('/api/heats/check/' + encodeURIComponent(val.trim()));
    const d   = await res.json();
    if (warn) warn.style.display = d.exists ? '' : 'none';
  } catch(e) { /* ignore */ }
}

/* ═══════════════════════════════════════════════════════════════
   GRADE LIBRARY
═══════════════════════════════════════════════════════════════ */
function renderGradeTable(data) {
  const tbody = document.getElementById('grades-body');
  if (!tbody) return;
  tbody.innerHTML = data.map(g => `<tr>
    <td><strong>${g.code}</strong></td>
    <td>${g.description}</td>
    <td class="num-col">${g.C.toFixed(2)}</td>
    <td class="num-col">${g.Si.toFixed(2)}</td>
    <td class="num-col">${g.Mn.toFixed(2)}</td>
    <td class="num-col">${g.Cr.toFixed(2)}</td>
    <td class="num-col">${g.Ni.toFixed(2)}</td>
    <td class="num-col">${g.Mo.toFixed(2)}</td>
    <td class="num-col">${g.Cu.toFixed(2)}</td>
    <td class="num-col">${(g.Al_deox||0).toFixed(4)}</td>
    <td class="num-col">${(g.CaSiMn||0).toFixed(4)}</td>
  </tr>`).join('');
}

function filterGrades() {
  const q = document.getElementById('grade-search').value.toLowerCase();
  renderGradeTable(allGrades.filter(g =>
    g.code.toLowerCase().includes(q) ||
    g.description.toLowerCase().includes(q)));
}

/* ═══════════════════════════════════════════════════════════════
   SHARED HELPERS
═══════════════════════════════════════════════════════════════ */

/**
 * Render chemistry cells.
 * items: [{el, value, status, icon?}]
 * showIcon: show status icon in label
 */
function renderChemCells(containerId, items, showIcon=false) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = items.map(({ el: name, value, status, icon }) => {
    const cls = status === 'ok'   ? 'status-ok'
              : status === 'low'  ? 'status-low'
              : status === 'high' ? 'status-high'
              : '';
    const lbl = showIcon && icon && status ? `${name} ${icon}` : name;
    return `<div class="chem-cell ${cls}">
      <div class="el">${lbl}</div>
      <div class="val">${value.toFixed(2)}</div>
    </div>`;
  }).join('');
}

/**
 * Render a single bar row.
 * cls: 'ok' | 'low' | 'high'
 */
function barRow(el, aim, actual, maxV, cls) {
  const aimPct = maxV > 0 ? aim / maxV * 100 : 0;
  const actPct = maxV > 0 ? actual / maxV * 100 : 0;
  return `<div class="bar-row">
    <span class="bar-el">${el}</span>
    <div class="bar-bg">
      <div class="bar-aim-line" style="left:${aimPct.toFixed(1)}%"></div>
      <div class="bar-fill ${cls}" style="width:${actPct.toFixed(1)}%"></div>
    </div>
    <span class="bar-val">${actual.toFixed(2)} / ${aim.toFixed(2)}</span>
  </div>`;
}

function setBadge(id, text, type) {
  const b = document.getElementById(id);
  if (!b) return;
  b.textContent = text;
  b.className   = 'badge ' + type;
}

/* ═══════════════════════════════════════════════════════════════
   HEAT INFO — TAP COUNT & POUR TEMP
═══════════════════════════════════════════════════════════════ */

// Called by the Single/Double/Triple buttons in heat info card
function setHeatTaps(n, btn) {
  heatTaps = n;
  document.querySelectorAll('#htap-1,#htap-2,#htap-3').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function onPourTempChange() {
  // Update argon purging display if active
  if (argonPurging) onArgonChange();
}

/* ── Print report — no modal, uses heat info taps directly ── */
function showPrintModal() {
  // Skip modal, go straight to print
  openPrintReport();
}
function closePrintModal() {}
function setModalTaps(n, btn) { setHeatTaps(n, btn); }
function renderTapSplitInputs() {}

async function openPrintReport() {
  if (!selectedGrade) { showToast('Select a grade first.', 'error'); return; }

  const tapWt   = parseFloat(document.getElementById('tap-weight').value) || 0;
  const pourTemp = parseFloat(document.getElementById('tap-temp').value) || 1550;
  const ladle   = document.getElementById('ladle').value || '';
  const perTap  = heatTaps > 1 ? Math.round(tapWt / heatTaps) : tapWt;

  // Build tap splits automatically from heat info (equal weight split, same temp/ladle)
  const tapSplits = [];
  for (let i = 0; i < heatTaps; i++) {
    const wt = (i < heatTaps - 1) ? perTap : (tapWt - perTap * (heatTaps - 1));
    tapSplits.push({ weight: Math.max(0, wt), temp: pourTemp, ladle: ladle });
  }

  // Pour temp entered by user = pour temp in UI
  // Report "Pour Temp" label = what user typed (pour temp)
  // Report "Tap Temp" label  = pour temp - 50 (reverse of old logic)
  const reportPourTemp = argonPurging ? pourTemp + 30 : pourTemp;

  const heatNo = document.getElementById('heat-no').value;

  const payload = {
    grade_code:     selectedGrade.code,
    tap_weight:     tapWt,
    charge_items:   getChargeItems(),
    addition_items: alloyRows.filter(a => a.planned + a.trim > 0).map(a => ({
      code: a.code, planned: a.planned, trim: a.trim,
    })),
    tap_splits:  tapSplits,
    heat_info: {
      furnace_no:       document.getElementById('furnace-no').value,
      heat_no:          heatNo,
      operator:         document.getElementById('operator').value,
      ladle:            ladle,
      pour_temp:        reportPourTemp,    // what user entered (+ argon if active)
      argon_purging:    argonPurging,
      melt_date:        new Date().toISOString().split('T')[0],
      mpn:              '',
    },
  };

  try {
    const res  = await fetch('/api/prepare_report', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.token) {
      // Open with save=1 so server writes to heat_pdf/
      window.open('/print_report?token=' + data.token + '&save=1', '_blank');
    } else {
      showToast('Failed to prepare report.', 'error');
    }
  } catch(e) {
    showToast('Error: ' + e.message, 'error');
  }
}


/* ═══════════════════════════════════════════════════════════════
   ARGON PURGING
═══════════════════════════════════════════════════════════════ */
function onArgonChange() {
  argonPurging = document.getElementById('argon-purging').checked;
  const info = document.getElementById('argon-info');
  const pourTemp = parseFloat(document.getElementById('tap-temp').value) || 0;
  info.style.display = argonPurging ? '' : 'none';
  if (argonPurging) {
    document.getElementById('argon-temp-display').textContent = pourTemp + 30;
  }
}

/* ═══════════════════════════════════════════════════════════════
   DILUTION CALCULATOR
═══════════════════════════════════════════════════════════════ */

// checkShowDilution moved to extended dilution section above

function buildDiluentDropdown() {
  const dd = document.getElementById('diluent-dropdown');
  if (!dd) return;
  // Scraps make good diluents (low carbon)
  const items = materials
    .filter(m => m.category === 'scrap' || m.category === 'grade_return')
    .sort((a,b) => (a.C||0) - (b.C||0));   // sort by lowest C first
  dd.innerHTML = items.map(m => {
    const safeD = (m.description||'').replace(/'/g,"\'");
    return `<div class="gd-item"
      onmousedown="selectDiluentItem(event,'${m.code}','${safeD}','${(m.C||0).toFixed(3)}')">
      <span class="gd-code">${m.code}</span>
      <span class="gd-desc">${m.description}</span>
      <span class="gd-chem" style="margin-left:auto">C=${(m.C||0).toFixed(3)}%</span>
    </div>`;
  }).join('') || '<div class="gd-empty">No materials</div>';
}

function filterDiluentDropdown() {
  const q  = (document.getElementById('diluent-search-input').value || '').toLowerCase();
  const dd = document.getElementById('diluent-dropdown');
  const items = materials
    .filter(m => (m.category === 'scrap' || m.category === 'grade_return') &&
      (m.code.toLowerCase().includes(q) || m.description.toLowerCase().includes(q)))
    .sort((a,b) => (a.C||0) - (b.C||0));
  dd.innerHTML = items.map(m => {
    const safeD = (m.description||'').replace(/'/g,"\'");
    return `<div class="gd-item"
      onmousedown="selectDiluentItem(event,'${m.code}','${safeD}','${(m.C||0).toFixed(3)}')">
      <span class="gd-code">${m.code}</span>
      <span class="gd-desc">${m.description}</span>
      <span class="gd-chem" style="margin-left:auto">C=${(m.C||0).toFixed(3)}%</span>
    </div>`;
  }).join('') || '<div class="gd-empty">No materials found</div>';
  dd.classList.add('open');
}

function openDiluentDropdown() {
  buildDiluentDropdown();
  document.getElementById('diluent-dropdown').classList.add('open');
}
function closeDiluentDropdownDelayed() {
  setTimeout(() => document.getElementById('diluent-dropdown')?.classList.remove('open'), 200);
}
function selectDiluentItem(e, code, desc, cPct) {
  e.preventDefault();
  document.getElementById('diluent-code').value          = code;
  document.getElementById('diluent-search-input').value  = code + ' — ' + desc + '  (C=' + cPct + '%)';
  document.getElementById('diluent-dropdown').classList.remove('open');
}

// runDilutionCalc moved to extended dilution section

function renderDilutionResult(data) {
  const wrap = document.getElementById('dilution-result');
  wrap.style.display = '';

  // Summary banner
  const banner = document.getElementById('dilution-summary');
  if (!data.needed) {
    banner.className   = 'dilution-banner-ok';
    banner.textContent = data.message;
    document.getElementById('dilution-steps').innerHTML         = '';
    document.getElementById('dilution-proj-cells').innerHTML    = '';
    document.getElementById('dilution-recovery-body').innerHTML = '';
    document.getElementById('dilution-no-recovery').style.display = 'none';
    return;
  }

  const r  = data.result;
  const el = data.target_element || 'C';
  banner.className = 'dilution-banner-excess';
  if (r.method === 'remove_replace') {
    banner.innerHTML = '<strong>Remove &amp; Replace (' + el + '):</strong> Remove <strong>' + r.kg_remove.toFixed(1)
      + ' kg</strong> → Add <strong>' + r.kg_diluent.toFixed(1)
      + ' kg</strong> of ' + data.diluent.description
      + ' &nbsp;|&nbsp; ' + el + ': <strong>' + data.C_current.toFixed(3) + '%</strong> → <strong>'
      + r.final_C.toFixed(3) + '%</strong> (target ' + data.C_target.toFixed(3) + '%)';
  } else {
    banner.innerHTML = '<strong>Add Only (' + el + '):</strong> Add <strong>' + r.kg_diluent.toFixed(1)
      + ' kg</strong> of ' + data.diluent.description
      + ' &nbsp;|&nbsp; ' + el + ': <strong>' + data.C_current.toFixed(3) + '%</strong> → <strong>'
      + r.final_C.toFixed(3) + '%</strong> (target ' + data.C_target.toFixed(3) + '%)';
  }

  // Process steps
  const ol = document.getElementById('dilution-steps');
  ol.innerHTML = (data.steps || []).map(s => '<li>' + s + '</li>').join('');

  // Projected composition after dilution
  if (data.proj_pct && data.comparison) {
    const cmp = data.comparison;
    const cellData = ELEMENTS.map(el => {
      const c = cmp[el] || { aim:0, actual:0, status:'ok' };
      return { el, value: c.actual, status: c.status, aim: c.aim,
               icon: c.status === 'ok' ? '✓' : c.status === 'low' ? '↓' : '↑' };
    });
    renderChemCells('dilution-proj-cells', cellData, true);
  }

  // Recovery additions
  const tbody   = document.getElementById('dilution-recovery-body');
  const noRecov = document.getElementById('dilution-no-recovery');
  const recov   = data.recovery_additions || [];

  if (!recov.length) {
    tbody.innerHTML  = '';
    noRecov.style.display = '';
    document.getElementById('dilution-total-kg').textContent   = '0.00 kg';
    document.getElementById('dilution-total-cost').textContent = '$0.00';
  } else {
    noRecov.style.display = 'none';
    tbody.innerHTML = recov.map(r => '<tr>'
      + '<td><strong>' + r.element + '</strong></td>'
      + '<td class="num-col">' + r.aim.toFixed(3) + '</td>'
      + '<td class="num-col">' + r.after_dilution.toFixed(3) + '</td>'
      + '<td class="num-col status-warn-text">' + r.deficit.toFixed(3) + '</td>'
      + '<td>' + r.addition_desc + ' <small style="color:var(--text3)">(' + r.addition_code + ')</small></td>'
      + '<td class="num-col"><strong>' + r.addition_kg.toFixed(2) + '</strong></td>'
      + '<td class="num-col">$' + r.cost.toFixed(2) + '</td>'
      + '</tr>').join('');
    const totalKg   = recov.reduce((s,r) => s + r.addition_kg, 0);
    document.getElementById('dilution-total-kg').textContent   = totalKg.toFixed(2) + ' kg';
    document.getElementById('dilution-total-cost').textContent = '$' + data.total_recovery_cost.toFixed(2);
  }
}

/* ═══════════════════════════════════════════════════════════════
   RELOAD
═══════════════════════════════════════════════════════════════ */
async function reloadData(btn) {
  const origText = btn.textContent;
  btn.textContent = '⟳ Reloading…';
  btn.classList.add('spinning');
  try {
    const res  = await fetch('/api/reload', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'reloaded') {
      grades = []; materials = [];
      document.getElementById('grades-body').innerHTML = '';
      await loadGrades();
      await loadMaterials();
      allMaterials = materials;
      mmRenderTable(allMaterials);
      initAdditionsTable();
      chargeRows.forEach(id => {
        const dd = document.getElementById('mdd-' + id);
        if (dd) buildMatDropdown(id);
      });
      updateTotals();
      showToast('Reloaded — ' + data.grades + ' grades, ' + data.materials + ' materials', 'success');
    }
  } catch(e) {
    showToast('Reload failed: ' + e.message, 'error');
  }
  btn.textContent = origText;
  btn.classList.remove('spinning');
}

/* ═══════════════════════════════════════════════════════════════
   GRADE MANAGER
═══════════════════════════════════════════════════════════════ */
let gmEditCode = null;
const GM_FIELDS = ['C','Si','Mn','Cr','Ni','Mo','Cu','S','P','Al_deox','Al_ladle','CaSiMn','FeSiZr'];

function gmRenderTable(data) {
  const tbody = document.getElementById('gm-tbody');
  if (!tbody) return;
  if (!data || !data.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text3);padding:20px">No grades found</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(function(g) {
    return [
      '<tr>',
      '<td><strong>', (g.code||''), '</strong></td>',
      '<td>', (g.description||''), '</td>',
      '<td class="num-col">', (g.C||0).toFixed(2), '</td>',
      '<td class="num-col">', (g.Si||0).toFixed(2), '</td>',
      '<td class="num-col">', (g.Mn||0).toFixed(2), '</td>',
      '<td class="num-col">', (g.Cr||0).toFixed(2), '</td>',
      '<td class="num-col">', (g.Ni||0).toFixed(2), '</td>',
      '<td class="num-col">', (g.Mo||0).toFixed(2), '</td>',
      '<td style="white-space:nowrap">',
      '<button class="gm-edit-btn" ',
        'data-code="', (g.code||''), '" ',
        'onclick="gmStartEdit(this.dataset.code)">Edit</button> ',
      '<button class="gm-del-btn" ',
        'data-code="', (g.code||''), '" ',
        'data-desc="', (g.description||'').replace(/"/g,'&quot;'), '" ',
        'onclick="gmDelete(this.dataset.code,this.dataset.desc)">Del</button>',
      '</td></tr>'
    ].join('');
  }).join('');
}

function gmFilter() {
  const q = (document.getElementById('gm-filter').value || '').toLowerCase();
  gmRenderTable(allGrades.filter(g =>
    g.code.toLowerCase().includes(q) || g.description.toLowerCase().includes(q)));
}

function gmGetField(key) {
  const el = document.getElementById('gm-' + key);
  return el ? (parseFloat(el.value) || 0) : 0;
}
function gmSetField(key, val) {
  const el = document.getElementById('gm-' + key);
  if (el) el.value = (val !== undefined && val !== null) ? val : 0;
}

function gmStartEdit(code) {
  const g = allGrades.find(x => x.code === code);
  if (!g) return;
  gmEditCode = code;
  document.getElementById('gm-form-title').textContent = 'Edit: ' + code + ' — ' + g.description;
  document.getElementById('gm-cancel-btn').style.display = '';
  const codeEl = document.getElementById('gm-code');
  codeEl.value = g.code;
  codeEl.disabled = true;
  document.getElementById('gm-desc').value = g.description;
  GM_FIELDS.forEach(function(k) { gmSetField(k, g[k]); });
  document.getElementById('grade-manager').scrollIntoView({ behavior:'smooth' });
  gmHideMsg();
}

function gmCancelEdit() {
  gmEditCode = null;
  document.getElementById('gm-form-title').textContent = 'Add New Grade';
  document.getElementById('gm-cancel-btn').style.display = 'none';
  const codeEl = document.getElementById('gm-code');
  codeEl.disabled = false;
  codeEl.value = '';
  document.getElementById('gm-desc').value = '';
  GM_FIELDS.forEach(function(k) { gmSetField(k, 0); });
  gmHideMsg();
}

async function gmSaveGrade() {
  const code = (document.getElementById('gm-code').value || '').trim();
  const desc = (document.getElementById('gm-desc').value || '').trim();
  if (!code) { gmShowMsg('Grade code is required.', false); return; }
  if (!desc) { gmShowMsg('Description is required.', false); return; }

  const payload = { code: code, description: desc };
  GM_FIELDS.forEach(function(k) { payload[k] = gmGetField(k); });

  const isEdit = gmEditCode !== null;
  const url    = isEdit ? ('/api/grades/' + encodeURIComponent(gmEditCode)) : '/api/grades';
  const method = isEdit ? 'PUT' : 'POST';

  try {
    const res  = await fetch(url, {
      method: method,
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.error) { gmShowMsg('Error: ' + data.error, false); return; }

    gmShowMsg(isEdit ? 'Grade ' + code + ' updated!' : 'Grade ' + code + ' added!', true);

    const r2 = await fetch('/api/grades');
    grades = await r2.json();
    allGrades = grades;
    gmRenderTable(grades);
    buildGradeDropdown('gsw-main', 'grade-select', onGradeChange);
    buildGradeDropdown('gsw-trim', 'trim-grade-select', onTrimGradeChange);
    renderGradeTable(grades);

    if (!isEdit) { setTimeout(gmCancelEdit, 2000); }
  } catch(e) {
    gmShowMsg('Network error: ' + e.message, false);
  }
}

async function gmDelete(code, desc) {
  if (!confirm('Delete grade ' + code + ' — ' + desc + '?\nThis cannot be undone.')) return;
  try {
    const res  = await fetch('/api/grades/' + encodeURIComponent(code), { method: 'DELETE' });
    const data = await res.json();
    if (data.error) { showToast('Error: ' + data.error, 'error'); return; }
    showToast('Grade ' + code + ' deleted', 'success');
    const r2 = await fetch('/api/grades');
    grades = await r2.json();
    allGrades = grades;
    gmRenderTable(grades);
    buildGradeDropdown('gsw-main', 'grade-select', onGradeChange);
    buildGradeDropdown('gsw-trim', 'trim-grade-select', onTrimGradeChange);
    renderGradeTable(grades);
    if (gmEditCode === code) gmCancelEdit();
  } catch(e) {
    showToast('Error: ' + e.message, 'error');
  }
}

function gmShowMsg(msg, ok) {
  const el = document.getElementById('gm-msg');
  if (!el) return;
  el.textContent = msg;
  el.className   = ok ? 'gm-msg-ok' : 'gm-msg-err';
  el.style.display = '';
  if (ok) setTimeout(gmHideMsg, 3000);
}
function gmHideMsg() {
  const el = document.getElementById('gm-msg');
  if (el) el.style.display = 'none';
}

/* ═══════════════════════════════════════════════════════════════
   MATERIAL MANAGER
═══════════════════════════════════════════════════════════════ */
let mmEditCode = null;
let allMaterials = [];
const MM_FIELDS = ['C','Si','Mn','Cr','Ni','Mo','Cu','S','P'];

function mmRenderTable(data) {
  const tbody = document.getElementById('mm-tbody');
  if (!tbody) return;
  if (!data || !data.length) {
    tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--text3);padding:20px">No materials found</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(function(m) {
    var cat = m.category === 'alloy' ? 'Alloy' : 'Scrap';
    return [
      '<tr>',
      '<td><strong>', (m.code||''), '</strong></td>',
      '<td>', (m.description||''), '</td>',
      '<td><span style="font-size:11px;padding:2px 6px;border-radius:4px;background:var(--bg);color:var(--text2)">', cat, '</span></td>',
      '<td class="num-col">', (m.C||0).toFixed(2), '</td>',
      '<td class="num-col">', (m.Si||0).toFixed(2), '</td>',
      '<td class="num-col">', (m.Mn||0).toFixed(2), '</td>',
      '<td class="num-col">', (m.Cr||0).toFixed(2), '</td>',
      '<td class="num-col">', (m.Ni||0).toFixed(2), '</td>',
      '<td class="num-col">', (m.Mo||0).toFixed(2), '</td>',
      '<td class="num-col">$', (m.cost||0).toFixed(2), '</td>',
      '<td style="white-space:nowrap">',
      '<button class="gm-edit-btn" ',
        'data-code="', (m.code||''), '" ',
        'onclick="mmStartEdit(this.dataset.code)">Edit</button> ',
      '<button class="gm-del-btn" ',
        'data-code="', (m.code||''), '" ',
        'data-desc="', (m.description||'').replace(/"/g,'&quot;'), '" ',
        'onclick="mmDelete(this.dataset.code,this.dataset.desc)">Del</button>',
      '</td></tr>'
    ].join('');
  }).join('');
}

function mmFilterList() {
  const q   = (document.getElementById('mm-filter').value || '').toLowerCase();
  const cat = document.getElementById('mm-cat-filter').value;
  let filtered = allMaterials;
  if (cat) filtered = filtered.filter(m => m.category === cat);
  if (q)   filtered = filtered.filter(m =>
    m.code.toLowerCase().includes(q) || m.description.toLowerCase().includes(q));
  mmRenderTable(filtered);
}

function mmGetField(key) {
  const el = document.getElementById('mm-' + key);
  return el ? (parseFloat(el.value) || 0) : 0;
}
function mmSetField(key, val) {
  const el = document.getElementById('mm-' + key);
  if (el) el.value = (val !== undefined && val !== null) ? val : 0;
}

function mmStartEdit(code) {
  const m = allMaterials.find(x => x.code === code);
  if (!m) return;
  mmEditCode = code;
  document.getElementById('mm-form-title').textContent = 'Edit: ' + code + ' — ' + m.description;
  document.getElementById('mm-cancel-btn').style.display = '';
  const codeEl = document.getElementById('mm-code');
  codeEl.value = m.code; codeEl.disabled = true;
  document.getElementById('mm-desc').value = m.description;
  document.getElementById('mm-category').value = m.category || 'scrap';
  MM_FIELDS.forEach(k => mmSetField(k, m[k]));
  mmSetField('cost', m.cost);
  document.getElementById('material-manager').scrollIntoView({ behavior:'smooth' });
  mmHideMsg();
}

function mmCancelEdit() {
  mmEditCode = null;
  document.getElementById('mm-form-title').textContent = 'Add New Material';
  document.getElementById('mm-cancel-btn').style.display = 'none';
  const codeEl = document.getElementById('mm-code');
  codeEl.disabled = false; codeEl.value = '';
  document.getElementById('mm-desc').value = '';
  document.getElementById('mm-category').value = 'scrap';
  MM_FIELDS.forEach(k => mmSetField(k, 0));
  mmSetField('cost', 0);
  mmHideMsg();
}

async function mmSaveMaterial() {
  const code = (document.getElementById('mm-code').value || '').trim();
  const desc = (document.getElementById('mm-desc').value || '').trim();
  if (!code) { mmShowMsg('Material code is required.', false); return; }
  if (!desc) { mmShowMsg('Description is required.', false); return; }

  const payload = {
    code, description: desc,
    category: document.getElementById('mm-category').value,
    cost: mmGetField('cost'),
  };
  MM_FIELDS.forEach(k => { payload[k] = mmGetField(k); });

  const isEdit = mmEditCode !== null;
  const url    = isEdit ? ('/api/materials/' + encodeURIComponent(mmEditCode)) : '/api/materials';
  const method = isEdit ? 'PUT' : 'POST';

  try {
    const res  = await fetch(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const data = await res.json();
    if (data.error) { mmShowMsg('Error: ' + data.error, false); return; }
    mmShowMsg(isEdit ? 'Material ' + code + ' updated!' : 'Material ' + code + ' added!', true);
    await mmReloadMaterials();
    if (!isEdit) setTimeout(mmCancelEdit, 2000);
  } catch(e) {
    mmShowMsg('Network error: ' + e.message, false);
  }
}

async function mmDelete(code, desc) {
  if (!confirm('Delete material ' + code + ' — ' + desc + '?\nThis cannot be undone.')) return;
  try {
    const res  = await fetch('/api/materials/' + encodeURIComponent(code), { method: 'DELETE' });
    const data = await res.json();
    if (data.error) { showToast('Error: ' + data.error, 'error'); return; }
    showToast('Material ' + code + ' deleted', 'success');
    await mmReloadMaterials();
    if (mmEditCode === code) mmCancelEdit();
  } catch(e) {
    showToast('Error: ' + e.message, 'error');
  }
}

async function mmReloadMaterials() {
  const res  = await fetch('/api/materials');
  materials  = await res.json();
  allMaterials = materials;
  mmRenderTable(materials);
  mmFilterList();
  // Rebuild material dropdowns in charge rows
  chargeRows.forEach(id => {
    const dd = document.getElementById('mdd-' + id);
    if (dd) { const cur = document.getElementById('mat-' + id)?.value || ''; buildMatDropdown(id); }
  });
}

function mmShowMsg(msg, ok) {
  const el = document.getElementById('mm-msg');
  if (!el) return;
  el.textContent = msg;
  el.className   = ok ? 'gm-msg-ok' : 'gm-msg-err';
  el.style.display = '';
  if (ok) setTimeout(mmHideMsg, 3000);
}
function mmHideMsg() {
  const el = document.getElementById('mm-msg');
  if (el) el.style.display = 'none';
}

/* ═══════════════════════════════════════════════════════════════
   DILUTION — ALL ELEMENTS (extended)
═══════════════════════════════════════════════════════════════ */

// After trim calc — check ALL elements that are above aim, not just C
function checkShowDilution(trimData) {
  const card = document.getElementById('dilution-card');
  if (!trimGrade) { card.style.display = 'none'; return; }

  // Find elements above aim
  const overElements = [];
  ELEMENTS.forEach(el => {
    const aim     = trimGrade[el] || 0;
    const actual  = parseFloat(document.getElementById('spectro-' + el).value) || 0;
    if (aim > 0 && actual > aim + 0.005) {
      overElements.push({ el, actual, aim, excess: actual - aim });
    }
  });

  if (overElements.length > 0) {
    card.style.display = '';
    const badge = document.getElementById('dilution-c-badge');
    const labels = overElements.map(e => e.el + ':' + e.actual.toFixed(3) + '% (aim ' + e.aim.toFixed(3) + '%)');
    badge.textContent = 'Over aim — ' + labels.join('  ');
    badge.className   = 'badge err';
    // Auto-select the most over-aim element in dropdown
    const worst = overElements.sort((a,b) => (b.excess/b.aim) - (a.excess/a.aim))[0];
    const elSel = document.getElementById('dilution-element');
    if (elSel) elSel.value = worst.el;
    buildDiluentDropdown();
  } else {
    card.style.display = 'none';
  }
}

function onDilutionElementChange() {
  // When element changes, rebuild diluent dropdown filtered by that element being low
  buildDiluentDropdown();
}

async function runDilutionCalc() {
  if (!trimGrade) { showToast('Select a grade first.', 'error'); return; }

  const furnaceKg      = parseFloat(document.getElementById('trim-furnace-kg').value) || 0;
  const diluentCode    = document.getElementById('diluent-code').value || 'FS1045';
  const method         = document.getElementById('dilution-method').value;
  const targetElement  = document.getElementById('dilution-element')?.value || 'C';

  const current_pct = {};
  ELEMENTS.forEach(el => {
    current_pct[el] = parseFloat(document.getElementById('spectro-' + el).value) || 0;
  });

  const res = await fetch('/api/dilution', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      grade_code:      trimGrade.code.trim(),
      furnace_kg:      furnaceKg,
      current_pct,
      diluent_code:    diluentCode,
      method,
      target_element:  targetElement,
    }),
  });
  const data = await res.json();
  if (data.error) { showToast('Dilution error: ' + data.error, 'error'); return; }
  renderDilutionResult(data);
}

function showToast(msg, type='') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className   = 'toast show ' + type;
  setTimeout(() => { t.className = 'toast'; }, 3200);
}

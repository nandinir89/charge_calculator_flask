from flask import Flask, jsonify, request, render_template, send_file
from db import ExcelDB
from datetime import datetime
from pathlib import Path
import uuid, os, io
# HTML-based print-to-PDF (no reportlab needed)

app = Flask(__name__)
db = ExcelDB()   # uses data/ CSV files

ELEMENTS = ['C', 'Si', 'Mn', 'S', 'P', 'Cr', 'Ni', 'Mo', 'Cu']

# Alloy → primary element mapping with composition %
ALLOY_MAP = {
    'C':  ('GRAF',  98.0),
    'Si': ('FESI',  75.49),
    'Mn': ('HCMN',  77.3),
    'Cr': ('HCCR',  66.59),
    'Ni': ('NI',   100.0),
    'Mo': ('FEMO',  66.9),
    'Cu': ('CU',   100.0),
}

# ── Pages ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

# ── API: Metal grades ─────────────────────────────────────────────────────────

@app.route('/api/grades')
def api_grades():
    return jsonify(db.get_grades())

@app.route('/api/grades/<code>')
def api_grade(code):
    g = db.get_grade(code)
    if not g:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(g)

# ── API: Materials (scraps + alloys) ─────────────────────────────────────────

@app.route('/api/materials')
def api_materials():
    return jsonify(db.get_materials())

@app.route('/api/materials/<code>')
def api_material(code):
    m = db.get_material(code)
    if not m:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(m)

# ── API: Calculate (planned charge + alloy additions) ────────────────────────

@app.route('/api/calculate', methods=['POST'])
def api_calculate():
    data = request.json
    grade_code     = data.get('grade_code')
    tap_weight     = float(data.get('tap_weight', 1000))
    charge_items   = data.get('charge_items', [])    # [{code, weight}]
    addition_items = data.get('addition_items', [])  # [{code, planned, trim}]

    grade = db.get_grade(grade_code)
    if not grade:
        return jsonify({'error': 'Grade not found'}), 400

    # ── Base charge chemistry ────────────────────────────────────
    total_charge_kg = 0.0
    chem_kg = {el: 0.0 for el in ELEMENTS}

    for item in charge_items:
        mat = db.get_material(item['code'])
        wt  = float(item.get('weight', 0))
        if mat and wt > 0:
            total_charge_kg += wt
            for el in ELEMENTS:
                chem_kg[el] += (mat.get(el, 0) or 0) / 100 * wt

    # ── Furnace alloy additions ──────────────────────────────────
    total_add_kg    = 0.0
    addition_results = []
    for item in addition_items:
        mat     = db.get_material(item['code'])
        planned = float(item.get('planned', 0))
        trim    = float(item.get('trim', 0))
        total   = planned + trim
        if mat and total > 0:
            total_add_kg += total
            for el in ELEMENTS:
                chem_kg[el] += (mat.get(el, 0) or 0) / 100 * total
            addition_results.append({
                'code':        item['code'],
                'description': mat.get('description', ''),
                'planned':     planned,
                'trim':        trim,
                'total':       total,
                'cost':        round((mat.get('cost', 0) or 0) * total, 2),
            })

    final_wt  = (total_charge_kg + total_add_kg) or 1
    final_pct = {el: round(chem_kg[el] / final_wt * 100, 4) for el in ELEMENTS}

    # ── Compare to aim ───────────────────────────────────────────
    comparison = _compare(grade, final_pct)

    # ── Auto-suggest additions based on charge alone ─────────────
    auto_additions = _auto_additions(grade, chem_kg, total_charge_kg or tap_weight, tap_weight)

    # ── Ladle / deoxidation additions ────────────────────────────
    ladle_additions = _ladle_additions(grade, tap_weight)

    return jsonify({
        'total_charge_kg':    round(total_charge_kg, 2),
        'total_additions_kg': round(total_add_kg, 2),
        'final_weight_kg':    round(final_wt, 2),
        'tap_weight':         tap_weight,
        'difference_kg':      round(tap_weight - total_charge_kg, 2),
        'final_pct':          final_pct,
        'comparison':         comparison,
        'additions':          addition_results,
        'total_addition_cost':round(sum(a['cost'] for a in addition_results), 2),
        'auto_additions':     auto_additions,
        'ladle_additions':    ladle_additions,
    })


# ── API: Trim correction (spectro actuals → recalc trim) ─────────────────────

@app.route('/api/trim_correction', methods=['POST'])
def api_trim_correction():
    """
    After tapping, the operator enters spectro actuals.
    We recalculate which alloys are still needed (trim additions)
    to bring the melt on-aim before ladle treatment.

    Payload:
      grade_code   – target grade
      furnace_kg   – actual furnace weight (kg) after tap
      spectro      – {C, Si, Mn, Cr, Ni, Mo, Cu, S, P}  (% as-read)
      existing_trim – [{code, kg}]  additions already in trim (optional)
    """
    data        = request.json
    grade_code  = data.get('grade_code')
    furnace_kg  = float(data.get('furnace_kg', 0))
    spectro     = data.get('spectro', {})          # actual % from spectrometer
    existing    = data.get('existing_trim', [])

    grade = db.get_grade((grade_code or '').strip())
    if not grade:
        return jsonify({'error': f'Grade not found: {grade_code!r}'}), 400
    if furnace_kg <= 0:
        return jsonify({'error': 'furnace_kg must be > 0'}), 400

    # Build chemistry kg from spectro readings
    chem_kg = {el: (float(spectro.get(el, 0)) / 100) * furnace_kg for el in ELEMENTS}

    # Account for any trim already committed
    total_trim_kg = 0.0
    for item in existing:
        mat = db.get_material(item['code'])
        kg  = float(item.get('kg', 0))
        if mat and kg > 0:
            total_trim_kg += kg
            furnace_kg    += kg          # grows the melt
            for el in ELEMENTS:
                chem_kg[el] += (mat.get(el, 0) or 0) / 100 * kg

    # Current composition after any committed trim
    current_pct = {el: round(chem_kg[el] / furnace_kg * 100, 4) for el in ELEMENTS}

    # Recalculate required trim additions
    trim_needed = []
    for el, (code, alloy_pct) in ALLOY_MAP.items():
        aim     = grade.get(el, 0) or 0
        if aim <= 0:
            continue
        have    = current_pct.get(el, 0)
        deficit = aim - have
        if deficit > 0.005:
            kg_needed = (deficit / 100 * furnace_kg) / (alloy_pct / 100)
            mat = db.get_material(code)
            trim_needed.append({
                'element':      el,
                'aim':          round(aim, 4),
                'actual':       round(have, 4),
                'deficit':      round(deficit, 4),
                'addition_code':code,
                'addition_desc':mat['description'] if mat else code,
                'addition_kg':  round(kg_needed, 2),
                'cost':         round((mat.get('cost', 0) or 0) * kg_needed, 2) if mat else 0,
            })

    # Projected final composition after trim
    proj_chem_kg = dict(chem_kg)
    for t in trim_needed:
        mat = db.get_material(t['addition_code'])
        if mat:
            for el in ELEMENTS:
                proj_chem_kg[el] += (mat.get(el, 0) or 0) / 100 * t['addition_kg']
    proj_wt  = furnace_kg + sum(t['addition_kg'] for t in trim_needed)
    proj_pct = {el: round(proj_chem_kg[el] / proj_wt * 100, 4) for el in ELEMENTS}
    comparison = _compare(grade, proj_pct)

    return jsonify({
        'furnace_kg':      round(furnace_kg, 2),
        'spectro':         spectro,
        'current_pct':     current_pct,
        'trim_needed':     trim_needed,
        'projected_pct':   proj_pct,
        'comparison':      comparison,
        'total_trim_kg':   round(sum(t['addition_kg'] for t in trim_needed), 2),
        'total_trim_cost': round(sum(t['cost'] for t in trim_needed), 2),
    })


# ── API: Ladle additions ──────────────────────────────────────────────────────

@app.route('/api/ladle_additions/<grade_code>')
def api_ladle_additions(grade_code):
    """Return the prescribed ladle/deoxidation additions for a grade."""
    grade = db.get_grade(grade_code)
    if not grade:
        return jsonify({'error': 'Not found'}), 404
    tap_weight = float(request.args.get('tap_weight', 1000))
    return jsonify(_ladle_additions(grade, tap_weight))


# ── Shared helpers ────────────────────────────────────────────────────────────

def _compare(grade, pct_dict):
    comparison = {}
    for el in ELEMENTS:
        aim    = grade.get(el, 0) or 0
        actual = pct_dict.get(el, 0)
        tol    = aim * 0.15 + 0.02
        status = 'ok' if abs(actual - aim) <= tol else ('low' if actual < aim else 'high')
        comparison[el] = {'aim': aim, 'actual': actual, 'status': status}
    return comparison


def _auto_additions(grade, base_chem_kg, base_wt, tap_wt):
    results = []
    for el, (code, alloy_pct) in ALLOY_MAP.items():
        aim = grade.get(el, 0) or 0
        if aim <= 0:
            continue
        have    = (base_chem_kg.get(el, 0) / base_wt * 100) if base_wt > 0 else 0
        deficit = aim - have
        if deficit > 0.005:
            kg_needed = (deficit / 100 * tap_wt) / (alloy_pct / 100)
            mat = db.get_material(code)
            results.append({
                'element':      el,
                'aim':          round(aim, 4),
                'have':         round(have, 4),
                'deficit':      round(deficit, 4),
                'addition_code':code,
                'addition_desc':mat['description'] if mat else code,
                'addition_kg':  round(kg_needed, 2),
            })
    return results


def _ladle_additions(grade, tap_weight):
    """
    Build the ladle/deoxidation/inoculant additions for a grade.
    Rates are stored as fractions (e.g. 0.025 = 2.5 kg/t).
    Multiplied by 100 to get kg/tonne, then by tap_weight/1000 for absolute kg.
    """
    tonne = tap_weight / 1000.0
    additions = []

    def _add(name, fa_code, rate_frac, location):
        rate = float(rate_frac or 0)
        if rate > 0:
            rate_per_t = round(rate * 100, 4)
            additions.append({
                'name':              name,
                'fa_code':           fa_code,
                'location':          location,
                'rate_kg_per_tonne': rate_per_t,
                'kg':                round(rate_per_t * tonne, 3),
            })

    # Steel grades — cols 14-21 are fractions (multiply *100 to get kg/t)
    _add('Aluminium (Furnace)', 'FA1240', grade.get('Al_deox', 0),   'furnace')
    _add('Aluminium (Ladle)',   'FA1240', grade.get('Al_ladle', 0),  'ladle')
    _add('Aluminium (Ladle 2)', 'FA1240', grade.get('Al_ladle2', 0),'ladle')
    _add('Hypercal',            'FA1364', grade.get('Hypercal', 0),  'ladle')
    _add('Fe-Se',               'FA1365', grade.get('FeSe', 0),      'ladle')
    _add('Ca-Si-Mn',            'FA1190', grade.get('CaSiMn', 0),    'ladle')
    _add('Fe-Si-Zr',            'FA1210', grade.get('FeSiZr', 0),    'ladle')
    _add('Fe-Ti7O',             'FA1180', grade.get('FeTi', 0),      'ladle')
    _add('Fe-B',                'FA1160', grade.get('FeB', 0),       'ladle')

    # Iron/SG grades — cols 23-26 are ALREADY in kg/tonne (no *100 needed)
    def _add_direct(name, fa_code, rate_kg_per_t, location):
        rate = float(rate_kg_per_t or 0)
        if rate > 0:
            additions.append({
                'name':              name,
                'fa_code':           fa_code,
                'location':          location,
                'rate_kg_per_tonne': round(rate, 4),
                'kg':                round(rate * tonne, 3),
            })

    _add_direct('Mg-Fe-Si (Nodulariser)', 'FA1011', grade.get('MgFeSi', 0),    'ladle')
    _add_direct('Barinoc (Inoculant)',    'FA1070', grade.get('Barinoc', 0),    'ladle')
    _add_direct('Superseed (Inoculant)',  'FA1197', grade.get('Superseed', 0),  'ladle')
    _add_direct('Fe-Ti7O (2)',            'FA1180', grade.get('FeTi2', 0),      'ladle')

    return additions


# ── API: Reload / cache control ──────────────────────────────────────────────

@app.route('/api/reload', methods=['POST'])
def api_reload():
    """Force reload all data from Excel (clears in-memory cache)."""
    db.clear_cache()
    grades_count    = len(db.get_grades())
    materials_count = len(db.get_materials())
    return jsonify({
        'status':   'reloaded',
        'grades':   grades_count,
        'materials':materials_count,
    })

# ── API: Heat log ─────────────────────────────────────────────────────────────

@app.route('/api/heats', methods=['GET'])
def api_heats():
    return jsonify(db.get_heats())

@app.route('/api/heats', methods=['POST'])
def api_save_heat():
    data = request.json
    heat_no = data.get('heat_no','').strip()
    # Uniqueness check
    if db.get_heat(heat_no):
        return jsonify({'error': f'Heat no. {heat_no!r} already exists in the log.'}), 409
    try:
        db.save_heat(data)
        return jsonify({'status': 'saved'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/heats/<heat_no>', methods=['GET'])
def api_get_heat(heat_no):
    from urllib.parse import unquote
    heat = db.get_heat(unquote(heat_no))
    if not heat:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(heat)

@app.route('/api/heats/check/<heat_no>', methods=['GET'])
def api_check_heat_no(heat_no):
    """Return whether a heat number already exists."""
    from urllib.parse import unquote
    exists = db.get_heat(unquote(heat_no)) is not None
    return jsonify({'exists': exists})

# furnace_weight route replaced by api_furnace_weight_v2 above

# ── API: Trim log ─────────────────────────────────────────────────────────────

@app.route('/api/trims', methods=['GET'])
def api_get_trims():
    """Return all trim records, or filter by heat_no FK."""
    heat_no = request.args.get('heat_no', None)
    return jsonify(db.get_trims(heat_no=heat_no))

@app.route('/api/trims', methods=['POST'])
def api_save_trim():
    """Save a trim record linked to a heat (heat_no = FK)."""
    data = request.json
    try:
        trim_id = db.save_trim(data)
        return jsonify({'status': 'saved', 'trim_id': trim_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trims/<heat_no>', methods=['GET'])
def api_get_trims_for_heat(heat_no):
    """Return all trim records for a specific heat number."""
    from urllib.parse import unquote
    return jsonify(db.get_trims(heat_no=unquote(heat_no)))


# ── API: Furnace relining management ─────────────────────────────────────────
# Relining resets the heat count for a furnace — stored in data/reline_log.csv

def _get_reline_dates():
    """Load furnace -> last_reline_date map from data/reline_log.csv."""
    p = Path(__file__).parent / 'data' / 'reline_log.csv'
    if not p.exists():
        return {}
    import csv as _csv
    result = {}
    with open(p, newline='', encoding='utf-8') as f:
        for row in _csv.DictReader(f):
            fn   = row.get('furnace_no','').strip()
            date = row.get('reline_date','').strip()
            if fn:
                result[fn] = date   # last entry wins
    return result

def _save_reline(furnace_no: str, date_str: str):
    import csv as _csv
    p = Path(__file__).parent / 'data' / 'reline_log.csv'
    file_exists = p.exists()
    with open(p, 'a', newline='', encoding='utf-8') as f:
        w = _csv.DictWriter(f, fieldnames=['furnace_no','reline_date','recorded_by'])
        if not file_exists:
            w.writeheader()
        w.writerow({'furnace_no': furnace_no, 'reline_date': date_str, 'recorded_by': 'user'})

@app.route('/api/furnace_reline', methods=['POST'])
def api_furnace_reline():
    """Record that a furnace has been relined. Resets the heat weight counter."""
    data       = request.json
    furnace_no = data.get('furnace_no','').strip()
    if not furnace_no:
        return jsonify({'error': 'furnace_no required'}), 400
    date_str = datetime.now().strftime('%Y-%m-%d')
    _save_reline(furnace_no, date_str)
    return jsonify({'status': 'relined', 'furnace_no': furnace_no, 'date': date_str})

@app.route('/api/furnace_weight/<furnace_no>', methods=['GET'])
def api_furnace_weight_v2(furnace_no):
    """Sum of tap weights since last reline for a furnace."""
    from urllib.parse import unquote
    fn          = unquote(furnace_no).strip()
    reline_dates = _get_reline_dates()
    last_reline  = reline_dates.get(fn)   # 'YYYY-MM-DD' or None

    # Only count heats AFTER the last reline date (strictly after, not same day)
    all_heats = db.get_heats()
    if last_reline:
        heats = [h for h in all_heats
                 if h.get('furnace_no','').strip() == fn
                 and (h.get('melt_date','') or '') > last_reline]
    else:
        heats = [h for h in all_heats if h.get('furnace_no','').strip() == fn]

    total_tonnes = sum(h.get('tap_wt', 0) for h in heats) / 1000.0
    RELINE_WARN  = 180
    RELINE_LIMIT = 200
    return jsonify({
        'furnace_no':   fn,
        'heat_count':   len(heats),
        'total_tonnes': round(total_tonnes, 2),
        'last_reline':  last_reline or 'Never',
        'warn':         total_tonnes >= RELINE_WARN,
        'critical':     total_tonnes >= RELINE_LIMIT,
        'remaining':    round(max(0, RELINE_LIMIT - total_tonnes), 2),
    })


# ── PDF save (Trim + Heat reports) ───────────────────────────────────────────
# These save an HTML file to a local folder, then the browser triggers print-to-PDF

@app.route('/api/prepare_trim_report', methods=['POST'])
def api_prepare_trim_report():
    """Prepare and save a trim correction report token, also save HTML to trim_pdf/."""
    import os, uuid as _uuid
    data        = request.json
    grade_code  = data.get('grade_code','')
    furnace_kg  = float(data.get('furnace_kg', 0))
    spectro     = data.get('spectro', {})
    trim_needed = data.get('trim_needed', [])
    proj_pct    = data.get('projected_pct', {})
    comparison  = data.get('comparison', {})
    ladle_adds  = data.get('ladle_additions', [])
    heat_info   = data.get('heat_info', {})
    grade       = db.get_grade(grade_code) or {}

    report_data = {
        'report_type':   'trim',
        'grade_code':    grade_code,
        'grade_description': grade.get('description',''),
        'heat_info':     heat_info,
        'furnace_kg':    furnace_kg,
        'spectro':       spectro,
        'trim_needed':   trim_needed,
        'projected_pct': proj_pct,
        'comparison':    comparison,
        'ladle_additions': ladle_adds,
        'aim_chemistry': {el: grade.get(el,0) for el in ELEMENTS},
    }

    token = str(_uuid.uuid4())
    _report_tokens[token] = report_data
    return jsonify({'token': token})

# ─────────────────────────────────────────────────────────────────────────────

# ── API: Print report ─────────────────────────────────────────────────────────
# Server-side token store so data survives the new-tab open
_report_tokens = {}   # token -> report_data dict (cleared on each new report)

@app.route('/print_report', methods=['GET'])
def print_report():
    """Render the print report page. Always saves to heat_pdf/HEATNO_taps.html."""
    token       = request.args.get('token', '')
    report_data = _report_tokens.pop(token, None)   # single-use

    if report_data:
        # Always save to heat_pdf/ folder alongside data/
        folder = Path(__file__).parent / 'heat_pdf'
        folder.mkdir(exist_ok=True)
        hi       = report_data.get('heat_info', {})
        heat_no  = str(hi.get('heat_no','unknown')).replace('/','_').replace('\\','_').replace(' ','_')
        tap_type = report_data.get('tap_type','Single_Tap').replace(' ','_')
        fname    = f'heat_{heat_no}_{tap_type}.html'
        html_str = render_template('print_report.html', report_data_json=report_data)
        saved_path = folder / fname
        saved_path.write_text(html_str, encoding='utf-8')
        report_data['_saved_file'] = str(saved_path)

    return render_template('print_report.html', report_data_json=report_data)


@app.route('/trim_report', methods=['GET'])
def trim_report_page():
    """Render the trim correction report. Saves to trim_pdf/."""
    token       = request.args.get('token', '')
    report_data = _report_tokens.pop(token, None)

    if report_data:
        folder = Path(__file__).parent / 'trim_pdf'
        folder.mkdir(exist_ok=True)
        hi      = report_data.get('heat_info', {})
        heat_no = str(hi.get('heat_no','unknown')).replace('/','_').replace('\\','_').replace(' ','_')
        fname   = f'trim_{heat_no}.html'
        # Reuse print_report.html — it handles both tap and trim via D.report_type
        html_str = render_template('print_report.html', report_data_json=report_data)
        saved = folder / fname
        saved.write_text(html_str, encoding='utf-8')
        report_data['_saved_file'] = str(saved)

    return render_template('print_report.html', report_data_json=report_data)


@app.route('/api/prepare_report', methods=['POST'])
def api_prepare_report():
    """
    Store report payload server-side, return a single-use token.
    The print window uses the token to retrieve pre-rendered data.
    """
    # Re-use existing report_data logic inline
    data           = request.json
    grade_code     = data.get('grade_code', '')
    tap_weight     = float(data.get('tap_weight', 0))
    charge_items   = data.get('charge_items', [])
    addition_items = data.get('addition_items', [])
    tap_splits     = data.get('tap_splits', [])
    heat_info      = data.get('heat_info', {})
    # Carry through argon purging — report_tap_temp already adjusted in JS
    # (tap_temp + 30 if argon_purging) — just pass as-is

    grade = db.get_grade(grade_code) or {}

    total_charge_kg = 0.0
    chem_kg = {el: 0.0 for el in ELEMENTS}
    charge_rows_out = []

    for item in charge_items:
        mat = db.get_material(item['code'])
        wt  = float(item.get('weight', 0))
        if mat and wt > 0:
            total_charge_kg += wt
            for el in ELEMENTS:
                chem_kg[el] += (mat.get(el, 0) or 0) / 100 * wt
            charge_rows_out.append({
                'description': mat.get('description', item['code']),
                'code': item['code'], 'planned': wt, 'actual': 0, 'total': wt,
            })

    alloy_name_map = {
        'GRAF': 'FA1300 - Carbon',    'FESI': 'FA1070 - FeSi',
        'HCMN': 'FA1010 - H.C. Fe-Mn','LCMN': 'FA1030 - L.C. Fe-Mn',
        'HCCR': 'FA1090 - H.C. Fe-Cr','LCCR': 'FA1100 - L.C. Fe-Cr',
        'NI':   'FA1120 - Nickel',    'FEMO': 'FA1140 - Fe-Mo',
        'CU':   'FA1105 - Copper',    'FEP':  'FA1220 - FeP',
    }

    total_add_kg   = 0.0
    alloy_rows_out = []
    for item in addition_items:
        mat     = db.get_material(item['code'])
        planned = float(item.get('planned', 0))
        trim    = float(item.get('trim', 0))
        total   = planned + trim
        if mat and total > 0:
            total_add_kg += total
            for el in ELEMENTS:
                chem_kg[el] += (mat.get(el, 0) or 0) / 100 * total
            alloy_rows_out.append({
                'description': alloy_name_map.get(item['code'], mat.get('description', item['code'])),
                'code': item['code'], 'planned': planned, 'trim': trim, 'total': total,
            })

    final_wt   = (total_charge_kg + total_add_kg) or 1
    final_pct  = {el: round(chem_kg[el] / final_wt * 100, 4) for el in ELEMENTS}
    comparison = _compare(grade, final_pct)
    ladle_adds = _ladle_additions(grade, tap_weight)
    n_taps     = max(1, min(3, len(tap_splits))) if tap_splits else 1
    tap_type   = {1: 'Single Tap', 2: 'Double Tap', 3: 'Triple Tap'}[n_taps]

    # Temperature nomenclature:
    # User enters "Pour Temperature" in the UI
    # Report shows "Pour Temp" = what user entered (+ 30 if argon, already in pour_temp)
    # Report shows "Tap Temp"  = pour_temp - 50  (tap happens before pour)
    pour_temp = float(heat_info.get('pour_temp', heat_info.get('tap_temp', 1550)))
    heat_info['pour_temp']     = pour_temp
    heat_info['tap_temp_calc'] = pour_temp - 50   # tap temp = pour - 50

    report_data = {
        'tap_type': tap_type, 'n_taps': n_taps, 'tap_splits': tap_splits,
        'heat_info': heat_info, 'grade': grade, 'grade_code': grade_code,
        'grade_description': grade.get('description', ''),
        'tap_weight': tap_weight, 'total_tonnes': round(tap_weight / 1000, 3),
        'aim_chemistry':     {el: grade.get(el, 0) for el in ELEMENTS},
        'planned_chemistry': final_pct,
        'comparison':        comparison,
        'charge_rows':       charge_rows_out,
        'total_charge_kg':   round(total_charge_kg, 2),
        'alloy_additions':   alloy_rows_out,
        'total_add_kg':      round(total_add_kg, 2),
        'total_combined_kg': round(total_charge_kg + total_add_kg, 2),
        'ladle_additions':   ladle_adds,
    }

    token = str(uuid.uuid4())
    _report_tokens[token] = report_data
    return jsonify({'token': token})




# ── API: Dilution calculation ─────────────────────────────────────────────────

@app.route('/api/dilution', methods=['POST'])
def api_dilution():
    """
    Carbon dilution calculation using mass balance.

    When C is too high after spectro, calculate:
      1. How much high-C metal to remove (dump/pig)
      2. What low-C diluent to add back
      3. Any alloy additions to restore elements lost in the dump

    Mass balance: M_init * C_init + M_added * C_added - M_removed * C_removed
                  = M_final * C_target

    Payload:
      grade_code   – target grade
      furnace_kg   – current furnace weight (kg)
      current_pct  – {C, Si, Mn, Cr, Ni, Mo, Cu, S, P} spectro readings
      diluent_code – material code of the diluent to add (e.g. FS1045 pure iron)
      method       – 'remove_replace' | 'add_only'
    """
    data          = request.json
    grade_code    = data.get('grade_code')
    furnace_kg    = float(data.get('furnace_kg', 0))
    current_pct   = data.get('current_pct', {})
    diluent_code  = data.get('diluent_code', 'FS1045')   # default: pure iron briquettes
    method        = data.get('method', 'remove_replace')

    grade = db.get_grade((grade_code or '').strip())
    if not grade:
        return jsonify({'error': f'Grade not found: {grade_code!r}'}), 400
    if furnace_kg <= 0:
        return jsonify({'error': 'furnace_kg must be > 0'}), 400

    diluent = db.get_material(diluent_code)
    if not diluent:
        return jsonify({'error': f'Diluent material not found: {diluent_code!r}'}), 400

    # Determine which element to dilute (default C, but can be any)
    target_element = data.get('target_element', 'C')
    C_current = float(current_pct.get(target_element, 0))
    C_target  = float(grade.get(target_element, 0))
    C_diluent = float(diluent.get(target_element, 0))
    el_label  = target_element

    if C_current <= C_target:
        return jsonify({
            'needed': False,
            'message': f'{el_label} is already at or below target ({C_current:.3f}% ≤ {C_target:.3f}%). No dilution required.',
            'C_current': C_current,
            'C_target':  C_target,
        })

    steps = []
    result = {}

    if method == 'add_only':
        # Just add diluent without removing anything
        # M_init * C_init + M_add * C_add = (M_init + M_add) * C_target
        # M_add = M_init * (C_init - C_target) / (C_target - C_add)
        denom = C_target - C_diluent
        if denom <= 0:
            return jsonify({'error': 'Diluent carbon is >= target carbon. Choose a lower-carbon diluent.'}), 400

        kg_diluent = furnace_kg * (C_current - C_target) / denom
        final_wt   = furnace_kg + kg_diluent
        final_C    = (furnace_kg * C_current + kg_diluent * C_diluent) / final_wt

        steps = [
            f'Current: {furnace_kg:.0f} kg at {el_label}={C_current:.3f}%',
            f'Add {kg_diluent:.1f} kg of {diluent["description"]} ({el_label}={C_diluent:.3f}%)',
            f'Final: {final_wt:.0f} kg at {el_label}={final_C:.3f}% (target {C_target:.3f}%)',
        ]
        result = {
            'method':        'add_only',
            'kg_remove':     0,
            'kg_diluent':    round(kg_diluent, 1),
            'final_wt':      round(final_wt, 1),
            'final_C':       round(final_C, 4),
            'C_reduction':   round(C_current - final_C, 4),
        }

    else:  # remove_replace — remove high-C, replace with diluent
        # Solve: remove X kg of current melt, add X kg of diluent
        # (M - X)*C_init + X*C_dil = M * C_target
        # X*(C_init - C_dil) = M*(C_init - C_target)
        # X = M * (C_init - C_target) / (C_init - C_dil)
        denom = C_current - C_diluent
        if denom <= 0:
            return jsonify({'error': 'Diluent carbon >= current carbon. Choose a lower-carbon diluent.'}), 400

        kg_remove  = furnace_kg * (C_current - C_target) / denom
        kg_replace = kg_remove   # replace equal weight
        final_wt   = furnace_kg  # unchanged (remove + replace)
        final_C    = ((furnace_kg - kg_remove) * C_current + kg_replace * C_diluent) / final_wt

        steps = [
            f'Current: {furnace_kg:.0f} kg at {el_label}={C_current:.3f}%',
            f'Remove {kg_remove:.1f} kg of current melt ({el_label}={C_current:.3f}%)',
            f'Replace with {kg_replace:.1f} kg of {diluent["description"]} ({el_label}={C_diluent:.3f}%)',
            f'Final: {final_wt:.0f} kg at {el_label}={final_C:.3f}% (target {C_target:.3f}%)',
        ]
        result = {
            'method':        'remove_replace',
            'kg_remove':     round(kg_remove, 1),
            'kg_diluent':    round(kg_replace, 1),
            'final_wt':      round(final_wt, 1),
            'final_C':       round(final_C, 4),
            'C_reduction':   round(C_current - final_C, 4),
        }

    # After dilution — compute projected composition for all elements
    # Then check which other elements are now low and need topping up
    proj_chem_kg = {}
    for el in ELEMENTS:
        c_el = float(current_pct.get(el, 0)) / 100
        if result['method'] == 'remove_replace':
            # remove portion + add diluent
            kg_rem  = result['kg_remove']
            kg_dil  = result['kg_diluent']
            proj_chem_kg[el] = (
                (furnace_kg - kg_rem) * c_el * furnace_kg / furnace_kg  # remaining original
                + kg_dil * (diluent.get(el, 0) or 0) / 100             # from diluent
            )
            # simplified: (furnace - rem)/furnace * original_kg + diluent contrib
            orig_kg = c_el * furnace_kg
            proj_chem_kg[el] = orig_kg * (furnace_kg - kg_rem) / furnace_kg                                 + kg_dil * (diluent.get(el, 0) or 0) / 100
        else:
            orig_kg = c_el * furnace_kg
            proj_chem_kg[el] = orig_kg + result['kg_diluent'] * (diluent.get(el, 0) or 0) / 100

    proj_pct = {el: round(proj_chem_kg[el] / result['final_wt'] * 100, 4) for el in ELEMENTS}
    comparison = _compare(grade, proj_pct)

    # Recovery additions: elements now below aim after dilution
    recovery = []
    for el, (code, alloy_pct) in ALLOY_MAP.items():
        aim  = grade.get(el, 0) or 0
        if aim <= 0:
            continue
        have = proj_pct.get(el, 0)
        deficit = aim - have
        if deficit > 0.005:
            kg_needed = (deficit / 100 * result['final_wt']) / (alloy_pct / 100)
            mat = db.get_material(code)
            recovery.append({
                'element':      el,
                'aim':          round(aim, 4),
                'after_dilution': round(have, 4),
                'deficit':      round(deficit, 4),
                'addition_code':code,
                'addition_desc':mat['description'] if mat else code,
                'addition_kg':  round(kg_needed, 2),
                'cost':         round((mat.get('cost', 0) or 0) * kg_needed, 2) if mat else 0,
            })

    return jsonify({
        'needed':         True,
        'target_element': el_label,
        'C_current':      C_current,
        'C_target':       C_target,
        'C_excess':       round(C_current - C_target, 4),
        'diluent':      {'code': diluent_code, 'description': diluent['description'], 'C': C_diluent},
        'result':       result,
        'steps':        steps,
        'proj_pct':     proj_pct,
        'comparison':   comparison,
        'recovery_additions': recovery,
        'total_recovery_cost': round(sum(r['cost'] for r in recovery), 2),
    })


# ── API: Heat no uniqueness check ───────────────────────────────────────────

@app.route('/api/furnace_monitor', methods=['GET'])
def api_furnace_monitor():
    """Return cumulative tap weight per furnace and alert thresholds."""
    heats = db.get_heats()
    totals = {}
    for h in heats:
        fn  = h.get('furnace_no', '') or 'Unknown'
        wt  = float(h.get('tap_wt', 0) or 0)
        totals[fn] = totals.get(fn, 0) + wt
    result = []
    for fn, total_kg in sorted(totals.items()):
        total_t = total_kg / 1000
        result.append({
            'furnace':  fn,
            'total_kg': round(total_kg, 1),
            'total_t':  round(total_t, 2),
            'alert':    total_t >= 180,
            'critical': total_t >= 195,
        })
    return jsonify(result)


# ── API: Save PDF (heat report) ───────────────────────────────────────────────

@app.route('/api/save_heat_pdf', methods=['POST'])
def api_save_heat_pdf():
    """Render the prepared report as PDF and save to heat_pdf/ folder."""
    try:
        from weasyprint import HTML as WPHTML
        import os, uuid

        data      = request.json
        html_body = data.get('html', '')
        heat_no   = data.get('heat_no', 'heat_' + str(uuid.uuid4())[:8])

        # Sanitise filename
        safe_name = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in heat_no)
        folder    = os.path.join(os.path.dirname(__file__), 'heat_pdf')
        os.makedirs(folder, exist_ok=True)
        path      = os.path.join(folder, f'{safe_name}.pdf')

        # Full HTML page with print CSS embedded
        full_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family: Arial, sans-serif; font-size:9pt; color:#000; }}
  @page {{ size: A4 portrait; margin: 8mm 10mm; }}
</style>
</head><body>{html_body}</body></html>"""

        WPHTML(string=full_html).write_pdf(path)
        return jsonify({'status': 'saved', 'path': path, 'filename': f'{safe_name}.pdf'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── API: Save PDF (trim report) ───────────────────────────────────────────────

@app.route('/api/save_trim_pdf', methods=['POST'])
def api_save_trim_pdf():
    """Render trim correction report as PDF and save to trim_pdf/ folder."""
    try:
        from weasyprint import HTML as WPHTML
        import os, uuid

        data      = request.json
        html_body = data.get('html', '')
        heat_no   = data.get('heat_no', 'trim_' + str(uuid.uuid4())[:8])

        safe_name = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in heat_no) + '_TRIM'
        folder    = os.path.join(os.path.dirname(__file__), 'trim_pdf')
        os.makedirs(folder, exist_ok=True)
        path      = os.path.join(folder, f'{safe_name}.pdf')

        full_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family: Arial, sans-serif; font-size:9pt; color:#000; }}
  @page {{ size: A4 portrait; margin: 8mm 10mm; }}
</style>
</head><body>{html_body}</body></html>"""

        WPHTML(string=full_html).write_pdf(path)
        return jsonify({'status': 'saved', 'path': path, 'filename': f'{safe_name}.pdf'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── API: Grade management ─────────────────────────────────────────────────────

@app.route('/api/grades', methods=['POST'])
def api_add_grade():
    """Add or update a grade in metal_specs.csv."""
    data = request.json
    try:
        db.save_grade(data)
        db.clear_cache()
        return jsonify({'status': 'saved', 'code': data.get('code','')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/grades/<code>', methods=['PUT'])
def api_update_grade(code):
    """Update an existing grade."""
    data = request.json
    data['code'] = code
    try:
        db.save_grade(data, update=True)
        db.clear_cache()
        return jsonify({'status': 'updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/grades/<code>', methods=['DELETE'])
def api_delete_grade(code):
    """Delete a grade from metal_specs.csv."""
    try:
        db.delete_grade(code)
        db.clear_cache()
        return jsonify({'status': 'deleted'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── API: Addition specs management ───────────────────────────────────────────

@app.route('/api/materials', methods=['POST'])
def api_add_material():
    """Add a new material/alloy/scrap to addition_specs.csv."""
    data = request.json
    try:
        db.save_material(data)
        db.clear_cache()
        return jsonify({'status': 'saved', 'code': data.get('code', '')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/materials/<code>', methods=['PUT'])
def api_update_material(code):
    data = request.json
    data['code'] = code
    try:
        db.save_material(data, update=True)
        db.clear_cache()
        return jsonify({'status': 'updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/materials/<code>', methods=['DELETE'])
def api_delete_material(code):
    try:
        db.delete_material(code)
        db.clear_cache()
        return jsonify({'status': 'deleted'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── API: Heat uniqueness check ───────────────────────────────────────────────

@app.route('/api/save_pdf', methods=['POST'])
def api_save_pdf():
    """Generate a PDF from report data and save to heat_pdf/ or trim_pdf/."""
    data      = request.json
    pdf_type  = data.get('type', 'heat')   # 'heat' or 'trim'
    heat_no   = data.get('heat_no', 'unknown').replace('/', '-').replace('\\', '-')
    folder    = 'heat_pdf' if pdf_type == 'heat' else 'trim_pdf'
    
    os.makedirs(folder, exist_ok=True)
    filename  = f"{folder}/{heat_no}_{pdf_type}.pdf"
    
    _generate_pdf(data, filename, pdf_type)
    
    return jsonify({'status': 'saved', 'file': filename})


@app.route('/api/download_pdf', methods=['POST'])
def api_download_pdf():
    """Generate PDF and stream it as a download."""
    data     = request.json
    pdf_type = data.get('type', 'heat')
    heat_no  = data.get('heat_no', 'unknown').replace('/', '-').replace('\\', '-')
    folder   = 'heat_pdf' if pdf_type == 'heat' else 'trim_pdf'
    
    os.makedirs(folder, exist_ok=True)
    filename = f"{folder}/{heat_no}_{pdf_type}.pdf"
    _generate_pdf(data, filename, pdf_type)
    
    return send_file(filename, as_attachment=True,
                     download_name=f"{heat_no}_{pdf_type}.pdf",
                     mimetype='application/pdf')


def _generate_pdf(data, filepath, pdf_type):
    """Generate a PDF report using ReportLab."""
    doc  = SimpleDocTemplate(filepath, pagesize=A4,
                              leftMargin=15*mm, rightMargin=15*mm,
                              topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'],
                                  fontSize=14, spaceAfter=4, textColor=colors.HexColor('#1a1d23'))
    sub_style   = ParagraphStyle('Sub', parent=styles['Normal'],
                                  fontSize=9, textColor=colors.HexColor('#555555'), spaceAfter=6)
    h2_style    = ParagraphStyle('H2', parent=styles['Heading2'],
                                  fontSize=10, spaceBefore=8, spaceAfter=4,
                                  textColor=colors.white,
                                  backColor=colors.HexColor('#1a1d23'),
                                  leftIndent=-2, rightIndent=-2)
    body_style  = ParagraphStyle('Body', parent=styles['Normal'], fontSize=8.5)
    
    hi   = data.get('heat_info', {})
    CHEM = ['C', 'Si', 'Mn', 'Cr', 'Ni', 'Mo', 'Cu', 'P']
    
    def tbl(rows, col_widths=None, header=True):
        t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
        style = [
            ('FONTSIZE',    (0,0), (-1,-1), 8),
            ('GRID',        (0,0), (-1,-1), 0.3, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f8f8')]),
            ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING',  (0,0), (-1,-1), 3),
            ('BOTTOMPADDING',(0,0),(-1,-1), 3),
        ]
        if header:
            style += [
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e8e8e8')),
                ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ]
        t.setStyle(TableStyle(style))
        return t

    story = []
    
    if pdf_type == 'heat':
        story.append(Paragraph('FURNACE CHARGE CALCULATOR', title_style))
        n_taps = data.get('n_taps', 1)
        tap_label = {1:'Single Tap',2:'Double Tap',3:'Triple Tap'}.get(n_taps,'Single Tap')
        story.append(Paragraph(
            f"{tap_label}  |  {data.get('grade_description','')} ({data.get('grade_code','')})  |  {data.get('total_tonnes',0)} t",
            sub_style))
        
        # Header info table
        story.append(tbl([
            ['Heat No.', hi.get('heat_no',''), 'Date', hi.get('melt_date',''), 'Furnace', hi.get('furnace_no','')],
            ['Grade', f"{data.get('grade_description','')} ({data.get('grade_code','')})",
             'Tap Weight', f"{data.get('tap_weight',0):,} kg",
             'Operator', hi.get('operator','')],
            ['Pour Temp', f"{hi.get('report_tap_temp', hi.get('tap_temp',''))} °C",
             'Tap Temp', f"{(hi.get('report_tap_temp', hi.get('tap_temp',0) or 0) or 0) + 50} °C",
             'Ladle', hi.get('ladle','')],
        ], col_widths=[22*mm,45*mm,22*mm,40*mm,22*mm,38*mm], header=False))
        story.append(Spacer(1, 4*mm))
        
        # Chemistry
        story.append(Paragraph('CHEMISTRY', h2_style))
        chem_rows = [[''] + CHEM]
        aim   = data.get('aim_chemistry', {})
        plan  = data.get('planned_chemistry', {})
        chem_rows.append(['Aim %']   + [f"{aim.get(e,0):.3f}" if aim.get(e,0) else '—' for e in CHEM])
        chem_rows.append(['Planned %'] + [f"{plan.get(e,0):.3f}" if plan.get(e,0) else '—' for e in CHEM])
        chem_rows.append(['Spectro %'] + ['____'] * len(CHEM))
        story.append(tbl(chem_rows, col_widths=[22*mm] + [19*mm]*len(CHEM)))
        story.append(Spacer(1, 4*mm))
        
        # Charge + additions
        story.append(Paragraph('BASE CHARGE MATERIALS (kg)', h2_style))
        charge_rows = [['Material', 'Planned', 'Actual', 'Total']]
        for r in data.get('charge_rows', []):
            charge_rows.append([r['description'], f"{r['planned']:.1f}", '', f"{r['total']:.1f}"])
        charge_rows.append(['Total Base Charge', f"{data.get('total_charge_kg',0):.1f}", '', f"{data.get('total_charge_kg',0):.1f}"])
        story.append(tbl(charge_rows, col_widths=[90*mm, 33*mm, 33*mm, 33*mm]))
        story.append(Spacer(1, 4*mm))
        
        story.append(Paragraph('ALLOY ADDITIONS (kg)', h2_style))
        add_rows = [['Addition', 'Planned', 'Trim', 'Total']]
        for a in data.get('alloy_additions', []):
            add_rows.append([a['description'], f"{a['planned']:.2f}", f"{a['trim']:.2f}", f"{a['total']:.2f}"])
        add_rows.append(['Total Additions', f"{data.get('total_add_kg',0):.2f}", '', f"{data.get('total_add_kg',0):.2f}"])
        add_rows.append([f"TOTAL CHARGE (Base + Additions)", '', '', f"{data.get('total_combined_kg',0):.2f} kg"])
        story.append(tbl(add_rows, col_widths=[90*mm, 33*mm, 33*mm, 33*mm]))
        story.append(Spacer(1, 4*mm))
        
        # Ladle additions
        ladle = data.get('ladle_additions', [])
        if ladle:
            story.append(Paragraph('DEOXIDATION & LADLE ADDITIONS', h2_style))
            la_rows = [['Additive', 'FA Code', 'Location', 'Rate (kg/t)', 'Qty (kg)', 'Actual']]
            for a in ladle:
                la_rows.append([a['name'], a['fa_code'], a['location'].upper(),
                                 f"{a['rate_kg_per_tonne']:.3f}", f"{a['kg']:.3f}", ''])
            story.append(tbl(la_rows, col_widths=[55*mm,20*mm,20*mm,25*mm,25*mm,44*mm]))
            story.append(Spacer(1, 4*mm))
        
        # Ops block
        story.append(Paragraph('FURNACE OPERATOR', h2_style))
        story.append(tbl([
            ['Operator', hi.get('operator',''), 'Power On', '', 'am/pm', ''],
            ['Date', hi.get('melt_date',''), 'Power Off', '', 'am/pm', ''],
            ['START kW', '', 'END kW', '', 'Tap Finish', ''],
            ['Actual Pour Temp (°C)', '', 'Actual Tap Wt (kg)', '', 'Pigged (kg)', ''],
            ['Total Charge Planned (kg)', f"{data.get('total_combined_kg',0):.2f}", 'Earth Fault', '', 'Ladle', hi.get('ladle','')],
        ], col_widths=[45*mm,40*mm,32*mm,25*mm,22*mm,25*mm], header=False))

    else:  # trim report
        story.append(Paragraph('TRIM CORRECTION REPORT', title_style))
        story.append(Paragraph(
            f"Grade: {data.get('grade_description','')} ({data.get('grade_code','')})  |  Furnace: {data.get('furnace_no','')}  |  Date: {data.get('date','')}",
            sub_style))
        
        # Spectro actuals
        story.append(Paragraph('SPECTRO ACTUALS (%)', h2_style))
        sp = data.get('spectro', {})
        CHEM8 = ['C','Si','Mn','Cr','Ni','Mo','Cu','P']
        story.append(tbl(
            [CHEM8, [f"{sp.get(e,0):.3f}" for e in CHEM8]],
            col_widths=[24*mm]*len(CHEM8)
        ))
        story.append(Spacer(1, 4*mm))
        
        # Trim additions
        story.append(Paragraph('TRIM ADDITIONS REQUIRED', h2_style))
        trim = data.get('trim_needed', [])
        if not trim:
            story.append(Paragraph('✓ No trim additions required — composition within aim.', body_style))
        else:
            trim_rows = [['Element', 'Aim (%)', 'Actual (%)', 'Deficit (%)', 'Addition', 'Qty (kg)', 'Cost ($)']]
            for t in trim:
                trim_rows.append([t['element'], f"{t['aim']:.3f}", f"{t['actual']:.3f}",
                                   f"{t['deficit']:.3f}", t['addition_desc'],
                                   f"{t['addition_kg']:.2f}", f"${t['cost']:.2f}"])
            trim_rows.append(['', '', '', '', 'Total',
                               f"{data.get('total_trim_kg',0):.2f} kg",
                               f"${data.get('total_trim_cost',0):.2f}"])
            story.append(tbl(trim_rows, col_widths=[18*mm,18*mm,18*mm,18*mm,60*mm,25*mm,25*mm]))
        story.append(Spacer(1, 4*mm))
        
        # Projected composition
        story.append(Paragraph('PROJECTED COMPOSITION AFTER TRIM (%)', h2_style))
        proj = data.get('projected_pct', {})
        cmp  = data.get('comparison', {})
        story.append(tbl(
            [CHEM8,
             [f"{proj.get(e,0):.3f}" for e in CHEM8],
             [('✓' if (cmp.get(e,{}).get('status')=='ok') else '⚠') for e in CHEM8]],
            col_widths=[24*mm]*len(CHEM8)
        ))
        story.append(Spacer(1, 4*mm))
        
        # Ladle additions
        ladle = data.get('ladle_additions', [])
        if ladle:
            story.append(Paragraph('LADLE & DEOXIDATION ADDITIONS', h2_style))
            la_rows = [['Additive', 'FA Code', 'Location', 'Rate (kg/t)', 'Qty (kg)', 'Actual']]
            for a in ladle:
                la_rows.append([a['name'], a['fa_code'], a['location'].upper(),
                                 f"{a['rate_kg_per_tonne']:.3f}", f"{a['kg']:.3f}", ''])
            story.append(tbl(la_rows, col_widths=[55*mm,20*mm,20*mm,25*mm,25*mm,44*mm]))
    
    doc.build(story)



if __name__ == '__main__':
    print("Starting Furnace Charge Calculator...")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000)

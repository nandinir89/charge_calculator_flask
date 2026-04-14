"""
db.py — CSV-backed database for the Furnace Charge Calculator.

Files used  (all inside  data/  folder):
  metal_specs.csv     → grade aim chemistry + ladle deox rates  (read)
  addition_specs.csv  → scrap & alloy compositions + cost       (read)
  heat_log.csv        → heat record log                         (read + append)

No Excel / openpyxl dependency — plain CSV that can be opened in any spreadsheet.
"""

import csv
import os
from pathlib import Path
from datetime import datetime

ELEMENTS = ['C', 'Si', 'Mn', 'S', 'P', 'Cr', 'Ni', 'Mo', 'Cu']

# ── Path helpers ──────────────────────────────────────────────────────────────

def _data_dir():
    """Resolve  data/  folder next to db.py regardless of cwd."""
    return Path(__file__).parent / 'data'

def _path(filename):
    return _data_dir() / filename

def _mtime(filename):
    try:
        return _path(filename).stat().st_mtime
    except OSError:
        return None

def _sf(v, default=0.0):
    """Safe float conversion."""
    try:
        return float(v) if v not in (None, '', 'None') else default
    except (TypeError, ValueError):
        return default

def _ss(v):
    return str(v).strip() if v not in (None, '', 'None') else ''


# ── ExcelDB (now really a CsvDB — name kept for compatibility) ─────────────

class ExcelDB:

    def __init__(self, _legacy_path=None):
        """_legacy_path is ignored — we always use data/ folder."""
        self._grades_cache    = None
        self._materials_cache = None
        self._grades_mtime    = None
        self._materials_mtime = None
        # Create data dir if missing
        _data_dir().mkdir(exist_ok=True)

    # ── Cache helpers ─────────────────────────────────────────────────────

    def clear_cache(self):
        self._grades_cache    = None
        self._materials_cache = None
        self._grades_mtime    = None
        self._materials_mtime = None

    # ── Grades (metal_specs.csv) ──────────────────────────────────────────

    def get_grades(self):
        mtime = _mtime('metal_specs.csv')
        if self._grades_cache is not None and self._grades_mtime == mtime:
            return self._grades_cache

        grades = []
        csv_path = _path('metal_specs.csv')
        if not csv_path.exists():
            self._grades_cache = grades
            return grades

        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Row layout (0-indexed):
        #   rows[0..3] = headers/deox-labels
        #   rows[4]    = column names: Description, Code, C_Aim, Si_Aim …
        #   rows[5+]   = data
        # We detect the data start by finding the row that has 'Description' in col 0

        data_start = 5
        for i, row in enumerate(rows):
            if row and _ss(row[0]) == 'Description':
                data_start = i + 1
                break

        for row in rows[data_start:]:
            if len(row) < 13:
                continue
            desc = _ss(row[0])
            code = _ss(row[1])
            if not desc or not code:
                continue
            # Keep named placeholder grades; skip truly empty rows
            vals = [_sf(row[i]) for i in range(2, 11)]
            if not desc and all(v == 0 for v in vals):
                continue
            def _gc(c): return _sf(row[c]) if len(row) > c else 0.0
            entry = {
                'description': desc,
                'code':   code,
                'C':  _sf(row[2]),  'Si': _sf(row[3]),
                'Mn': _sf(row[4]),  'S':  _sf(row[5]),
                'P':  _sf(row[6]),  'Cr': _sf(row[7]),
                'Ni': _sf(row[8]),  'Mo': _sf(row[9]),
                'Cu': _sf(row[10]), 'Al': _sf(row[11]),
                'V':  _sf(row[12]),
                # Deox/inoculant cols 14-26
                'Al_deox':  _gc(14), 'Al_ladle': _gc(15),
                'Hypercal': _gc(16), 'FeSe':     _gc(17),
                'CaSiMn':   _gc(18), 'FeSiZr':   _gc(19),
                'FeTi':     _gc(20), 'FeB':       _gc(21),
                'Al_ladle2':_gc(22),
                'MgFeSi':   _gc(23),  # Nodulariser FA1011 (SG grades)
                'Barinoc':  _gc(24),  # Inoculant   FA1070 (SG grades)
                'Superseed':_gc(25),  # Inoculant   FA1197 (iron grades)
                'FeTi2':    _gc(26),
            }
            grades.append(entry)

        self._grades_cache = grades
        self._grades_mtime = mtime
        return grades

    def get_grade(self, code: str):
        if not code:
            return None
        # Normalise: strip whitespace, try exact match then zero-padded
        code = code.strip()
        grades = self.get_grades()
        # Exact match first
        match = next((g for g in grades if g['code'] == code), None)
        if match:
            return match
        # Try zero-padded 3-digit (e.g. '77' → '077')
        try:
            padded = str(int(code)).zfill(3)
            match = next((g for g in grades if g['code'] == padded), None)
            if match:
                return match
        except ValueError:
            pass
        return None

    # ── Materials (addition_specs.csv) ────────────────────────────────────

    def get_materials(self):
        mtime = _mtime('addition_specs.csv')
        if self._materials_cache is not None and self._materials_mtime == mtime:
            return self._materials_cache

        materials = []
        csv_path = _path('addition_specs.csv')
        if not csv_path.exists():
            self._materials_cache = materials
            return materials

        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Row 0 = header: Description, Code, C %, Si %, Mn %, S%, P%, Cr %, Ni %, Mo %, Cu %, Cost $/Kg
        for row in rows[1:]:
            if len(row) < 2:
                continue
            desc = _ss(row[0])
            code = _ss(row[1])
            if not code or code in ('Code', '0', ''):
                continue

            # Determine category
            if code.startswith('FS') or code in ('HEEL','SiW1','SiW2','SiW3','SiW4','I600'):
                category = 'scrap'
            elif code in ('GRAF','FESI','HCMN','LCMN','HCCR','LCCR','NI','FEMO','CU','SIMN','FEP'):
                category = 'alloy'
            else:
                category = 'grade_return'

            cost_raw = row[11] if len(row) > 11 else ''
            try:
                cost = float(cost_raw) if cost_raw.strip() else 0.0
            except (ValueError, AttributeError):
                cost = 0.0

            materials.append({
                'description': desc or code,
                'code':     code,
                'category': category,
                'C':  _sf(row[2]  if len(row) > 2  else 0),
                'Si': _sf(row[3]  if len(row) > 3  else 0),
                'Mn': _sf(row[4]  if len(row) > 4  else 0),
                'S':  _sf(row[5]  if len(row) > 5  else 0),
                'P':  _sf(row[6]  if len(row) > 6  else 0),
                'Cr': _sf(row[7]  if len(row) > 7  else 0),
                'Ni': _sf(row[8]  if len(row) > 8  else 0),
                'Mo': _sf(row[9]  if len(row) > 9  else 0),
                'Cu': _sf(row[10] if len(row) > 10 else 0),
                'cost': cost,
            })

        self._materials_cache = materials
        self._materials_mtime = mtime
        return materials

    def get_material(self, code: str):
        if not code:
            return None
        code = code.strip()
        return next((m for m in self.get_materials() if m['code'] == code), None)

    def get_scraps(self):
        return [m for m in self.get_materials() if m['category'] in ('scrap','grade_return')]

    def get_alloys(self):
        return [m for m in self.get_materials() if m['category'] == 'alloy']

    # ── Heat log (heat_log.csv) ───────────────────────────────────────────

    def get_heats(self):
        csv_path = _path('heat_log.csv')
        if not csv_path.exists():
            return []

        heats = []
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                heat_no = _ss(row.get('Heat No.',''))
                if not heat_no:
                    continue
                # tap_wt: prefer 'Tap Wt' column, fall back to 'Melt Wt. (kg)'
                tap_wt_val = _sf(row.get('Tap Wt', 0)) or _sf(row.get('Melt Wt. (kg)', 0))
                heats.append({
                    'melt_date':  _ss(row.get('Melt Date','')),
                    'grade_name': _ss(row.get('Grade Name','')),
                    'grade_code': _ss(row.get('Grade Code','')),
                    'mpn':        _ss(row.get('MPN','')),
                    'description':_ss(row.get('Description','')),
                    'furnace_no': _ss(row.get('F/c No.','')),
                    'heat_no':    heat_no,
                    'ladle':      _ss(row.get('Ladle','')),
                    'operator':   _ss(row.get('Operator','')),
                    'melt_wt':    _sf(row.get('Melt Wt. (kg)',0)),
                    'C':  _sf(row.get('C',0)),
                    'Si': _sf(row.get('Si',0)),
                    'Mn': _sf(row.get('Mn',0)),
                    'S':  _sf(row.get('S',0)),
                    'P':  _sf(row.get('P',0)),
                    'Cr': _sf(row.get('Cr',0)),
                    'Ni': _sf(row.get('Ni',0)),
                    'Mo': _sf(row.get('Mo',0)),
                    'Cu': _sf(row.get('Cu',0)),
                    'tap_temp': _sf(row.get('Tap Temperature',0)),
                    'tap_wt':   tap_wt_val,
                    'GRAF': _sf(row.get('GRAF',0)),
                    'FESI': _sf(row.get('FESI',0)),
                    'HCMN': _sf(row.get('HCMN',0)),
                    'LCMN': _sf(row.get('LCMN',0)),
                    'HCCR': _sf(row.get('HCCR',0)),
                    'LCCR': _sf(row.get('LCCR',0)),
                    'NI':   _sf(row.get('NI',0)),
                    'FEMO': _sf(row.get('FEMO',0)),
                    'CU':   _sf(row.get('CU',0)),
                })
        return heats

    def get_heat(self, heat_no: str):
        return next((h for h in self.get_heats() if h['heat_no'] == heat_no), None)

    def save_heat(self, data: dict):
        """Append a heat record to heat_log.csv."""
        csv_path = _path('heat_log.csv')
        # Read existing CSV headers so new rows are fully compatible
        _existing_headers = None
        if csv_path.exists():
            with open(csv_path, newline='', encoding='utf-8') as _f:
                _reader = csv.reader(_f)
                _first = next(_reader, None)
                if _first:
                    _existing_headers = _first

        fieldnames = _existing_headers or [
            'Melt Date','Grade Name','Grade Code','MPN','Description',
            'F/c No.','Heat No.','Ladle','Melt Wt. (kg)',
            'C','Si','Mn','S','P','Cr','Ni','Mo','Cu','Al',
            'Tap Temperature','Tap Wt','Pouring Temp','Pigged',
            'Heel Mat','Heel Wt.',
            'Scrap 1','S1 Wt','Scrap 2','S2 Wt','Scrap 3','S3 Wt','Scrap 4','S4 Wt',
            'GRAF','FESI','HCMN','LCMN','HCCR','LCCR','NI','FEMO','CU',
            'Aluminium','Ca-Si-Mn','Operator','Power on','Power off',
            'Start KW','END KW','Tap finish time',
        ]

        file_exists = csv_path.exists()
        with open(csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'Melt Date':    data.get('melt_date', datetime.now().strftime('%Y-%m-%d')),
                'Grade Name':   data.get('grade_name',''),
                'Grade Code':   data.get('grade_code',''),
                'MPN':          data.get('mpn',''),
                'Description':  data.get('description',''),
                'F/c No.':      data.get('furnace_no',''),
                'Heat No.':     data.get('heat_no',''),
                'Ladle':        data.get('ladle',''),
                'Melt Wt. (kg)':data.get('melt_wt',0),
                'C':  data.get('C',0),  'Si': data.get('Si',0),
                'Mn': data.get('Mn',0), 'S':  data.get('S',0),
                'P':  data.get('P',0),  'Cr': data.get('Cr',0),
                'Ni': data.get('Ni',0), 'Mo': data.get('Mo',0),
                'Cu': data.get('Cu',0), 'Al': data.get('Al',0),
                'Tap Temperature': data.get('tap_temp',0),
                'Tap Wt':          data.get('tap_wt',0),
                'Heel Mat':        data.get('heel_mat',''),
                'Heel Wt.':        data.get('heel_wt',0),
                'Scrap 1':  data.get('scrap_1_mat',''),  'S1 Wt': data.get('scrap_1_wt',0),
                'Scrap 2':  data.get('scrap_2_mat',''),  'S2 Wt': data.get('scrap_2_wt',0),
                'Scrap 3':  data.get('scrap_3_mat',''),  'S3 Wt': data.get('scrap_3_wt',0),
                'Scrap 4':  data.get('scrap_4_mat',''),  'S4 Wt': data.get('scrap_4_wt',0),
                'GRAF': data.get('GRAF',0), 'FESI': data.get('FESI',0),
                'HCMN': data.get('HCMN',0), 'LCMN': data.get('LCMN',0),
                'HCCR': data.get('HCCR',0), 'LCCR': data.get('LCCR',0),
                'NI':   data.get('NI',0),   'FEMO': data.get('FEMO',0),
                'CU':   data.get('CU',0),
                'Aluminium': data.get('Aluminium',0),
                'Ca-Si-Mn':  data.get('Ca-Si-Mn',0),
                'Operator':  data.get('operator',''),
            })


    # ── Trim log (trim_log.csv) ───────────────────────────────────────────────

    def get_trims(self, heat_no: str = None):
        """Return all trim records, optionally filtered by heat_no (FK)."""
        csv_path = _path('trim_log.csv')
        if not csv_path.exists():
            return []

        trims = []
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trim_id = _ss(row.get('Trim ID', ''))
                if not trim_id:
                    continue
                # Filter by heat_no if requested
                if heat_no and _ss(row.get('Heat No.', '')) != heat_no:
                    continue
                rec = {
                    'trim_id':    trim_id,
                    'heat_no':    _ss(row.get('Heat No.', '')),
                    'trim_date':  _ss(row.get('Trim Date', '')),
                    'grade_code': _ss(row.get('Grade Code', '')),
                    'grade_name': _ss(row.get('Grade Name', '')),
                    'furnace_no': _ss(row.get('Furnace No.', '')),
                    'furnace_kg': _sf(row.get('Furnace Wt (kg)', 0)),
                    'operator':   _ss(row.get('Operator', '')),
                    # Spectro actuals
                    'spec_C':  _sf(row.get('Spectro C', 0)),
                    'spec_Si': _sf(row.get('Spectro Si', 0)),
                    'spec_Mn': _sf(row.get('Spectro Mn', 0)),
                    'spec_Cr': _sf(row.get('Spectro Cr', 0)),
                    'spec_Ni': _sf(row.get('Spectro Ni', 0)),
                    'spec_Mo': _sf(row.get('Spectro Mo', 0)),
                    'spec_Cu': _sf(row.get('Spectro Cu', 0)),
                    'spec_S':  _sf(row.get('Spectro S', 0)),
                    'spec_P':  _sf(row.get('Spectro P', 0)),
                    # Projected after trim
                    'proj_C':  _sf(row.get('Proj C', 0)),
                    'proj_Si': _sf(row.get('Proj Si', 0)),
                    'proj_Mn': _sf(row.get('Proj Mn', 0)),
                    'proj_Cr': _sf(row.get('Proj Cr', 0)),
                    'proj_Ni': _sf(row.get('Proj Ni', 0)),
                    'proj_Mo': _sf(row.get('Proj Mo', 0)),
                    # Additions made
                    'total_trim_kg':   _sf(row.get('Total Trim Kg', 0)),
                    'total_trim_cost': _sf(row.get('Total Trim Cost', 0)),
                    'trim_additions':  _ss(row.get('Trim Additions', '')),
                    'status':          _ss(row.get('Status', 'saved')),
                }
                trims.append(rec)
        return trims

    def save_trim(self, data: dict):
        """Append a trim record to trim_log.csv."""
        csv_path = _path('trim_log.csv')
        fieldnames = [
            'Trim ID', 'Heat No.', 'Trim Date', 'Grade Code', 'Grade Name',
            'Furnace No.', 'Furnace Wt (kg)', 'Operator',
            'Spectro C', 'Spectro Si', 'Spectro Mn', 'Spectro Cr',
            'Spectro Ni', 'Spectro Mo', 'Spectro Cu', 'Spectro S', 'Spectro P',
            'Proj C', 'Proj Si', 'Proj Mn', 'Proj Cr', 'Proj Ni', 'Proj Mo',
            'Total Trim Kg', 'Total Trim Cost', 'Trim Additions', 'Status',
        ]

        file_exists = csv_path.exists()
        # Auto-generate Trim ID: TRM-{YYYYMMDD}-{seq}
        seq = 1
        if file_exists:
            existing = self.get_trims()
            today = datetime.now().strftime('%Y%m%d')
            today_trims = [t for t in existing if t['trim_id'].startswith('TRM-' + today)]
            seq = len(today_trims) + 1

        trim_id = data.get('trim_id') or f'TRM-{datetime.now().strftime("%Y%m%d")}-{seq:03d}'

        with open(csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'Trim ID':        trim_id,
                'Heat No.':       data.get('heat_no', ''),
                'Trim Date':      data.get('trim_date', datetime.now().strftime('%Y-%m-%d')),
                'Grade Code':     data.get('grade_code', ''),
                'Grade Name':     data.get('grade_name', ''),
                'Furnace No.':    data.get('furnace_no', ''),
                'Furnace Wt (kg)':data.get('furnace_kg', 0),
                'Operator':       data.get('operator', ''),
                'Spectro C':  data.get('spec_C', 0),
                'Spectro Si': data.get('spec_Si', 0),
                'Spectro Mn': data.get('spec_Mn', 0),
                'Spectro Cr': data.get('spec_Cr', 0),
                'Spectro Ni': data.get('spec_Ni', 0),
                'Spectro Mo': data.get('spec_Mo', 0),
                'Spectro Cu': data.get('spec_Cu', 0),
                'Spectro S':  data.get('spec_S', 0),
                'Spectro P':  data.get('spec_P', 0),
                'Proj C':  data.get('proj_C', 0),
                'Proj Si': data.get('proj_Si', 0),
                'Proj Mn': data.get('proj_Mn', 0),
                'Proj Cr': data.get('proj_Cr', 0),
                'Proj Ni': data.get('proj_Ni', 0),
                'Proj Mo': data.get('proj_Mo', 0),
                'Total Trim Kg':   data.get('total_trim_kg', 0),
                'Total Trim Cost': data.get('total_trim_cost', 0),
                'Trim Additions':  data.get('trim_additions', ''),
                'Status':          data.get('status', 'saved'),
            })
        return trim_id

    # ── Material (addition specs) management ─────────────────────────────────

    def save_material(self, data: dict, update: bool = False):
        """Add or update a material row in addition_specs.csv."""
        csv_path = _path('addition_specs.csv')
        code = _ss(data.get('code', ''))
        if not code:
            raise ValueError('Material code is required')

        with open(csv_path, newline='', encoding='utf-8') as f:
            raw = list(csv.reader(f))

        # Row 0 = header
        def col(key, default=0.0):
            v = data.get(key, default)
            return str(v if v is not None else default)

        # Determine category from code prefix
        if str(code).startswith('FS') or code in ('HEEL','SiW1','SiW2','SiW3','SiW4'):
            cat_hint = 'scrap'
        elif code in ('GRAF','FESI','HCMN','LCMN','HCCR','LCCR','NI','FEMO','CU','SIMN','FEP'):
            cat_hint = 'alloy'
        else:
            cat_hint = data.get('category', 'scrap')

        new_row = [
            _ss(data.get('description', '')),  # 0 Description
            code,                              # 1 Code
            col('C'),   col('Si'),  col('Mn'), # 2-4
            col('S'),   col('P'),              # 5-6
            col('Cr'),  col('Ni'),  col('Mo'), # 7-9
            col('Cu'),                         # 10
            col('cost', 0),                    # 11 Cost $/kg
            '', '',                            # 12-13 (unused)
        ]

        if not update:
            for row in raw[1:]:
                if len(row) > 1 and _ss(row[1]) == code:
                    raise ValueError(f'Material code {code!r} already exists')
            raw.append(new_row)
        else:
            replaced = False
            for i, row in enumerate(raw[1:], 1):
                if len(row) > 1 and _ss(row[1]) == code:
                    raw[i] = new_row
                    replaced = True
                    break
            if not replaced:
                raise ValueError(f'Material code {code!r} not found for update')

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(raw)

    def delete_material(self, code: str):
        """Remove a material row from addition_specs.csv by code."""
        csv_path = _path('addition_specs.csv')
        code = code.strip()
        with open(csv_path, newline='', encoding='utf-8') as f:
            raw = list(csv.reader(f))
        new_raw = [raw[0]]   # keep header
        deleted = False
        for row in raw[1:]:
            if len(row) > 1 and _ss(row[1]) == code:
                deleted = True
            else:
                new_raw.append(row)
        if not deleted:
            raise ValueError(f'Material {code!r} not found')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(new_raw)

    # ── Grade management ──────────────────────────────────────────────────

    def save_grade(self, data: dict, update: bool = False):
        """
        Add or update a grade row in metal_specs.csv.
        The CSV has 4 header rows then a column-names row, then data rows.
        We append for add, or rewrite all rows for update.
        """
        csv_path = _path('metal_specs.csv')
        code = _ss(data.get('code', ''))
        if not code:
            raise ValueError('Grade code is required')

        with open(csv_path, newline='', encoding='utf-8') as f:
            raw = list(csv.reader(f))

        # Find data start row
        data_start = 5
        for i, row in enumerate(raw):
            if row and _ss(row[0]) == 'Description':
                data_start = i + 1
                break

        # Build new row (28 columns to match existing structure)
        def col(key, default=0.0): return str(data.get(key, default) or default)
        new_row = [
            _ss(data.get('description', '')),  # 0
            code,                              # 1
            col('C'), col('Si'), col('Mn'),    # 2-4
            col('S'), col('P'),                # 5-6
            col('Cr'), col('Ni'), col('Mo'),   # 7-9
            col('Cu'), col('Al'), col('V'),    # 10-12
            '0',                               # 13 Check
            col('Al_deox'), col('Al_ladle'),   # 14-15
            col('Hypercal'), col('FeSe'),      # 16-17
            col('CaSiMn'), col('FeSiZr'),      # 18-19
            col('FeTi'), col('FeB'),           # 20-21
            '0','0','0','0','0','',            # 22-27 (unused cols)
        ]

        if not update:
            # Check for duplicate code
            for row in raw[data_start:]:
                if len(row) > 1 and _ss(row[1]) == code:
                    raise ValueError(f'Grade code {code!r} already exists')
            raw.append(new_row)
        else:
            # Replace matching row
            replaced = False
            for i, row in enumerate(raw[data_start:], data_start):
                if len(row) > 1 and _ss(row[1]) == code:
                    raw[i] = new_row
                    replaced = True
                    break
            if not replaced:
                raise ValueError(f'Grade code {code!r} not found for update')

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(raw)

    def delete_grade(self, code: str):
        """Remove a grade row from metal_specs.csv by code."""
        csv_path = _path('metal_specs.csv')
        code = code.strip()

        with open(csv_path, newline='', encoding='utf-8') as f:
            raw = list(csv.reader(f))

        data_start = 5
        for i, row in enumerate(raw):
            if row and _ss(row[0]) == 'Description':
                data_start = i + 1
                break

        new_raw = []
        deleted = False
        for i, row in enumerate(raw):
            if i >= data_start and len(row) > 1 and _ss(row[1]) == code:
                deleted = True
                continue
            new_raw.append(row)

        if not deleted:
            raise ValueError(f'Grade {code!r} not found')

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(new_raw)


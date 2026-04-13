# Furnace Charge Calculator — Flask App

A web application for induction furnace charge calculation.
Uses plain CSV files as the database — no Excel install needed.

## Project structure

```
charge_app/
├── app.py                  ← Flask routes + calculation logic
├── db.py                   ← CSV read/write layer (no openpyxl)
├── desktop_app.py          ← Windows desktop launcher (pywebview)
├── desktop_app.spec        ← PyInstaller build config
├── build_windows.bat       ← One-click Windows .exe builder
├── requirements.txt
├── data/
│   ├── metal_specs.csv     ← Grade aim chemistry + deox rates  (EDIT HERE)
│   ├── addition_specs.csv  ← Scrap & alloy compositions + cost (EDIT HERE)
│   └── heat_log.csv        ← Saved heat records               (auto-appended)
├── templates/
│   ├── index.html
│   └── print_report.html
└── static/
    ├── css/style.css
    └── js/app.js
```

## Setup (web mode)

```bash
pip install flask
python app.py
# Open http://localhost:5000
```

## Build Windows .exe

```bash
# On a Windows machine:
build_windows.bat
# Output: dist\FurnaceCalc\FurnaceCalc.exe
```

## CSV Database

All data lives in the `data/` folder as plain CSV files.
Open them in Excel, LibreOffice, or Notepad to edit.

| File | Contents | Edit? |
|------|----------|-------|
| `metal_specs.csv` | 172 grade aim chemistries + ladle deox rates | ✅ Yes |
| `addition_specs.csv` | 276 scraps, alloys, costs | ✅ Yes |
| `heat_log.csv` | Saved heat records | Auto (app writes here) |

**To add a new grade:** open `metal_specs.csv`, add a row with the
grade description, code, and chemistry values in the correct columns.
Hit **⟳ Reload** in the app — changes appear immediately.

## API endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/grades` | All metal grades |
| GET | `/api/materials` | All scraps + alloys |
| POST | `/api/calculate` | Charge calculation |
| POST | `/api/trim_correction` | Post-spectro trim calc |
| GET | `/api/ladle_additions/<code>` | Ladle deox additions |
| POST | `/api/reload` | Clear cache, re-read CSVs |
| GET/POST | `/api/heats` | Heat log read/write |
| POST | `/api/prepare_report` | Prepare printable report |
| GET | `/print_report?token=…` | Render print report |

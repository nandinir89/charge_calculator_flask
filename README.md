# Furnace Charge Calculator

A web application for induction furnace charge calculation and heat management.

## Quick Start

```bash
pip install flask
python app.py
# Open http://localhost:5000
```

## Project Structure

```
charge_app/
├── index.html            ← Root copy for GitHub Pages
├── app.py                ← Flask server + all API routes
├── db.py                 ← CSV read/write layer
├── data/
│   ├── metal_specs.csv   ← 182 metal grades + ladle deox rates
│   ├── addition_specs.csv← 276 scraps & alloys + costs
│   ├── heat_log.csv      ← Saved heat records
│   └── reline_log.csv    ← Furnace relining records (auto-created)
├── templates/
│   ├── index.html        ← Main app (single page)
│   └── print_report.html ← Heat & trim print reports
├── static/
│   ├── css/style.css
│   └── js/app.js
├── heat_pdf/             ← Auto-saved heat reports (auto-created)
└── trim_pdf/             ← Auto-saved trim reports (auto-created)
```

## Features

| Feature | Description |
|---------|-------------|
| **Charge Calculator** | Grade selection, charge materials, alloy additions, chemistry tracking |
| **Print Report** | Single/Double/Triple tap, auto-saved to heat_pdf/ |
| **Trim Correction** | Post-spectro trim calc, ladle additions |
| **Trim Report** | Auto-saved to trim_pdf/ |
| **Carbon Dilution** | Any-element dilution calc with recovery additions |
| **Heat Log** | Searchable, clickable heat numbers load to calculator |
| **Furnace Monitor** | Per-furnace weight sum, 180T warning, 200T reline alert, ✓ Mark Relined button |
| **Grade Manager** | Add/edit/delete grades |
| **Materials Manager** | Add/edit/delete scraps & alloys |

## Temperature Logic

| Label | Value |
|-------|-------|
| **Pour Temperature** (UI input) | What the operator enters |
| **Pour Temp** (report) | = Pour entry + 30 if Argon purging |
| **Tap Temp** (report) | = Pour Temp + 50 |

## CSV Database

All data lives in `data/` as plain CSV — open in Excel or Notepad, hit ⟳ Reload.

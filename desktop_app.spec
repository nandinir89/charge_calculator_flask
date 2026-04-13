# desktop_app.spec
# -----------------
# PyInstaller build spec for Furnace Charge Calculator
#
# Usage:
#   pip install pyinstaller pywebview flask openpyxl
#   pyinstaller desktop_app.spec
#
# Output:  dist/FurnaceCalc/FurnaceCalc.exe  (folder mode)
#          dist/FurnaceCalc.exe              (single-file mode — slower startup)
#
# Folder mode is recommended — faster launch, easier to update database.xlsm

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Flask templates and static files
        ('templates',  'templates'),
        ('static',     'static'),
        # CSV database files (editable in any spreadsheet app)
        ('data',       'data'),
    ],
    hiddenimports=[
        # Flask internals
        'flask', 'jinja2', 'werkzeug', 'click',
        # CSV only - no openpyxl needed
        # pywebview backends (Windows)
        'webview', 'webview.platforms.winforms',
        'clr', 'System', 'System.Windows.Forms',
        # pywebview may also use EdgeChromium or IE
        'webview.platforms.edgechromium',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FurnaceCalc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',      # Uncomment and add icon.ico to use a custom icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FurnaceCalc',
)

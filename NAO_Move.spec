# NAO_Move.spec
# Fichier de compilation PyInstaller pour NAO Move
# Usage : pyinstaller NAO_Move.spec

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Icone embarquée
        ('scene-icon.ico', '.'),
        # Scripts annexes embarqués dans le .exe
        ('scene_idc.py', '.'),
        ('serveur_nao.py', '.'),
        # Dossier modules embarqué
        ('modules', 'modules'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'collections',
        'threading',
        'queue',
        'subprocess',
        'json',
        'socket',
        'math',
        'time',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NAO Move',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # Pas de fenêtre console
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='scene-icon.ico',
)

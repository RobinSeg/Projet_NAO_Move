@echo off
echo ========================================
echo    NAO Move - Installation et compilation
echo ========================================
echo.

:: Verification Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable. Installez Python 3 et relancez.
    pause
    exit /b 1
)

echo Python detecte :
python --version
echo.

:: Installation Pillow (affichage camera)
echo [1/3] Installation de Pillow...
pip install Pillow --quiet
if errorlevel 1 (
    echo [ERREUR] Impossible d'installer Pillow.
    pause
    exit /b 1
)
echo        Pillow OK.
echo.

:: Installation PyInstaller (compilation exe)
echo [2/3] Installation de PyInstaller...
pip install pyinstaller --quiet
if errorlevel 1 (
    echo [ERREUR] Impossible d'installer PyInstaller.
    pause
    exit /b 1
)
echo        PyInstaller OK.
echo.

:: Compilation
echo [3/3] Compilation de NAO Move.exe...
pyinstaller NAO_Move.spec --noconfirm
if errorlevel 1 (
    echo [ERREUR] La compilation a echoue. Verifiez les messages ci-dessus.
    pause
    exit /b 1
)
echo.
echo ========================================
echo    Compilation reussie !
echo    Votre .exe est dans : dist\NAO Move.exe
echo ========================================
echo.
echo NOTE : Pillow doit aussi etre installe sur
echo la machine cible pour afficher la camera.
echo (pip install Pillow)
echo.
pause

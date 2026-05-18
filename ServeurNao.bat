@echo off
echo =========================================
echo    NAO Move - Lancement de Choregraphe
echo =========================================
echo.

:: Chemin vers Choregraphe
set CHORE_EXE=C:\Program Files (x86)\Softbank Robotics\Choregraphe Suite 2.8\bin\choregraphe.exe

if not exist "%CHORE_EXE%" (
    echo [ERREUR] Choregraphe introuvable :
    echo %CHORE_EXE%
    echo.
    echo Verifiez le chemin d'installation de Choregraphe.
    pause
    exit /b 1
)

echo Lancement de Choregraphe avec le comportement serveur_nao...
start "" "%CHORE_EXE%" "%~dp0serveur_nao\serveur_nao.pml"

echo.
echo Attente du demarrage de Choregraphe...
timeout /t 8 >nul

echo.
echo ===============================================================
echo    Choregraphe lance !
echo    1. Connectez-vous au robot (ou simulation)
echo    2. Cliquez sur le bouton Play pour demarrer le serveur
echo ===============================================================
echo.
pause

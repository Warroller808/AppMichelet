@echo off
echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Starting worker...
celery -A AppMichelet worker --loglevel=INFO --pool=threads --concurrency=8

rem Vérifier le code de retour de la commande runserver
if errorlevel 1 (
    echo Error occurred. Press any key to exit...
    pause >nul
) else (
    echo Deactivating virtual environment...
    deactivate
    echo Press any key to exit...
    pause >nul
)
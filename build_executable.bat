@echo off
echo ==========================================
echo  Building Water Refilling Station
echo ==========================================
echo.

REM Check if we're in the right directory
if not exist "manage.py" (
    echo ERROR: manage.py not found!
    echo Make sure you're running this script from your Django project root directory.
    echo.
    pause
    exit /b 1
)

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python and try again.
    echo.
    pause
    exit /b 1
)

echo Step 1: Installing PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install PyInstaller
    pause
    exit /b 1
)

echo.
echo Step 2: Installing Django dependencies...
pip install django
if exist "requirements.txt" (
    echo Installing from requirements.txt...
    pip install -r requirements.txt
)

echo.
echo Step 3: Preparing Django database...
echo Running makemigrations...
python manage.py makemigrations

echo Running migrate...
python manage.py migrate
if errorlevel 1 (
    echo WARNING: Migration failed, continuing anyway...
)

echo.
echo Step 4: Collecting static files...
python manage.py collectstatic --noinput
if errorlevel 1 (
    echo WARNING: Static files collection failed, continuing anyway...
)

echo.
echo Step 5: Creating launcher script...
(
echo import os
echo import sys
echo import django
echo import webbrowser
echo import threading
echo import time
echo from django.core.management import execute_from_command_line
echo.
echo def get_base_dir^(^):
echo     if hasattr^(sys, '_MEIPASS'^):
echo         return sys._MEIPASS
echo     else:
echo         return os.path.dirname^(os.path.abspath^(__file__^)^)
echo.
echo def setup_django^(^):
echo     base_dir = get_base_dir^(^)
echo     sys.path.insert^(0, base_dir^)
echo     os.environ.setdefault^('DJANGO_SETTINGS_MODULE', 'water_refilling_station.settings'^)
echo     django.setup^(^)
echo.
echo def open_browser^(^):
echo     time.sleep^(3^)
echo     webbrowser.open^('http://127.0.0.1:8000'^)
echo.
echo def main^(^):
echo     print^("Starting Water Refilling Station..."^)
echo     setup_django^(^)
echo     browser_thread = threading.Thread^(target=open_browser^)
echo     browser_thread.daemon = True
echo     browser_thread.start^(^)
echo     execute_from_command_line^(['manage.py', 'runserver', '127.0.0.1:8000', '--noreload']^)
echo.
echo if __name__ == '__main__':
echo     main^(^)
) > run_water_station.py

echo Launcher script created: run_water_station.py

echo.
echo Step 6: Building executable...
echo This may take several minutes...

REM Get the project name from the current directory
for %%I in (.) do set PROJECT_NAME=%%~nxI

pyinstaller --onefile ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "staticfiles;staticfiles" ^
    --add-data "media;media" ^
    --add-data "db.sqlite3;." ^
    --hidden-import=django ^
    --hidden-import=django.contrib.admin ^
    --hidden-import=django.contrib.auth ^
    --hidden-import=django.contrib.contenttypes ^
    --hidden-import=django.contrib.sessions ^
    --hidden-import=django.contrib.messages ^
    --hidden-import=django.contrib.staticfiles ^
    --hidden-import=django.db.backends.sqlite3 ^
    --hidden-import=water_refilling_station ^
    --name "WaterRefillingStation" ^
    run_water_station.py

if errorlevel 1 (
    echo.
    echo ERROR: Build failed!
    echo Check the output above for error details.
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo          BUILD COMPLETED SUCCESSFULLY!
echo ==========================================
echo.

if exist "dist\WaterRefillingStation.exe" (
    echo Executable created: dist\WaterRefillingStation.exe
    
    REM Get file size
    for %%A in ("dist\WaterRefillingStation.exe") do (
        set size=%%~zA
        set /a sizeInMB=!size!/1024/1024
    )
    
    echo File size: %size% bytes
    echo.
    echo The executable is now ready for distribution!
    echo Users can run it on any Windows computer without Python installed.
    echo.
    echo Files created:
    echo - dist\WaterRefillingStation.exe (main executable)
    echo - build\ (temporary build files - can be deleted)
    echo - run_water_station.py (launcher script)
    echo - WaterRefillingStation.spec (PyInstaller config)
    echo.
    
    set /p run_now="Do you want to test the executable now? (y/n): "
    if /i "%run_now%"=="y" (
        echo.
        echo Starting executable...
        echo The application will open in your default web browser.
        echo Close the console window to stop the server.
        echo.
        "dist\WaterRefillingStation.exe"
    )
) else (
    echo.
    echo ERROR: Executable not found!
    echo The build process completed but the executable was not created.
    echo Check the PyInstaller output above for errors.
)

echo.
echo Build process finished.
pause
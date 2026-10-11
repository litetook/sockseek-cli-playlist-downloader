@echo off
rem Build a single sockseek-cli.exe for Windows.
rem
rem Needs PyInstaller once:  py -m pip install pyinstaller
rem Output:                  dist\sockseek-cli.exe
rem
rem The exe is the whole program, but NOT the external tools: sockseek and yt-dlp are still
rem fetched at their pinned versions (dependencies.yaml, baked in as a fallback) into the
rem folder the exe sits in. config.yaml, sockseek.conf, Playlists/ and output/ are read from
rem that same folder, so the exe can be dropped next to an existing install and just work.
cd /d "%~dp0"

set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py"
if not defined PY (
    where python >nul 2>nul
    if %errorlevel%==0 set "PY=python"
)
if not defined PY (
    echo Python is not installed, or not on PATH. See README.md.
    exit /b 2
)

%PY% -m PyInstaller --version >nul 2>nul
if not %errorlevel%==0 (
    echo PyInstaller is not installed. Run:  %PY% -m pip install pyinstaller
    exit /b 2
)

echo Running the tests before building...
%PY% -m unittest discover -q
if not %errorlevel%==0 (
    echo Tests failed - not building.
    exit /b 1
)

%PY% -m PyInstaller --onefile --console --name sockseek-cli ^
    --add-data "dependencies.yaml;." ^
    --add-data "sockseek.conf;." ^
    run.py
if not %errorlevel%==0 exit /b 1

echo.
echo Built: dist\sockseek-cli.exe
%PY% -c "import soulseek; print('version:', soulseek.__version__)"

@echo off
setlocal EnableExtensions

rem ============================================================
rem  run_deck.bat
rem  Usage: run_deck.bat NAME [SOLVER_PATH] [THREADS] [CONVERT]
rem    NAME        deck name: the part before _0000.rad (with no NAME_0001.rad: a single combined deck)
rem    SOLVER_PATH unzipped OpenCourant package (exec, extlib, hm_cfg_files)
rem    THREADS     default 4
rem    CONVERT     1 = convert results to .vtk/.csv (default), 0 = skip
rem  Run it from the folder that holds the decks.
rem ============================================================

set "NAME=%~1"
set "SOLVER=%~2"
set "THREADS=%~3"
set "CONVERT=%~4"

if "%NAME%"=="" (
    echo ERROR: missing deck name. Usage: run_deck.bat NAME [SOLVER_PATH] [THREADS] [CONVERT]
    exit /b 1
)
if "%SOLVER%"=="" set "SOLVER=C:\OpenCourant"
if "%THREADS%"=="" set "THREADS=4"
if "%CONVERT%"=="" set "CONVERT=1"

rem One deck NAME_0000.rad with the engine block before /BEGIN is split into a starter and an engine deck in rp_run.
set "COMBINED=0"
if not exist "%NAME%_0000.rad" goto missing_deck
if not exist "%NAME%_0001.rad" set "COMBINED=1"
if not exist "%SOLVER%\exec\starter_win64.exe" goto missing_solver

set "PATH=%SOLVER%\extlib\hm_reader\win64;%SOLVER%\extlib\intelOneAPI_runtime\win64;%PATH%"
set "RAD_CFG_PATH=%SOLVER%\hm_cfg_files"
set "KMP_STACKSIZE=400m"
set "OMP_NUM_THREADS=%THREADS%"

set "STARTDECK=%NAME%_0000.rad"
set "ENGDECK=%NAME%_0001.rad"
if exist rp_run rd /s /q rp_run
mkdir rp_run
if "%COMBINED%"=="1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rp_prepare_engine.ps1" "%NAME%_0000.rad" "rp_run\%NAME%_0001.rad" -Combined
    if errorlevel 1 goto split_failed
    set "STARTDECK=rp_run\%NAME%_0000.rad"
    set "ENGDECK=rp_run\%NAME%_0001.rad"
)

echo === Starter ===
"%SOLVER%\exec\starter_win64.exe" -i "%STARTDECK%" -np 1 -nt %THREADS% > "%NAME%_starter.log" 2>&1

set "ERRCOUNT="
for /f "tokens=1" %%E in ('findstr /R /C:"[0-9][0-9]* *ERROR(S)" "%NAME%_starter.log"') do set "ERRCOUNT=%%E"
if not defined ERRCOUNT goto starter_failed
if not "%ERRCOUNT%"=="0" goto starter_failed
echo Starter finished with 0 errors.

rem RP shows /ANIM output only: the engine runs a copy of the engine deck without the /H3D cards and with a standard
rem /ANIM block when the deck has none (see rp_prepare_engine.ps1). The original deck is never modified.
if "%COMBINED%"=="1" goto engine_ready
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rp_prepare_engine.ps1" "%NAME%_0001.rad" "rp_run\%NAME%_0001.rad"
if exist "rp_run\%NAME%_0001.rad" (set "ENGDECK=rp_run\%NAME%_0001.rad") else rd rp_run
:engine_ready

echo === Engine ===
"%SOLVER%\exec\engine_win64.exe" -i "%ENGDECK%" -nt %THREADS% > "%NAME%_engine.log" 2>&1
findstr /C:"NORMAL TERMINATION" "%NAME%_0001.out" >nul 2>&1
if errorlevel 1 (
    echo WARNING: normal termination message not found. Check %NAME%_0001.out
) else (
    echo Engine finished normally.
)

if "%CONVERT%"=="0" goto done

echo === Converting results ===
set "NGZ=0"
for %%G in ("%NAME%A*.gz") do set /a NGZ+=1
if not %NGZ%==0 echo %NGZ% compressed animation files ^(/ANIM/GZIP^) kept: OpenCourantRP asks which steps to decompress and convert.
set "NANIM=0"
if exist "%NAME%_convert.log" del "%NAME%_convert.log"
for /f "delims=" %%F in ('dir /b /a-d "%NAME%A*" 2^>nul ^| findstr /R /I /C:"^%NAME%A[0-9][0-9]*$"') do (
    set /a NANIM+=1
    echo Converting %%F
    "%SOLVER%\exec\anim_to_vtk_win64.exe" "%%F" > "%%F.vtk" 2>> "%NAME%_convert.log"
    if errorlevel 1 echo WARNING: anim_to_vtk returned an error on %%F, see %NAME%_convert.log
)
if %NANIM%==0 if %NGZ%==0 echo WARNING: no animation files named %NAME%A### were found in %CD%. List the folder to see how the engine named them.

if exist "%NAME%T01" (
    "%SOLVER%\exec\th_to_csv_win64.exe" "%NAME%T01" >> "%NAME%_convert.log" 2>&1
    if errorlevel 1 echo WARNING: th_to_csv returned an error, see %NAME%_convert.log
) else (
    echo WARNING: %NAME%T01 not found, no time history to convert.
)

set "NVTK=0"
for %%V in (*.vtk) do set /a NVTK+=1
echo Animation files converted: %NANIM%. .vtk files now in %CD%: %NVTK%.

:done
rem ---- add your extra CMD commands here ----
endlocal
exit /b 0

:missing_deck
echo ERROR: Missing %NAME%_0000.rad in %CD%. Run this from the folder that holds the decks.
endlocal
exit /b 1

:missing_solver
echo ERROR: OpenCourant not found in %SOLVER%
endlocal
exit /b 1

:split_failed
echo ERROR: %NAME%_0000.rad could not be split into a starter and an engine deck.
endlocal
exit /b 1

:starter_failed
echo ERROR: The starter reported errors: read %NAME%_starter.log and %NAME%_0000.out
endlocal
exit /b 1
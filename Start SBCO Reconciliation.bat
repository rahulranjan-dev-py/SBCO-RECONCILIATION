@echo off
title SBCO Reconciliation Tool
cd /d "%~dp0"
echo.
echo   Starting the SBCO Reconciliation Tool...
echo   Your browser will open in a moment.
echo.
echo   Keep this window open while you work. Close it when you are finished.
echo   Your data is kept in your user folder, not in this program folder,
echo   so upgrading the tool will not touch it.
echo.

rem Three ways to start, tried in order. The last needs no installed shortcut,
rem so the tool still runs when pip put sbco.exe somewhere Windows does not look.
where sbco >nul 2>nul && (sbco gui & goto :done)

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
python -m sbco_recon.cli gui && goto :done
py -3 -m sbco_recon.cli gui && goto :done

echo.
echo   The tool could not start. Running a check to find out why...
echo.
python -m sbco_recon.cli doctor 2>nul || py -3 -m sbco_recon.cli doctor 2>nul || (
  echo   Python itself could not be found on this PC.
  echo.
  echo   Open Command Prompt and run:  python --version
  echo   If that fails, see Part A of the installation guide.
)
echo.
pause

:done

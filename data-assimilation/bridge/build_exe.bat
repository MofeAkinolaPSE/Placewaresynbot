@echo off
REM build_exe.bat — Package bridge.py into a single standalone .exe.
REM
REM No Python install needed on the target Windows 7 server afterwards —
REM just copy placeware_bridge.exe + bridge_config.ini there.
REM
REM Run this from a machine with Python + pyinstaller installed:
REM   pip install pyinstaller requests
REM   build_exe.bat

pyinstaller --onefile --name placeware_bridge --distpath . --workpath build --specpath build ^
    --hidden-import sage50.hard_reader ^
    --hidden-import sage50.btrieve_scanner ^
    bridge.py

echo.
echo Done. placeware_bridge.exe is in this folder.
echo Copy placeware_bridge.exe + bridge_config.ini to the target server,
echo edit bridge_config.ini, then run install_task.ps1 there.

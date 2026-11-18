@echo off
rem Aegis AC - build the telemetry-patched AssaultCube dedicated server (MSVC, 32-bit).
rem Usually called by setup.ps1.   Usage: build.bat [path\to\assaultcube-source]
rem Output: <source>\bin_win32\ac_server_aegis.exe   (the stock server is left untouched)

setlocal
if "%~1"=="" ( set "AC=%~dp0..\..\assaultcube" ) else ( set "AC=%~1" )
set VCVARS="C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat"
if not exist %VCVARS% (
  echo [aegis] Visual Studio 2022 Build Tools not found: %VCVARS%
  exit /b 1
)
call %VCVARS% >nul || exit /b 1

pushd "%AC%\source\src" || exit /b 1
if not exist ..\..\build mkdir ..\..\build

rem No /EH flag on purpose: matches the official vcxproj, and AC's crash handler
rem in main() uses SEH __try, which /EHsc rejects (C2712).
cl /nologo /O2 /MT /W1 ^
   /DWIN32 /DNDEBUG /D_CONSOLE /DSTANDALONE /D_CRT_SECURE_NO_WARNINGS /D_WINSOCK_DEPRECATED_NO_WARNINGS ^
   /I..\enet\include /I..\include /I. ^
   /Fo..\..\build\ ^
   crypto.cpp log.cpp protocol.cpp serverms.cpp server.cpp stream.cpp tools.cpp wizard.cpp ^
   /link /LIBPATH:..\lib enet.lib zdll.lib ws2_32.lib winmm.lib SDL2.lib ^
   advapi32.lib dbghelp.lib ^
   /OUT:..\..\bin_win32\ac_server_aegis.exe
set RC=%ERRORLEVEL%
popd
if not "%RC%"=="0" ( echo [aegis] build FAILED & exit /b %RC% )
echo [aegis] built %AC%\bin_win32\ac_server_aegis.exe
endlocal

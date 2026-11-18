@echo off
rem Aegis AC red team - build the LAB cheat client (ESP + aimbot, LAN-only).
rem Usually called by setup.ps1.   Usage: build.bat [path\to\assaultcube-source]
rem Output: <source>\bin_win32\ac_client_lab.exe   (the stock client is left untouched)

setlocal
if "%~1"=="" ( set "AC=%~dp0..\..\assaultcube" ) else ( set "AC=%~1" )
set VCVARS="C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat"
if not exist %VCVARS% ( echo [aegis] VS 2022 Build Tools not found & exit /b 1 )
call %VCVARS% >nul || exit /b 1

rem The CL env var adds the opt-in define to every compile, including the precompiled header.
set CL=/DAEGIS_LAB
msbuild "%AC%\source\vcpp\assaultcube.vcxproj" /nologo /v:minimal /m ^
  /p:Configuration=Release /p:Platform=Win32 /p:PlatformToolset=v143 ^
  /p:TargetName=ac_client_lab /p:IntDir=..\..\build\lab\ ^
  /p:WindowsTargetPlatformVersion=10.0
if errorlevel 1 ( echo [aegis] build FAILED & exit /b 1 )
echo [aegis] built %AC%\bin_win32\ac_client_lab.exe
endlocal

@echo off
rem Start n8n with Laragon's Node.js. This file runs when PowerShell blocks .ps1 scripts.
set "NODE_DIR=D:\laragon\bin\nodejs\node-v22.23.4-win-x64"
if not exist "%NODE_DIR%\node.exe" (
  echo Laragon Node.js was not found at %NODE_DIR%
  exit /b 1
)
set "PATH=%NODE_DIR%;%PATH%"
where n8n >nul 2>&1
if errorlevel 1 (
  call npm install -g n8n
  if errorlevel 1 exit /b 1
)
n8n start

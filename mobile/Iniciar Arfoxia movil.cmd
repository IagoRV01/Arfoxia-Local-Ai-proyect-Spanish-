@echo off
title Arfoxia para Expo Go
cd /d "%~dp0"
if not exist "C:\Program Files\nodejs\npm.cmd" (
  echo No se encuentra Node.js en C:\Program Files\nodejs.
  echo Instala Node.js o revisa su ruta antes de continuar.
  pause
  exit /b 1
)
"C:\Program Files\nodejs\npm.cmd" start
if errorlevel 1 (
  echo.
  echo Expo se ha cerrado con un error.
  pause
)

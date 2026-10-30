@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if errorlevel 1 goto :folder_unavailable
if /i "%~1"=="--keep-window" goto :run
rem Keep the window without expanding an owner folder path in another command.
"%SystemRoot%\System32\cmd.exe" /D /V:OFF /K ""Start Windows verification.cmd" --keep-window"
exit /b

:run
title Частная сверка банка
echo ЧАСТНАЯ СВЕРКА БАНКА — Windows
echo Сначала подтвердите рабочую семью, затем выберите файлы 1–7.
echo Профиль браузера не читается. Исходные копии не изменяются.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -EncodedCommand __WINDOWS_ENCODED_PREFLIGHT__
echo.
echo Работа программы завершена. В чат сообщите только результат и коды.
echo Окно можно закрыть крестиком в правом верхнем углу.
exit /b

:folder_unavailable
echo Результат: failed
echo Коды: verification-launch-folder-unavailable
"%SystemRoot%\System32\cmd.exe" /D /V:OFF /K
exit /b 1

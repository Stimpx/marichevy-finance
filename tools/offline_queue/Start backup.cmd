@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if errorlevel 1 goto :folder_unavailable
if /i "%~1"=="--keep-window" goto :run
rem Keep the same console open. Pass a fixed relative filename so folder names
rem containing percent signs are never expanded again by the child command.
"%SystemRoot%\System32\cmd.exe" /D /V:OFF /K ""Start backup.cmd" --keep-window"
exit /b

:run
title Частная копия банка
set "NODE_OPTIONS="
set "NODE_PATH="
echo ЧАСТНАЯ КОПИЯ БАНКА — запуск 2
echo Окно останется открытым, чтобы сообщение можно было прочитать.
echo.
if not exist "%~dp0runtime\node.exe" goto :incomplete
if not exist "%~dp0app\bootstrap.cjs" goto :incomplete
if not exist "%~dp0MANIFEST.json" goto :incomplete
"%~dp0runtime\node.exe" --no-global-search-paths --max-old-space-size=256 "%~dp0app\bootstrap.cjs"
echo.
echo Работа помощника завершена. Окно оставлено открытым.
echo Если выше нет слова «СОХРАНЕНО», копия пока не подтверждена.
echo При ошибке сфотографируйте это окно; нажимать клавиши не нужно.
echo Чтобы закрыть окно, нажмите крестик в правом верхнем углу.
exit /b

:incomplete
echo КОМПЛЕКТ РАСПАКОВАН НЕ ПОЛНОСТЬЮ. Копия не создавалась.
echo Закройте окно архива. Нажмите ZIP правой кнопкой мыши.
echo Выберите «Извлечь всё», затем «Извлечь».
echo В открывшейся новой папке запустите «Start backup.cmd».
echo Рядом с ним должны находиться папки app и runtime и файл MANIFEST.json.
echo Это окно останется открытым; его можно сфотографировать.
exit /b 1

:folder_unavailable
echo Не удалось открыть папку помощника. Извлеките весь ZIP в новую локальную папку.
echo Окно останется открытым; его можно сфотографировать.
"%SystemRoot%\System32\cmd.exe" /D /V:OFF /K
exit /b 1

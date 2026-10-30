#!/bin/bash
# Read-only diagnosis of the original fixed Mac helper. No profile selection.
set -u
umask 077
task_result=1
task_finish() {
  printf '\n%s\n' 'Проверка завершена. Пришлите строки «Код», «Системный код» и «Причина загрузки», если они есть.'
  if [ -t 0 ]; then
    printf '%s' 'Нажмите Enter, чтобы закрыть окно: '
    IFS= read -r task_end
  fi
  exit "$task_result"
}
if [ "$(/usr/bin/uname -s)" != Darwin ]; then
  printf '%s\n' 'Код: diagnostic-platform'
  task_finish
fi
case "$(/usr/bin/uname -m)" in
  arm64) task_arch=arm64; task_runtime_sha=2cc28a1880d0774616959f2210ee739bffa6ac695c887e8988a496a21271f6c0 ;;
  x86_64) task_arch=x64; task_runtime_sha=e55a748c81980fda1399e65b686708960d6bb9b7e8ea5913d85a97c6a19e7a7b ;;
  *) printf '%s\n' 'Код: diagnostic-architecture'; task_finish ;;
esac
if ! cd "$(/usr/bin/dirname "$0")" 2>/dev/null; then
  printf '%s\n' 'Код: diagnostic-directory'
  task_finish
fi
task_diag_dir=$(pwd -P)
task_parent=$(/usr/bin/dirname "$task_diag_dir")
if [ -f "$task_parent/MANIFEST.json" ]; then
  task_bundle="$task_parent"
elif [ -f "$task_parent/mac-private-backup-helper-v95/MANIFEST.json" ]; then
  task_bundle="$task_parent/mac-private-backup-helper-v95"
else
  printf '%s\n' 'Скопируйте путь к РАСПАКОВАННОЙ папке mac-private-backup-helper-v95.'
  printf '%s\n' 'Нужна папка программы, не профиль Chrome и не файл резервной копии.'
  printf '%s' 'Путь к папке помощника: '
  IFS= read -r task_bundle
fi
task_node="$task_bundle/runtime/$task_arch/node"
task_diag="$task_diag_dir/mac-diagnose.cjs"
if [ -L "$task_bundle" ] || [ ! -f "$task_bundle/MANIFEST.json" ] || [ -L "$task_node" ] || [ ! -x "$task_node" ] || [ -L "$task_diag" ] || [ ! -f "$task_diag" ]; then
  printf '%s\n' 'Код: diagnostic-input-files'
  task_finish
fi
task_runtime_actual=$(/usr/bin/shasum -a 256 "$task_node" 2>/dev/null) || { printf '%s\n' 'Код: diagnostic-runtime-read'; task_finish; }
task_runtime_actual=${task_runtime_actual%% *}
if [ "$task_runtime_actual" != "$task_runtime_sha" ]; then
  printf '%s\n' 'Код: diagnostic-runtime-checksum'
  task_finish
fi
task_diag_actual=$(/usr/bin/shasum -a 256 "$task_diag" 2>/dev/null) || { printf '%s\n' 'Код: diagnostic-source-read'; task_finish; }
task_diag_actual=${task_diag_actual%% *}
if [ "$task_diag_actual" != 0b42f887eab5a8e3d8d6d4bb3fff93347cf873f1bf1c33884237b4bc9f39e555 ]; then
  printf '%s\n' 'Код: diagnostic-source-checksum'
  task_finish
fi
printf '%s\n' 'Проверяем только файлы программы. Данные банка и профиль Chrome не читаются.'
/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=ru_RU.UTF-8 "$task_node" --no-global-search-paths "$task_diag" "$task_bundle" 2>/dev/null
task_result=$?
if [ "$task_result" -ne 0 ]; then
  printf '%s\n' "Процесс диагностики: exit-$task_result"
fi
task_finish

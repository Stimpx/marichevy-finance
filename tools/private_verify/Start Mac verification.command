#!/bin/bash -p
# Offline owner-local comparison; reuse the original verified helper runtime.
set -u
umask 077
task_result=1
task_finish() {
  printf '\n%s\n' 'Работа программы завершена. В чат сообщи только результат и коды; файлы оставь у себя.'
  if [ -t 0 ]; then
    printf '%s' 'Нажми Enter, чтобы закрыть окно: '
    IFS= read -r task_end
  fi
  exit "$task_result"
}
if [ "$(/usr/bin/uname -s)" != Darwin ]; then
  printf '%s\n' 'Коды: verification-platform'
  task_finish
fi
case "$(/usr/bin/uname -m)" in
  arm64) task_arch=arm64; task_runtime_sha=2cc28a1880d0774616959f2210ee739bffa6ac695c887e8988a496a21271f6c0 ;;
  x86_64) task_arch=x64; task_runtime_sha=e55a748c81980fda1399e65b686708960d6bb9b7e8ea5913d85a97c6a19e7a7b ;;
  *) printf '%s\n' 'Коды: verification-architecture'; task_finish ;;
esac
if ! cd "$(/usr/bin/dirname "$0")" 2>/dev/null; then
  printf '%s\n' 'Коды: verification-directory'
  task_finish
fi
task_addon=$(pwd -P)
task_parent=$(/usr/bin/dirname "$task_addon")
if [ -f "$task_parent/mac-private-backup-helper-v95/MANIFEST.json" ]; then
  task_bundle="$task_parent/mac-private-backup-helper-v95"
else
  printf '%s\n' 'Скопируй путь к РАСПАКОВАННОЙ папке mac-private-backup-helper-v95, которая уже работала на этом Mac.'
  printf '%s\n' 'Нужна папка программы, не профиль Chrome и не файл резервной копии.'
  printf '%s' 'Путь к папке помощника: '
  IFS= read -r task_bundle
fi
task_node="$task_bundle/runtime/$task_arch/node"
task_bootstrap="$task_addon/app/mac-bootstrap.cjs"
if [ -L "$task_bundle" ] || [ ! -f "$task_bundle/MANIFEST.json" ] || [ -L "$task_node" ] || [ ! -x "$task_node" ] || [ -L "$task_bootstrap" ] || [ ! -f "$task_bootstrap" ]; then
  printf '%s\n' 'Коды: verification-input-files'
  task_finish
fi
task_runtime_actual=$(/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/bin/shasum -a 256 "$task_node" 2>/dev/null) || { printf '%s\n' 'Коды: verification-runtime-read'; task_finish; }
task_runtime_actual=${task_runtime_actual%% *}
if [ "$task_runtime_actual" != "$task_runtime_sha" ]; then
  printf '%s\n' 'Коды: verification-runtime-checksum'
  task_finish
fi
task_bootstrap_actual=$(/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/bin/shasum -a 256 "$task_bootstrap" 2>/dev/null) || { printf '%s\n' 'Коды: verification-source-read'; task_finish; }
task_bootstrap_actual=${task_bootstrap_actual%% *}
if [ "$task_bootstrap_actual" != __ADDON_BOOTSTRAP_SHA256__ ]; then
  printf '%s\n' 'Коды: verification-source-checksum'
  task_finish
fi
printf '%s\n' 'Этап: запуск среды программы'
/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=ru_RU.UTF-8 "$task_node" --version >/dev/null 2>/dev/null
task_runtime_result=$?
if [ "$task_runtime_result" -ne 0 ]; then
  task_result=$task_runtime_result
  printf '%s\n' 'Результат: failed'
  case "$task_runtime_result" in
    137) printf '%s\n' 'Коды: verification-runtime-signal-9' ;;
    *) printf '%s\n' 'Коды: verification-runtime-start-failed' ;;
  esac
  task_finish
fi
printf '%s\n' 'Проверяем файлы программы. Затем откроется выбор семи копий банка; профиль браузера не читается.'
/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=ru_RU.UTF-8 "$task_node" --no-global-search-paths "$task_bootstrap" "$task_bundle" 2>/dev/null
task_result=$?
case "$task_result" in
  0|1|2) ;; # The application already printed its verified result and codes.
  137) printf '%s\n' 'Результат: failed' 'Коды: verification-process-signal-9' ;;
  *) printf '%s\n' 'Результат: failed' 'Коды: verification-process-unexpected-exit' ;;
esac
task_finish

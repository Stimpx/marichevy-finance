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
# HELPER_FOLDER_SELECTION_BEGIN
task_helper_folder_valid() {
  [ -d "$1" ] && [ ! -L "$1" ] &&
    [ -f "$1/Start Mac backup.command" ] && [ ! -L "$1/Start Mac backup.command" ] &&
    [ -f "$1/MANIFEST.json" ] && [ ! -L "$1/MANIFEST.json" ] &&
    [ -d "$1/runtime" ] && [ ! -L "$1/runtime" ] &&
    [ -d "$1/runtime/$task_arch" ] && [ ! -L "$1/runtime/$task_arch" ] &&
    [ -f "$1/runtime/$task_arch/node" ] && [ -x "$1/runtime/$task_arch/node" ] &&
    [ ! -L "$1/runtime/$task_arch/node" ]
}
task_choose_helper_script='on run
try
set selectedFolder to choose folder with prompt "Выбери РАСПАКОВАННУЮ папку старого помощника резервной копии mac-private-backup-helper-v95. Внутри должны быть Start Mac backup.command и папка runtime." default location (path to downloads folder)
return POSIX path of selectedFolder
on error number -128
return "helper-selection-cancelled"
end try
end run'
task_wrong_helper_script='on run
try
display dialog "Нужна папка старого помощника резервной копии, в которой есть Start Mac backup.command и папка runtime. Выбранная папка для этого запуска не подходит. Выбери другую папку; начинать заново не нужно." buttons {"Завершить", "Выбрать другую папку"} default button "Выбрать другую папку" cancel button "Завершить" with title "Выбор помощника резервной копии"
return "choose-again"
on error number -128
return "helper-selection-cancelled"
end try
end run'
if task_helper_folder_valid "$task_parent/mac-private-backup-helper-v95"; then
  task_bundle="$task_parent/mac-private-backup-helper-v95"
else
  printf '%s\n' 'Этап: выбор папки исходного помощника'
  while :; do
    task_bundle=$(/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=ru_RU.UTF-8 /usr/bin/osascript -e "$task_choose_helper_script" 2>/dev/null) || {
      printf '%s\n' 'Результат: failed' 'Коды: verification-helper-selection-failed'; task_finish;
    }
    if [ "$task_bundle" = helper-selection-cancelled ]; then
      printf '%s\n' 'Результат: failed' 'Коды: verification-helper-selection-cancelled'; task_finish
    fi
    task_bundle=${task_bundle%/}
    if task_helper_folder_valid "$task_bundle"; then
      break
    fi
    task_folder_action=$(/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=ru_RU.UTF-8 /usr/bin/osascript -e "$task_wrong_helper_script" 2>/dev/null) || {
      printf '%s\n' 'Результат: failed' 'Коды: verification-helper-selection-failed'; task_finish;
    }
    if [ "$task_folder_action" = helper-selection-cancelled ]; then
      printf '%s\n' 'Результат: failed' 'Коды: verification-helper-selection-cancelled'; task_finish
    fi
    if [ "$task_folder_action" != choose-again ]; then
      printf '%s\n' 'Результат: failed' 'Коды: verification-helper-selection-failed'; task_finish
    fi
  done
fi
# HELPER_FOLDER_SELECTION_END
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

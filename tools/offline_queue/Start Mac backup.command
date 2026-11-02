#!/bin/bash
# Local, offline program. No browser console, downloads or permission changes.
set -u
umask 077

task_result=1
task_system=$(/usr/bin/uname -s)
task_machine=$(/usr/bin/uname -m)
if [ "$task_system" != "Darwin" ]; then
  printf '%s\n' 'Этот комплект предназначен только для macOS.'
  exit 64
fi
case "$task_machine" in
  arm64) task_arch=arm64 ;;
  x86_64) task_arch=x64 ;;
  *) printf '%s\n' 'Этот Mac не поддерживается. Копия не создана.'; exit 64 ;;
esac
if ! cd "$(/usr/bin/dirname "$0")"; then
  printf '%s\n' 'Не удалось открыть папку помощника.'
  exit 1
fi
task_bundle_dir=$(pwd -P)
task_node="$task_bundle_dir/runtime/$task_arch/node"
if [ ! -x "$task_node" ] || [ ! -f "$task_bundle_dir/app/mac-bootstrap.cjs" ] || [ ! -f "$task_bundle_dir/MANIFEST.json" ]; then
  printf '%s\n' 'КОПИЯ НЕ СОЗДАНА. Распакуйте весь архив в новую папку.'
else
  # A clean environment prevents NODE_OPTIONS/NODE_PATH and DYLD/LD injection
  # before Node loads bootstrap. Only the bundled runtime and modules are used.
  /usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=ru_RU.UTF-8 "$task_node" --no-global-search-paths "$task_bundle_dir/app/mac-bootstrap.cjs"
  task_result=$?
fi
printf '\n%s\n' 'Работа помощника завершена. Проверьте, появилось ли сообщение «СОХРАНЕНО».'
if [ -t 0 ]; then
  printf '%s' 'Нажмите Enter, чтобы закрыть окно: '
  IFS= read -r task_end
fi
exit "$task_result"

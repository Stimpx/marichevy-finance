'use strict';

// A local command-line application, not code for a browser console. It never
// starts a browser, reads credentials or makes network requests.
const fs = require('node:fs/promises');
const path = require('node:path');
const readline = require('node:readline/promises');
const {ClassicLevel} = require('classic-level');
const windows = require('./windows.cjs');
const core = require('./capture.cjs');
const {validateClone} = require('./integrity.cjs');
const {selftest} = require('./selftest.cjs');

const MESSAGES = Object.freeze({
  WINDOWS_UNSUPPORTED: 'Этот комплект предназначен для Windows x64.',
  WINDOWS_BINDINGS_UNAVAILABLE: 'Комплект программы неполный. Распакуйте весь архив в новую папку.',
  BROWSER_RUNNING: 'Chrome или Яндекс Браузер ещё работает. Закройте его через меню «Выход», затем повторите запуск.',
  BROWSER_CHECK_FAILED: 'Не удалось проверить закрытие браузера. Копия не создана.',
  SOURCE_PATH_UNSAFE: 'Нужен обычный локальный путь к профилю, без сетевого диска и ссылок.',
  SOURCE_INVALID: 'Не удалось прочитать выбранную папку. Копия не создана.',
  SOURCE_LOCK_UNAVAILABLE: 'Файлы браузера ещё заняты. Копия не создана.',
  SOURCE_LOCK_RELEASE_FAILED: 'Не удалось завершить защиту чтения. Закройте помощник перед повторным запуском.',
  PRIVATE_ACL_UNAVAILABLE: 'Не удалось создать закрытую папку на этом диске. Копирование остановлено.',
  PRIVATE_DIRECTORY_FAILED: 'Не удалось создать закрытую папку для копии.',
  'unsupported-sqlite-storage': 'Эта версия браузера использует другой формат хранения. Копия не создана; нужен отдельный проверенный способ.',
  'source-layout-unsupported': 'Не найдено ожидаемое хранилище браузера. Проверьте путь профиля.',
  'source-changed': 'Во время чтения файлы изменились. Копия не создана. Полностью закройте браузер и повторите.',
  'source-unsafe': 'Не удалось подтвердить безопасное чтение исходной папки. Копия не создана.',
  'source-incomplete': 'Набор файлов хранилища неполный. Копия не создана.',
  'source-read-failed': 'Не удалось прочитать хранилище закрытого браузера. Копия не создана.',
  'source-size-limit': 'Хранилище превышает проверенный размер. Копия не создана; исходные файлы не менялись.',
  'capture-size-limit': 'Копия превышает проверенный размер. Файл не сохранён; исходные данные не менялись.',
  'integrity-validation-failed': 'Проверка целостности хранилища не прошла. Не очищайте и не исправляйте его самостоятельно.',
  'database-read-failed': 'Не удалось точно восстановить состояние хранилища. Исходные файлы не менялись.',
  'invalid-storage-encoding': 'Найден неподдерживаемый формат строки. Исходные данные не менялись.',
  'duplicate-financial-key': 'Найдены неоднозначные варианты одной записи. Исходные данные не менялись.',
  'no-financial-keys': 'В выбранном профиле не найдены записи этого банка. Это не доказывает, что очередь другого профиля пуста.',
  'clone-cleanup-failed': 'Не удалось удалить временную частную копию. Основной файл резерва не создан.',
  'selftest-failed': 'Встроенная проверка помощника на вымышленных данных не прошла. Файлы вашего профиля не читались.',
  'capture-write-failed': 'Не удалось сохранить файл копии. Исходное хранилище не менялось.',
  'invalid-profile-path': 'Вставьте только путь из строки «Путь к профилю», например C:\\Users\\...\\Default.',
  'capture-failed': 'Копирование остановлено. Не очищайте данные браузера; сообщите только код ошибки.',
});

async function openDatabase(cloneDir, options, proof) {
  if (!proof || proof.validated !== true || proof.checksumSource !== 'external-crc32c-preflight') {
    throw new core.CaptureError('engine-checksums-unverified');
  }
  return new ClassicLevel(cloneDir, options);
}

function profilePath(text) {
  let value = String(text ?? '').trim();
  if (value.startsWith('"') && value.endsWith('"')) value = value.slice(1,-1);
  if (!/^[A-Za-z]:[\\/]/.test(value) || /[\x00-\x1f<>"|?*]/.test(value) || value.length > 32700) {
    throw Object.assign(new Error('invalid-profile-path'), {code:'invalid-profile-path'});
  }
  return path.win32.normalize(value);
}

async function main() {
  const terminal = readline.createInterface({input:process.stdin, output:process.stdout});
  let outputDir;
  try {
    console.log('ЧАСТНАЯ КОПИЯ БАНКА — Windows\n');
    console.log('Помощник сохраняет финансовые строки только сайта finance.marichev.pro.');
    console.log('Записи банка, настройки браузера и сессии входа он не изменяет.');
    console.log('Пароли и ключи вводить не нужно. Программа не отправляет данные в интернет.\n');
    console.log('Заранее сохраните обычный JSON из банка. В Chrome откройте chrome://version,');
    console.log('в Яндекс Браузере — browser://version. Скопируйте строку «Путь к профилю».');
    console.log('Этот путь вставляется как имя папки, а не как команда.\n');
    const profile = profilePath(await terminal.question('Вставьте путь к профилю и нажмите Enter: '));
    console.log('\nТеперь полностью закройте Chrome и Яндекс Браузер, включая окно этого чата.');
    console.log('Перед закрытием завершите заполнение и сохранение текущей покупки.');
    await terminal.question('Когда браузеры закрыты, нажмите Enter здесь: ');
    await windows.assertBrowserClosed();
    const bundleRoot = path.dirname(__dirname);
    outputDir = await windows.createPrivateDirectory(bundleRoot, 'PRIVATE-backup-');
    console.log('\nПроверяем помощник на вымышленных данных до чтения вашего профиля…');
    try { await selftest({outputDir, windows, openDatabase, validateClone}); }
    catch (_) { throw Object.assign(new Error('selftest-failed'), {code:'selftest-failed'}); }
    console.log('Встроенная проверка пройдена. Сохраняем частную копию…');
    const result = await core.captureProfile({
      sourceDir:path.join(profile,'Local Storage','leveldb'), outputDir,
      withSourceLock:windows.withSourceLock, openDatabase, validateClone,
      makePrivateTemp:windows.createPrivateDirectory,
    });
    const stat = await fs.lstat(result.output_path);
    if (!stat.isFile() || stat.isSymbolicLink() || !stat.size) throw Object.assign(new Error('capture-write-failed'), {code:'capture-write-failed'});
    console.log('\nСОХРАНЕНО. Частный файл находится здесь:\n'+result.output_path);
    console.log('\nПереложите его рядом с обычным JSON этого Windows-профиля.');
    console.log('Это дополнительная копия для проверки; самостоятельно импортировать её в банк не нужно.');
    console.log('В чат достаточно написать «Очередь Windows сохранена». Сам файл оставьте у себя.');
    return 0;
  } catch (error) {
    const code = Object.hasOwn(MESSAGES, error?.code) ? error.code : 'capture-failed';
    console.log('\nКОПИЯ НЕ ПОДТВЕРЖДЕНА.\n'+MESSAGES[code]+'\nКод: '+code);
    if (outputDir && code === 'clone-cleanup-failed') console.log('Временная частная папка: '+outputDir);
    return 1;
  } finally {
    terminal.close();
  }
}

if (require.main === module) main().then(code=>{process.exitCode=code;}).catch(()=>{
  console.log('КОПИЯ НЕ ПОДТВЕРЖДЕНА. Копирование остановлено.\nКод: capture-failed');
  process.exitCode=1;
});
module.exports = {main, profilePath, openDatabase};

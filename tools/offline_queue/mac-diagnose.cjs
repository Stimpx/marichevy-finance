'use strict';

// Diagnostic for the fixed first Mac ZIP. Read-only code-bundle checks only.
// Never calls main(), opens LevelDB, reads a browser profile, or changes files.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

const OLD_MANIFEST_SHA256 = '5136a4d4a3c864f6643b00322bab2405b6a4efd904f169a46a9394f442f422b4';
const SAFE_ERRORS = new Set(['ENOENT','EACCES','EPERM','ENOTDIR','EISDIR','ELOOP','EMFILE','ENFILE',
  'ERR_DLOPEN_FAILED','MODULE_NOT_FOUND','ERR_MODULE_NOT_FOUND','ERR_REQUIRE_ESM',
  'ERR_UNKNOWN_BUILTIN_MODULE','ERR_UNSUPPORTED_ESM_URL_SCHEME']);
const REQUIRED = ['Start Mac backup.command','README_MAC_RU.txt','BUILD.json',
  'app/mac-bootstrap.cjs','app/mac-main.cjs','app/macos.cjs','app/capture.cjs','app/integrity.cjs',
  'runtime/arm64/node','runtime/arm64/NODE-LICENSE.txt','runtime/x64/node','runtime/x64/NODE-LICENSE.txt'];
function safeCode(error) { return SAFE_ERRORS.has(error?.code) ? error.code : 'unknown-error'; }
function nativeCause(error) {
  if (error?.code !== 'ERR_DLOPEN_FAILED') return undefined;
  const message = typeof error.message === 'string' ? error.message : '';
  if (/code signature|code signing|security policy|system policy|not valid for use|library validation|library load disallowed|unsigned/i.test(message)) return 'native-policy';
  if (/incompatible architecture|wrong architecture|bad cpu type/i.test(message)) return 'native-architecture';
  if (/symbol not found|library not loaded|image not found|dependent dylib.*not found/i.test(message)) return 'native-linker';
  return 'native-other';
}
class DiagnosticError extends Error {
  constructor(stage, codeFile, errorCode, causeCode) {
    super(stage); this.stage = stage;
    if (codeFile) this.codeFile = codeFile;
    if (errorCode) this.errorCode = errorCode;
    if (causeCode) this.causeCode = causeCode;
  }
}
function fail(stage, codeFile, error) { throw new DiagnosticError(stage, codeFile, error ? safeCode(error) : undefined, nativeCause(error)); }
function relative(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= 500 &&
    !/[\x00-\x1f\\:<>"|?*]/.test(value) && !value.startsWith('/') &&
    value.split('/').every(part => part && part !== '.' && part !== '..');
}
function bucket(name) {
  return name === '.DS_Store' ? 'ds-store' : name.startsWith('._') ? 'apple-double' : 'other';
}
async function hash(filename) {
  const handle = await fs.open(filename, 'r');
  try {
    const digest = crypto.createHash('sha256');
    for await (const bytes of handle.createReadStream({autoClose:false})) digest.update(bytes);
    return digest.digest('hex');
  } finally { await handle.close(); }
}
async function verifyOldBundle(root, expectedManifest = OLD_MANIFEST_SHA256) {
  if (typeof root !== 'string' || !path.isAbsolute(root) || /[\x00-\x1f]/.test(root) ||
      root.split('/').some(part => part === '.' || part === '..')) fail('root-path');
  try {
    if (await fs.realpath(root) !== path.resolve(root) || (await fs.lstat(root)).isSymbolicLink()) fail('root-path');
  } catch (error) { if (error instanceof DiagnosticError) throw error; fail('root-access', undefined, error); }
  const manifestPath = path.join(root, 'MANIFEST.json');
  let raw;
  try {
    const stat = await fs.lstat(manifestPath);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 2 * 1024 * 1024) fail('manifest-file');
    raw = await fs.readFile(manifestPath);
  } catch (error) { if (error instanceof DiagnosticError) throw error; fail('manifest-access', undefined, error); }
  if (crypto.createHash('sha256').update(raw).digest('hex') !== expectedManifest) fail('manifest-changed');
  let manifest;
  try { manifest = JSON.parse(raw.toString('utf8')); } catch (_) { fail('manifest-format'); }
  if (manifest.format !== 'marichevy-offline-queue-macos-bundle-v1' ||
      !Array.isArray(manifest.files) || manifest.files.length < 10 || manifest.files.length > 5000) fail('manifest-format');
  const expected = new Map(), directories = new Set(['app','runtime']), folded = new Set();
  for (const item of manifest.files) {
    if (!relative(item?.path) || (!item.path.startsWith('app/') && !item.path.startsWith('runtime/') &&
        !['Start Mac backup.command','README_MAC_RU.txt','BUILD.json'].includes(item.path)) ||
        expected.has(item.path) || folded.has(item.path.toLowerCase()) ||
        !/^[a-f0-9]{64}$/.test(item.sha256) || !Number.isSafeInteger(item.bytes) ||
        item.bytes < 0 || item.bytes > 160 * 1024 * 1024) fail('manifest-format');
    expected.set(item.path, item); folded.add(item.path.toLowerCase());
    const parts = item.path.split('/');
    for (let index = 1; index < parts.length; index++) directories.add(parts.slice(0, index).join('/'));
  }
  if (REQUIRED.some(name => !expected.has(name))) fail('manifest-required-file');
  let visited = 0;
  async function inspect(directory, prefix) {
    let entries;
    try { entries = await fs.readdir(directory, {withFileTypes:true}); }
    catch (error) { fail('code-directory-access', undefined, error); }
    for (const entry of entries) {
      if (++visited > 6000) fail('code-file-limit');
      const name = prefix + '/' + entry.name;
      if (!relative(name)) fail('unexpected-name-' + bucket(entry.name));
      if (!expected.has(name) && !directories.has(name)) fail('unexpected-name-' + bucket(entry.name));
      if (entry.isSymbolicLink()) fail('code-link', expected.has(name) ? name : undefined);
      let stat;
      try { stat = await fs.lstat(path.join(directory, entry.name)); }
      catch (error) { fail('code-file-access', expected.has(name) ? name : undefined, error); }
      if (stat.isSymbolicLink()) fail('code-link', expected.has(name) ? name : undefined);
      if (stat.isDirectory()) {
        if (!directories.has(name)) fail('code-file-type', expected.has(name) ? name : undefined);
        await inspect(path.join(directory, entry.name), name);
      } else if (!stat.isFile() || !expected.has(name)) fail('code-file-type', expected.has(name) ? name : undefined);
    }
  }
  // Existing PRIVATE-backup directories at bundle root are deliberately ignored.
  await inspect(path.join(root, 'app'), 'app');
  await inspect(path.join(root, 'runtime'), 'runtime');
  for (const [name, item] of expected) {
    const filename = path.join(root, ...name.split('/'));
    let parent = path.dirname(filename);
    while (parent !== root) {
      let stat;
      try { stat = await fs.lstat(parent); } catch (error) { fail('code-parent-access', name, error); }
      if (!stat.isDirectory() || stat.isSymbolicLink()) fail('code-parent-path', name);
      parent = path.dirname(parent);
    }
    let stat;
    try { stat = await fs.lstat(filename); }
    catch (error) { fail(error.code === 'ENOENT' ? 'code-file-missing' : 'code-file-access', name, error); }
    if (!stat.isFile() || stat.isSymbolicLink()) fail('code-file-type', name);
    if (stat.size !== item.bytes) fail('code-file-size', name);
    let digest;
    try { digest = await hash(filename); } catch (error) { fail('code-file-read', name, error); }
    if (digest !== item.sha256) fail('code-file-changed', name);
  }
  return true;
}
function clearLoaderOverrides() {
  for (const name of ['CLASSIC_LEVEL_PREBUILD','npm_config_arch','npm_config_platform','LIBC','ARM_VERSION','ELECTRON_RUN_AS_NODE']) delete process.env[name];
  process.env.PREBUILDS_ONLY = '1';
}
async function diagnose(root, options = {}) {
  const runtime = options.runtime || {platform:process.platform, arch:process.arch, version:process.versions.node};
  const output = options.output || (line => console.log(line));
  const load = options.load || (filename => require(filename));
  if (runtime.platform !== 'darwin' || !['arm64','x64'].includes(runtime.arch) || runtime.version !== '22.23.4') fail('runtime-mismatch');
  output('Проверка: runtime-passed');
  await verifyOldBundle(root, options.expectedManifest || OLD_MANIFEST_SHA256);
  output('Проверка: fixed-bundle-integrity-passed');
  clearLoaderOverrides();
  for (const [stage, file] of [
    ['classic-level-module-load','app/node_modules/classic-level'],
    ['koffi-module-load','app/node_modules/koffi'],
    ['macos-module-load','app/macos.cjs'],
    ['integrity-module-load','app/integrity.cjs'],
    ['main-module-load','app/mac-main.cjs']
  ]) {
    try { load(path.join(root, file)); } catch (error) { fail(stage, undefined, error); }
    output('Проверка: ' + stage + '-passed');
  }
  output('Диагностика завершена: modules-load-passed. Профиль браузера не читался.');
  return true;
}
function report(error) {
  if (!(error instanceof DiagnosticError)) return 'Код: diagnostic-internal-error';
  let result = 'Код: ' + error.stage;
  if (error.codeFile) result += '\nФайл программы: ' + error.codeFile;
  if (error.errorCode) result += '\nСистемный код: ' + error.errorCode;
  if (error.causeCode) result += '\nПричина загрузки: ' + error.causeCode;
  return result;
}
async function run() {
  try {
    if (process.argv.length !== 3) fail('diagnostic-arguments');
    await diagnose(process.argv[2]);
  } catch (error) {
    console.log('ДИАГНОСТИКА ОСТАНОВЛЕНА. Файлы профиля не читались.\n' + report(error));
    process.exitCode = 1;
  }
}
if (require.main === module) run();
module.exports = {OLD_MANIFEST_SHA256, verifyOldBundle, diagnose, report, DiagnosticError};

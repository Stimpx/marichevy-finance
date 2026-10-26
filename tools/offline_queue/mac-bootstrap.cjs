'use strict';

// Code-only bundle verification before any third-party/native module is loaded.
// The manifest detects changed/incomplete files; it is not a digital signature.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

function invalid() { throw new Error('bundle-integrity-failed'); }
function relativeName(value) {
  if (typeof value !== 'string' || !value || value.length > 500 ||
      /[\x00-\x1f\\:<>"|?*]/.test(value) || value.startsWith('/') ||
      value.split('/').some(part => !part || part === '.' || part === '..')) invalid();
  return value;
}
async function digest(filename) {
  const handle = await fs.open(filename, 'r');
  try {
    const hash = crypto.createHash('sha256');
    for await (const part of handle.createReadStream({autoClose:false})) hash.update(part);
    return hash.digest('hex');
  } finally { await handle.close(); }
}
async function verifyBundle(root) {
  if (await fs.realpath(root) !== path.resolve(root) || (await fs.lstat(root)).isSymbolicLink()) invalid();
  const filename = path.join(root, 'MANIFEST.json');
  const stat = await fs.lstat(filename);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 2 * 1024 * 1024) invalid();
  const manifest = JSON.parse(await fs.readFile(filename, 'utf8'));
  if (manifest.format !== 'marichevy-offline-queue-macos-bundle-v1' ||
      !Array.isArray(manifest.files) || manifest.files.length < 10 || manifest.files.length > 5000) invalid();
  const expected = new Map();
  const folded = new Set();
  for (const file of manifest.files) {
    const name = relativeName(file.path);
    if (!name.startsWith('app/') && !name.startsWith('runtime/') &&
        !['Start Mac backup.command','README_MAC_RU.txt','BUILD.json'].includes(name)) invalid();
    if (expected.has(name) || folded.has(name.toLowerCase()) || !/^[a-f0-9]{64}$/.test(file.sha256) ||
        !Number.isSafeInteger(file.bytes) || file.bytes < 0 || file.bytes > 160 * 1024 * 1024) invalid();
    expected.set(name, file);
    folded.add(name.toLowerCase());
  }
  for (const name of ['Start Mac backup.command','README_MAC_RU.txt','BUILD.json',
    'app/mac-bootstrap.cjs','app/mac-main.cjs','app/macos.cjs','app/capture.cjs','app/integrity.cjs',
    'runtime/arm64/node','runtime/arm64/NODE-LICENSE.txt','runtime/x64/node','runtime/x64/NODE-LICENSE.txt']) {
    if (!expected.has(name)) invalid();
  }
  let visited = 0;
  async function inspect(directory, prefix) {
    for (const entry of await fs.readdir(directory, {withFileTypes:true})) {
      if (++visited > 6000 || entry.isSymbolicLink()) invalid();
      const name = relativeName(prefix + '/' + entry.name), absolute = path.join(directory, entry.name);
      const item = await fs.lstat(absolute);
      if (item.isSymbolicLink()) invalid();
      if (item.isDirectory()) await inspect(absolute, name);
      else if (!item.isFile() || !expected.has(name)) invalid();
    }
  }
  // Existing PRIVATE-backup output folders at bundle root are never traversed.
  await inspect(path.join(root, 'app'), 'app');
  await inspect(path.join(root, 'runtime'), 'runtime');
  for (const [name, file] of expected) {
    const absolute = path.join(root, ...name.split('/'));
    let parent = path.dirname(absolute);
    while (parent !== root) {
      const item = await fs.lstat(parent);
      if (!item.isDirectory() || item.isSymbolicLink()) invalid();
      parent = path.dirname(parent);
    }
    const item = await fs.lstat(absolute);
    if (!item.isFile() || item.isSymbolicLink() || item.size !== file.bytes || await digest(absolute) !== file.sha256) invalid();
  }
  return true;
}
async function run() {
  try {
    if (process.platform !== 'darwin' || !['arm64','x64'].includes(process.arch) || process.versions.node !== '22.23.4') invalid();
    await verifyBundle(path.dirname(__dirname));
    for (const name of ['CLASSIC_LEVEL_PREBUILD','npm_config_arch','npm_config_platform','LIBC','ARM_VERSION','ELECTRON_RUN_AS_NODE']) delete process.env[name];
    process.env.PREBUILDS_ONLY = '1';
    const {main} = require('./mac-main.cjs');
    process.exitCode = await main();
  } catch (_) {
    console.log('КОПИЯ НЕ СОЗДАНА. Комплект неполный, изменён или не поддерживается.\nРаспакуйте весь исходный архив в новую папку. Защиту macOS отключать не нужно.\nКод: bundle-integrity-failed');
    process.exitCode = 1;
  }
}
if (require.main === module) run();
module.exports = {verifyBundle, relativeName};

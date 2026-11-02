'use strict';

// Verify the extracted bundle before loading any third-party module or helper.
// This detects incomplete/changed files; it is not a digital signature. Obtain
// the archive only from the pinned project download supplied with the release.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

function invalid() { throw new Error('bundle-integrity-failed'); }
function relativeName(value) {
  // Apply Windows component rules even in Linux build tests. Win32 strips
  // trailing dots/spaces; accepting '.. ' could turn a nominal app path into
  // a parent traversal when filesystem APIs resolve it on the owner device.
  if (typeof value !== 'string' || value.length > 500 || /[\x00-\x1f<>"|?*]/.test(value) || value.includes('\\') ||
      value.includes(':') || value.startsWith('/') || value.split('/').some(part =>
        !part || part==='.' || part==='..' || /[. ]$/.test(part) ||
        /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))) invalid();
  return value;
}
async function digest(filename) {
  const handle=await fs.open(filename,'r');
  try {
    const hash=crypto.createHash('sha256');
    for await (const part of handle.createReadStream({autoClose:false})) hash.update(part);
    return hash.digest('hex');
  } finally { await handle.close(); }
}
async function verifyBundle(root) {
  const real=await fs.realpath(root);
  if (real!==path.resolve(root) || (await fs.lstat(root)).isSymbolicLink()) invalid();
  const manifestFile=path.join(root,'MANIFEST.json');
  const stat=await fs.lstat(manifestFile);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size>2*1024*1024) invalid();
  const manifest=JSON.parse(await fs.readFile(manifestFile,'utf8'));
  if (manifest.format!=='marichevy-offline-queue-bundle-v1' || !Array.isArray(manifest.files) ||
      manifest.files.length<10 || manifest.files.length>5000) invalid();
  const expected=new Map();
  for (const file of manifest.files) {
    const name=relativeName(file.path);
    if (!name.startsWith('app/') && !name.startsWith('runtime/') &&
        !['Start backup.cmd','README_RU.txt','BUILD.json'].includes(name)) invalid();
    if (expected.has(name) || !/^[a-f0-9]{64}$/.test(file.sha256) || !Number.isSafeInteger(file.bytes) || file.bytes<0 || file.bytes>100*1024*1024) invalid();
    expected.set(name,file);
  }
  for (const name of ['Start backup.cmd','README_RU.txt','BUILD.json','app/bootstrap.cjs','app/main.cjs','app/selftest.cjs','app/windows.cjs','app/capture.cjs','app/integrity.cjs','runtime/node.exe','runtime/NODE-LICENSE.txt']) {
    if (!expected.has(name)) invalid();
  }
  let visited=0;
  async function inspect(directory, prefix) {
    for (const entry of await fs.readdir(directory,{withFileTypes:true})) {
      if (++visited>6000 || entry.isSymbolicLink()) invalid();
      const name=relativeName(prefix+'/'+entry.name), absolute=path.join(directory,entry.name);
      const item=await fs.lstat(absolute);
      if (item.isSymbolicLink()) invalid();
      if (item.isDirectory()) await inspect(absolute,name);
      else if (!item.isFile() || !expected.has(name)) invalid();
    }
  }
  // Output folders at bundle root are deliberately excluded. Never inspect an
  // existing PRIVATE-backup directory or any browser profile during bootstrap.
  await inspect(path.join(root,'app'),'app');
  await inspect(path.join(root,'runtime'),'runtime');
  for (const [name,file] of expected) {
    const absolute=path.join(root,...name.split('/'));
    let parent=path.dirname(absolute);
    while (parent!==root) {
      const item=await fs.lstat(parent);
      if (!item.isDirectory() || item.isSymbolicLink()) invalid();
      parent=path.dirname(parent);
    }
    const item=await fs.lstat(absolute);
    if (!item.isFile() || item.isSymbolicLink() || item.size!==file.bytes || await digest(absolute)!==file.sha256) invalid();
  }
  return true;
}
async function run() {
  try {
    await verifyBundle(path.dirname(__dirname));
    // Native dependency loaders accept environment overrides. Use only the
    // bundled prebuilds after their hashes have been checked.
    for (const name of ['CLASSIC_LEVEL_PREBUILD','npm_config_arch','npm_config_platform','LIBC','ARM_VERSION','ELECTRON_RUN_AS_NODE']) delete process.env[name];
    process.env.PREBUILDS_ONLY='1';
    const {main}=require('./main.cjs');
    process.exitCode=await main();
  } catch (_) {
    console.log('КОПИЯ НЕ СОЗДАНА. Комплект неполный, изменён или не поддерживается.\nРаспакуйте весь исходный архив в новую папку. Не отключайте защиту Windows.\nКод: bundle-integrity-failed');
    process.exitCode=1;
  }
}
if (require.main===module) run();
module.exports={verifyBundle,relativeName};

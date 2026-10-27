'use strict';

// The shell pins this bootstrap. It pins every other addon payload and the
// complete original helper before either application or native-module imports.
const fs=require('node:fs/promises');
const constants=require('node:fs').constants;
const path=require('node:path');
const crypto=require('node:crypto');
const OLD_MANIFEST_SHA256='5136a4d4a3c864f6643b00322bab2405b6a4efd904f169a46a9394f442f422b4';
const ADDON_MANIFEST_SHA256='__ADDON_MANIFEST_SHA256__';
const NODE_PINS=Object.freeze({
  arm64:'2cc28a1880d0774616959f2210ee739bffa6ac695c887e8988a496a21271f6c0',
  x64:'e55a748c81980fda1399e65b686708960d6bb9b7e8ea5913d85a97c6a19e7a7b',
});
const ADDON_FILES=Object.freeze(['BUILD.json','README_MAC_RU.txt','app/core.cjs',
  'app/mac-main.cjs','app/owner-export.cjs','app/owner-export.sql','app/local-restore.cjs',
  'app/sql-sources.json','app/pglite/index.cjs','app/pglite/pglite.wasm',
  'app/pglite/pglite.data','app/pglite/package.json','app/pglite/LICENSE']);
const OLD_REQUIRED=Object.freeze(['Start Mac backup.command','README_MAC_RU.txt','BUILD.json',
  'app/mac-bootstrap.cjs','app/mac-main.cjs','app/macos.cjs','app/capture.cjs','app/integrity.cjs',
  'runtime/arm64/node','runtime/arm64/NODE-LICENSE.txt','runtime/x64/node','runtime/x64/NODE-LICENSE.txt']);
const MAX_FILE=160*1024*1024,MAX_MANIFEST=2*1024*1024;
class BootstrapError extends Error {
  constructor(code){super(code);this.name='BootstrapError';this.code=code;}
}
const fail=code=>{throw new BootstrapError(code);};
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function relative(value){
  // All reviewed program paths are ASCII; this also makes case-fold identity
  // unambiguous on the owner's case-insensitive filesystem.
  return typeof value==='string'&&value.length>0&&value.length<=500&&
    /^[A-Za-z0-9@._ +/()-]+$/.test(value)&&!value.startsWith('/')&&
    value.split('/').every(piece=>piece&&piece!=='.'&&piece!=='..');
}
function identity(stat){return ['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'].map(key=>stat[key].toString()).join(':');}
async function rootPath(root){
  if(typeof root!=='string'||!path.isAbsolute(root)||/[\x00-\x1f\x7f]/.test(root)||
    root==='/'||path.normalize(root)!==root||root.split('/').some(piece=>piece==='.'||piece==='..'))fail('verification-code-root');
  const stat=await fs.lstat(root,{bigint:true});
  if(!stat.isDirectory()||stat.isSymbolicLink()||await fs.realpath(root)!==root)fail('verification-code-root');
  return root;
}
async function bytes(filename,maximum=MAX_FILE){
  let handle;
  try{
    if(typeof constants.O_NOFOLLOW!=='number')fail('verification-code-platform');
    handle=await fs.open(filename,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
    const before=await handle.stat({bigint:true});
    if(!before.isFile()||before.nlink!==1n||before.size<0n||before.size>BigInt(maximum))fail('verification-code-file');
    const content=await handle.readFile(),after=await handle.stat({bigint:true});
    const current=await fs.lstat(filename,{bigint:true});
    if(identity(before)!==identity(after)||identity(after)!==identity(current)||content.length!==Number(before.size))fail('verification-code-changed');
    return content;
  }finally{if(handle)await handle.close();}
}
function manifestValue(raw,kind){
  let value;try{value=JSON.parse(raw.toString('utf8'));}catch(_){fail('verification-manifest-format');}
  const expectedFormat=kind==='old'?'marichevy-offline-queue-macos-bundle-v1':'marichevy-private-verification-macos-bundle-v1';
  if(!value||typeof value!=='object'||Array.isArray(value)||value.format!==expectedFormat||
    Object.keys(value).sort().join(',')!=='files,format'||!Array.isArray(value.files)||!value.files.length||value.files.length>5000)
    fail('verification-manifest-format');
  const expected=new Map(),folded=new Set(),directories=new Set();
  for(const item of value.files){
    if(!item||typeof item!=='object'||Array.isArray(item)||Object.keys(item).sort().join(',')!=='bytes,path,sha256'||
      !relative(item.path)||expected.has(item.path)||folded.has(item.path.toLowerCase())||
      !/^[a-f0-9]{64}$/.test(item.sha256)||!Number.isSafeInteger(item.bytes)||item.bytes<0||item.bytes>MAX_FILE)
      fail('verification-manifest-format');
    if(kind==='old'&&!item.path.startsWith('app/')&&!item.path.startsWith('runtime/')&&
      !['Start Mac backup.command','README_MAC_RU.txt','BUILD.json'].includes(item.path))fail('verification-manifest-format');
    expected.set(item.path,item);folded.add(item.path.toLowerCase());
    const pieces=item.path.split('/');for(let n=1;n<pieces.length;n++)directories.add(pieces.slice(0,n).join('/'));
  }
  if(kind==='addon'&&(expected.size!==ADDON_FILES.length||ADDON_FILES.some(name=>!expected.has(name))))fail('verification-manifest-coverage');
  if(kind==='old'&&OLD_REQUIRED.some(name=>!expected.has(name)))fail('verification-manifest-coverage');
  const allFolded=new Map();
  for(const name of [...expected.keys(),...directories]){
    const lower=name.toLowerCase();
    if(allFolded.has(lower)&&allFolded.get(lower)!==name)fail('verification-manifest-format');allFolded.set(lower,name);
  }
  for(const name of expected.keys())if(directories.has(name))fail('verification-manifest-format');
  return {expected,directories};
}
async function verifyClosure(root,kind,expectedManifest){
  try{
    await rootPath(root);
    const raw=await bytes(path.join(root,'MANIFEST.json'),MAX_MANIFEST);
    if(!/^[a-f0-9]{64}$/.test(expectedManifest)||sha(raw)!==expectedManifest)fail('verification-manifest-changed');
    const {expected,directories}=manifestValue(raw,kind);
    const roots=new Set(['MANIFEST.json']);
    if(kind==='addon'){roots.add('Start Mac verification.command');roots.add('app/mac-bootstrap.cjs');directories.add('app');}
    let visited=0;
    async function inspect(directory,prefix=''){
      const entries=await fs.readdir(directory,{withFileTypes:true});
      const localFolded=new Set();
      for(const entry of entries){
        if(++visited>6000)fail('verification-code-file-limit');
        const name=prefix?prefix+'/'+entry.name:entry.name,filename=path.join(directory,entry.name);
        const folded=entry.name.toLowerCase();if(localFolded.has(folded))fail('verification-code-case-collision');localFolded.add(folded);
        const stat=await fs.lstat(filename,{bigint:true});
        if(stat.isSymbolicLink())fail('verification-code-link');
        // Only directory metadata is inspected; never traverse private output.
        if(!prefix&&/^PRIVATE-(?:backup|verification)-[A-Za-z0-9_-]+$/.test(entry.name)){
          if(!stat.isDirectory())fail('verification-code-private-type');continue;
        }
        // Finder metadata has no effect on module resolution. Its contents are
        // never read; metadata anywhere inside a code tree remains forbidden.
        if(!prefix&&entry.name==='.DS_Store'){
          if(!stat.isFile()||stat.nlink!==1n||stat.size>1024n*1024n)fail('verification-code-metadata');continue;
        }
        if(!relative(name)||(!expected.has(name)&&!directories.has(name)&&!roots.has(name)))fail('verification-code-unexpected-file');
        if(stat.isDirectory()){
          if(!directories.has(name))fail('verification-code-file');await inspect(filename,name);
        }else if(!stat.isFile()||stat.nlink!==1n||directories.has(name))fail('verification-code-file');
      }
    }
    await inspect(root);
    for(const [name,item]of expected){
      const content=await bytes(path.join(root,...name.split('/')));
      if(content.length!==item.bytes||sha(content)!==item.sha256)fail('verification-code-changed');
    }
    // The trust-root names are allowed in the inventory, but still must exist
    // as regular non-linked files. The shell already checked bootstrap bytes.
    for(const name of roots){const stat=await fs.lstat(path.join(root,...name.split('/')),{bigint:true});
      if(!stat.isFile()||stat.isSymbolicLink()||stat.nlink!==1n)fail('verification-code-file');}
    return true;
  }catch(error){if(error instanceof BootstrapError)throw error;fail('verification-code-unavailable');}
}
async function verifyOldBundle(root,expectedManifest=OLD_MANIFEST_SHA256){return verifyClosure(root,'old',expectedManifest);}
async function verifyAddon(root,expectedManifest=ADDON_MANIFEST_SHA256){return verifyClosure(root,'addon',expectedManifest);}
function clearLoaderOverrides(){
  for(const name of Object.keys(process.env))if(/^(?:NODE_|DYLD_|npm_config_|CLASSIC_LEVEL_PREBUILD$|LIBC$|ARM_VERSION$|ELECTRON_RUN_AS_NODE$)/.test(name))delete process.env[name];
  process.env.PREBUILDS_ONLY='1';
}
async function run(){
  try{
    if(process.platform!=='darwin'||!['arm64','x64'].includes(process.arch)||process.versions.node!=='22.23.4'||
      typeof process.getuid!=='function'||process.getuid()<=0||process.geteuid()!==process.getuid())fail('verification-runtime');
    if(process.argv.length!==3)fail('verification-arguments');
    const oldBundleRoot=process.argv[2],addonRoot=path.dirname(__dirname);
    if(oldBundleRoot===addonRoot)fail('verification-code-root');
    console.log('Этап: проверка исходного помощника');
    await verifyOldBundle(oldBundleRoot);
    console.log('Этап: проверка программы сверки');
    await verifyAddon(addonRoot);
    const selectedNode=path.join(oldBundleRoot,'runtime',process.arch,'node');
    if(process.execPath!==selectedNode||sha(await bytes(selectedNode))!==NODE_PINS[process.arch])fail('verification-runtime');
    clearLoaderOverrides();
    console.log('Этап: загрузка программы сверки');
    const main=require('./mac-main.cjs'),localRestore=require('./local-restore.cjs');
    if(typeof main.main!=='function'||typeof localRestore.restore!=='function')fail('verification-entry-point');
    process.exitCode=await main.main({oldBundleRoot,addonRoot:__dirname,restore:localRestore.restore});
  }catch(error){
    console.log('Результат: failed');
    console.log('Коды: '+(error instanceof BootstrapError?error.code:'verification-bootstrap-failed'));
    process.exitCode=1;
  }
}
if(require.main===module)run();
module.exports=Object.freeze({verifyOldBundle,verifyAddon,relative,BootstrapError,OLD_MANIFEST_SHA256,ADDON_MANIFEST_SHA256,NODE_PINS});

'use strict';

// The fixed PowerShell launcher pins this bootstrap, the manifest and Node.
// Only built-in modules are imported until the complete payload is verified.
const fs=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const MANIFEST_SHA256='__WINDOWS_MANIFEST_SHA256__';
const NODE_SHA256='dccc52de28d8df2ee22d2062424f8c563070d95d8ad70c54c4bf01d590dec14f';
const MAX_FILE=160*1024*1024,MAX_MANIFEST=2*1024*1024;
const REQUIRED=Object.freeze(['BUILD.json','README_WINDOWS_RU.txt','runtime/node.exe','runtime/NODE-LICENSE.txt',
  'app/core.cjs','app/owner-export.cjs','app/owner-export.sql','app/local-restore.cjs','app/sql-sources.json',
  'app/windows-main.cjs','app/windows-io.cjs','app/windows.cjs','app/pglite/index.cjs','app/pglite/pglite.wasm',
  'app/pglite/pglite.data','app/pglite/package.json','app/pglite/LICENSE',
  'app/node_modules/koffi/package.json','app/node_modules/koffi/LICENSE.txt','app/node_modules/koffi/index.cjs',
  'app/node_modules/koffi/src/koffi/index.cjs','app/node_modules/koffi/src/koffi/src/static.cjs',
  'app/node_modules/@koromix/koffi-win32-x64/package.json','app/node_modules/@koromix/koffi-win32-x64/README.md',
  'app/node_modules/@koromix/koffi-win32-x64/index.js','app/node_modules/@koromix/koffi-win32-x64/win32_x64/koffi.node']);
const ROOTS=Object.freeze(['MANIFEST.json','Start Windows verification.cmd','Start Windows verification.ps1','app/windows-bootstrap.cjs']);
class BootstrapError extends Error{constructor(code){super(code);this.name='BootstrapError';this.code=code;}}
const fail=code=>{throw new BootstrapError(code);};
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function relative(value){
  return typeof value==='string'&&value.length>0&&value.length<=500&&
    /^[A-Za-z0-9@._ +/()-]+$/.test(value)&&!value.startsWith('/')&&
    value.split('/').every(part=>part&&part!=='.'&&part!=='..'&&!/[. ]$/.test(part)&&
      !/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part));
}
function identity(stat){return ['dev','ino','mode','nlink','size','mtimeNs','ctimeNs'].map(key=>stat[key].toString()).join(':');}
async function bytes(filename,maximum=MAX_FILE){
  let handle;
  try{
    const leaf=await fs.lstat(filename,{bigint:true});
    if(!leaf.isFile()||leaf.isSymbolicLink()||leaf.nlink!==1n||leaf.size<0n||leaf.size>BigInt(maximum))fail('verification-code-file');
    handle=await fs.open(filename,'r');
    const before=await handle.stat({bigint:true});
    if(identity(before)!==identity(leaf))fail('verification-code-changed');
    const content=await handle.readFile(),after=await handle.stat({bigint:true});
    if(identity(before)!==identity(after)||identity(after)!==identity(await fs.lstat(filename,{bigint:true}))||
      content.length!==Number(before.size))fail('verification-code-changed');
    return content;
  }finally{if(handle)await handle.close();}
}
function manifestValue(raw){
  let value;try{value=JSON.parse(raw.toString('utf8'));}catch(_){fail('verification-manifest-format');}
  if(!value||typeof value!=='object'||Array.isArray(value)||value.format!=='marichevy-private-verification-windows-bundle-v1'||
    Object.keys(value).sort().join(',')!=='files,format'||!Array.isArray(value.files)||value.files.length!==REQUIRED.length)
    fail('verification-manifest-format');
  const expected=new Map(),folded=new Set(),directories=new Set();
  for(const item of value.files){
    if(!item||typeof item!=='object'||Array.isArray(item)||Object.keys(item).sort().join(',')!=='bytes,path,sha256'||
      !relative(item.path)||!REQUIRED.includes(item.path)||expected.has(item.path)||folded.has(item.path.toLowerCase())||
      !/^[a-f0-9]{64}$/.test(item.sha256)||!Number.isSafeInteger(item.bytes)||item.bytes<0||item.bytes>MAX_FILE)
      fail('verification-manifest-format');
    expected.set(item.path,item);folded.add(item.path.toLowerCase());
    const parts=item.path.split('/');for(let n=1;n<parts.length;n++)directories.add(parts.slice(0,n).join('/'));
  }
  if(REQUIRED.some(name=>!expected.has(name)))fail('verification-manifest-coverage');
  return {expected,directories};
}
async function verifyBundle(root,expectedManifest=MANIFEST_SHA256){
  try{
    if(typeof root!=='string'||!path.isAbsolute(root)||path.normalize(root)!==root||/[\x00-\x1f\x7f]/.test(root))fail('verification-code-root');
    const real=await fs.realpath(root),rootStat=await fs.lstat(root,{bigint:true});
    if(!rootStat.isDirectory()||rootStat.isSymbolicLink()||real.toLowerCase()!==root.toLowerCase())fail('verification-code-root');
    // Reject junction/symlink ancestors as well, before examining descendants.
    let parent=root;
    for(;;){const stat=await fs.lstat(parent,{bigint:true});
      if(!stat.isDirectory()||stat.isSymbolicLink())fail('verification-code-root');
      const next=path.dirname(parent);if(next===parent)break;parent=next;}
    const raw=await bytes(path.join(root,'MANIFEST.json'),MAX_MANIFEST);
    if(!/^[a-f0-9]{64}$/.test(expectedManifest)||sha(raw)!==expectedManifest)fail('verification-manifest-changed');
    const {expected,directories}=manifestValue(raw);const roots=new Set(ROOTS);let visited=0;
    async function inspect(directory,prefix=''){
      const folded=new Set();
      for(const entry of await fs.readdir(directory,{withFileTypes:true})){
        if(++visited>500)fail('verification-code-file-limit');
        const lower=entry.name.toLowerCase();if(folded.has(lower))fail('verification-code-case-collision');folded.add(lower);
        const name=prefix?prefix+'/'+entry.name:entry.name,filename=path.join(directory,entry.name);
        const stat=await fs.lstat(filename,{bigint:true});if(stat.isSymbolicLink())fail('verification-code-link');
        // Never read an existing private result directory or its contents.
        if(!prefix&&/^PRIVATE-verification-[A-Za-z0-9_-]+$/.test(entry.name)){
          if(!stat.isDirectory())fail('verification-code-private-type');continue;
        }
        if(!relative(name)||(!expected.has(name)&&!directories.has(name)&&!roots.has(name)))fail('verification-code-unexpected-file');
        if(stat.isDirectory()){
          if(!directories.has(name))fail('verification-code-file');await inspect(filename,name);
        }else if(!stat.isFile()||stat.nlink!==1n||directories.has(name))fail('verification-code-file');
      }
    }
    await inspect(root);
    for(const [name,item]of expected){const content=await bytes(path.join(root,...name.split('/')));
      if(content.length!==item.bytes||sha(content)!==item.sha256)fail('verification-code-changed');}
    for(const name of roots){const stat=await fs.lstat(path.join(root,...name.split('/')),{bigint:true});
      if(!stat.isFile()||stat.isSymbolicLink()||stat.nlink!==1n)fail('verification-code-file');}
    return true;
  }catch(error){if(error instanceof BootstrapError)throw error;fail('verification-code-unavailable');}
}
function clearLoaderOverrides(){
  for(const name of Object.keys(process.env))if(/^(?:NODE_|DYLD_|npm_config_|KOFFI_|CLASSIC_LEVEL_PREBUILD$|LIBC$|ARM_VERSION$|ELECTRON_RUN_AS_NODE$)/i.test(name))delete process.env[name];
  process.env.PREBUILDS_ONLY='1';
}
async function run(){
  try{
    if(process.platform!=='win32'||process.arch!=='x64'||process.versions.node!=='22.23.4'||process.argv.length!==2)fail('verification-runtime');
    const bundleRoot=path.dirname(__dirname);
    console.log('Этап: проверка программы сверки');await verifyBundle(bundleRoot);
    const selectedNode=path.join(bundleRoot,'runtime','node.exe');
    if(process.execPath.toLowerCase()!==selectedNode.toLowerCase()||sha(await bytes(selectedNode))!==NODE_SHA256)fail('verification-runtime');
    clearLoaderOverrides();console.log('Этап: загрузка программы сверки');
    const main=require('./windows-main.cjs'),restore=require('./local-restore.cjs');
    if(typeof main.main!=='function'||typeof restore.restore!=='function')fail('verification-entry-point');
    process.exitCode=await main.main({bundleRoot,addonRoot:__dirname,restore:restore.restore});
  }catch(error){console.log('Результат: failed');console.log('Коды: '+(error instanceof BootstrapError?error.code:'verification-bootstrap-failed'));process.exitCode=1;}
}
if(require.main===module)run();
module.exports=Object.freeze({verifyBundle,relative,manifestValue,BootstrapError,MANIFEST_SHA256,NODE_SHA256,REQUIRED,ROOTS});

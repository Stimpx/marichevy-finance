'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {_createAdapterForTests: create} = require('../tools/offline_queue/windows.cjs');
function fixture(overrides={}) {
 const state={last:18,held:false,calls:[],processes:['explorer.exe'],scan:0,names:['LOCK','CURRENT','MANIFEST-000001','000003.log'],paths:new Map([['C:\\',16],['C:\\fixture',16],['C:\\fixture\\leveldb',16],['C:\\private',16]])};
 const original='C:\\fixture\\leveldb';
 const clean=p=>p.replace(/^\\\\\?\\/,'');
 const sid=Buffer.alloc(16);sid[0]=1;sid[1]=2;sid[7]=5;sid.writeUInt32LE(21,8);sid.writeUInt32LE(42,12);
 const fill=(buffer,name)=>{buffer.fill(0,44);buffer.write(name,44,'utf16le');};
 const native={
  CreateToolhelp32Snapshot(flags,pid){assert.equal(flags,2);assert.equal(pid,0);state.scan++;state.index=0;state.calls.push(['snapshot']);if(state.secondBrowser&&state.scan===2)state.processes=['browser.exe'];return 10n;},
  Process32FirstW(handle,buf){assert.equal(buf.length,568);assert.equal(buf.readUInt32LE(0),568);if(!state.processes.length){state.last=18;return 0;}fill(buf,state.processes[0]);return 1;},
  Process32NextW(handle,buf){state.index++;if(state.index>=state.processes.length){state.last=18;return 0;}fill(buf,state.processes[state.index]);return 1;},
  GetLastError(){return state.last;},
  CloseHandle(handle){state.calls.push(['close',handle]);if(handle===99n)state.held=false;return !(state.closeLockFails&&handle===99n);},
  GetDriveTypeW(){return state.remote?4:3;},
  GetFileAttributesW(p){const value=clean(p);if(state.paths.has(value))return state.paths.get(value);if(value.startsWith(original+'\\')&&state.names.includes(value.slice(original.length+1)))return 32;return 0xffffffff;},
  CreateFileW(...args){state.calls.push(['open',...args]);if(state.openThrows)throw Error('sensitive raw native path');if(state.busy)return 0xffffffffffffffffn;state.held=true;return 99n;},
  GetFileType(){return 1;},
  GetFileInformationByHandleEx(handle,kind,out,size){assert.equal(kind,9);out.writeUInt32LE(state.lockAttrs||32,0);return 1;},
  GetCurrentProcess(){return 0xffffffffffffffffn;},
  OpenProcessToken(process,rights,out){assert.equal(rights,8);out.writeBigUInt64LE(50n);return 1;},
  GetTokenInformation(token,kind,out,size,needed){assert.equal(kind,1);needed.writeUInt32LE(32);if(!out){state.last=122;return 0;}out.writeBigUInt64LE(1000n);return 1;},
  GetLengthSid(){return sid.length;},CopySid(length,out,pointer){assert.equal(pointer,1000n);sid.copy(out);return 1;},
  ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,revision,out){state.sddl=sddl;assert.equal(revision,1);out.writeBigUInt64LE(2000n);return 1;},
  CreateDirectoryW(p,sa){assert.equal(sa.length,24);assert.equal(sa.readUInt32LE(0),24);assert.equal(sa.readBigUInt64LE(8),2000n);assert.equal(sa.readUInt32LE(16),0);state.created=clean(p);state.paths.set(state.created,16);return 1;},
  GetVolumeInformationW(root,a,b,c,d,flags){assert.equal(root,'C:\\');flags.writeUInt32LE(state.noAcl?0:8);return 1;},
  LocalFree(pointer){state.freed=pointer;return null;},
 };
 Object.assign(state,overrides);
 const fs={async readdir(dir,options){assert.equal(dir,original);assert.equal(options.withFileTypes,true);return state.names.map(name=>({name,isFile:()=>name!=='subfolder',isSymbolicLink:()=>name==='linked-file'}));}};
 return {state,original,adapter:create({native,fs,platform:'win32',arch:'x64',randomBytes:()=>Buffer.alloc(12,7)})};
}
const rejects=async(fn,code)=>assert.rejects(fn,e=>e.code===code&&!/sensitive/.test(e.message));
test('unsupported platforms fail before loading native bindings',async()=>{await rejects(()=>create({platform:'linux',arch:'x64'}).assertBrowserClosed(),'WINDOWS_UNSUPPORTED');await rejects(()=>create({platform:'win32',arch:'arm64'}).assertBrowserClosed(),'WINDOWS_UNSUPPORTED');});
test('Toolhelp reads process names, detects both browsers case-insensitively and closes snapshot',async()=>{for(const name of ['ChRoMe.ExE','browser.exe']){const f=fixture({processes:[name]});await rejects(()=>f.adapter.assertBrowserClosed(),'BROWSER_RUNNING');assert.equal(f.state.calls.filter(x=>x[0]==='close').length,1);assert.equal(f.state.calls.filter(x=>x[0]==='open').length,0);}});
test('existing LOCK is read-only, exclusive, OPEN_EXISTING and held through asynchronous copy/hash',async()=>{const f=fixture();const result=await f.adapter.withSourceLock(f.original,async()=>{assert(f.state.held);await Promise.resolve();assert(f.state.held);return 'copied-and-hashed';});assert.equal(result,'copied-and-hashed');assert(!f.state.held);const call=f.state.calls.find(x=>x[0]==='open');assert.deepEqual(call.slice(1),['\\\\?\\C:\\fixture\\leveldb\\LOCK',0x80000000,0,null,3,0x00200000,null]);assert.equal(f.state.scan,2);});
test('busy/missing LOCK prevent callback and never create source files',async()=>{for(const settings of [{busy:true},{names:['CURRENT']}]){const f=fixture(settings);let called=false;await rejects(()=>f.adapter.withSourceLock(f.original,()=>{called=true;}),'SOURCE_LOCK_UNAVAILABLE');assert(!called);assert(!f.state.held);}});
test('reparse parents, reparse LOCK, symlink entries, directory entries, ADS and UNC are refused',async()=>{for(const mode of ['parent','lock','symlink','directory','ads','unc']){const f=fixture();let source=f.original;if(mode==='parent')f.state.paths.set('C:\\fixture',16|0x400);if(mode==='lock')f.state.lockAttrs=0x400;if(mode==='symlink')f.state.names.push('linked-file');if(mode==='directory')f.state.names.push('subfolder');if(mode==='ads')source+=':other';if(mode==='unc')source='\\\\server\\share\\leveldb';await rejects(()=>f.adapter.withSourceLock(source,()=>assert.fail('callback forbidden')),'SOURCE_PATH_UNSAFE');assert(!f.state.held);}});
test('browser starting during lock acquisition aborts and releases guard',async()=>{const f=fixture({secondBrowser:true});await rejects(()=>f.adapter.withSourceLock(f.original,()=>assert.fail('callback forbidden')),'BROWSER_RUNNING');assert(!f.state.held);});
test('native exceptions are fixed safe errors; callback errors retain caller ownership',async()=>{const f=fixture({openThrows:true});await rejects(()=>f.adapter.withSourceLock(f.original,()=>{}),'SOURCE_INVALID');const g=fixture(),sentinel=Object.assign(Error('core safe status'),{code:'CORE_UNSTABLE'});await assert.rejects(()=>g.adapter.withSourceLock(g.original,async()=>{throw sentinel;}),e=>e===sentinel);assert(!g.state.held);});
test('failed guard release is reported',async()=>{const f=fixture({closeLockFails:true});await rejects(()=>f.adapter.withSourceLock(f.original,async()=>true),'SOURCE_LOCK_RELEASE_FAILED');});
test('new private directory is atomically created with explicit user owner and protected user+SYSTEM inheritable DACL',async()=>{const f=fixture();const created=await f.adapter.createPrivateDirectory('C:\\private','private-');assert.equal(created,f.state.created);assert.match(created,/^C:\\private\\private-[0-9a-f]{24}$/);assert.equal(f.state.sddl,'O:S-1-5-21-42D:P(A;OICI;FA;;;S-1-5-21-42)(A;OICI;FA;;;SY)');assert.equal(f.state.freed,2000n);assert.equal(f.state.calls.filter(x=>x[0]==='open').length,0);});
test('filesystem without persistent ACL and unsafe private parent fail closed',async()=>{const f=fixture({noAcl:true});await rejects(()=>f.adapter.createPrivateDirectory('C:\\private','private-'),'PRIVATE_ACL_UNAVAILABLE');assert(!f.state.created);const g=fixture();g.state.paths.set('C:\\private',16|0x400);await rejects(()=>g.adapter.createPrivateDirectory('C:\\private','private-'),'SOURCE_PATH_UNSAFE');assert(!g.state.created);});

test('mapped network drive is rejected before profile enumeration',async()=>{const f=fixture({remote:true});await rejects(()=>f.adapter.withSourceLock(f.original,()=>assert.fail('callback forbidden')),'SOURCE_PATH_UNSAFE');assert.equal(f.state.calls.filter(x=>x[0]==='open').length,0);});

test('capture core temporary prefix is accepted by the private ACL creator',async()=>{const fs=require('node:fs');const source=fs.readFileSync(require.resolve('../tools/offline_queue/capture.cjs'),'utf8');const prefix=source.match(/makePrivateTemp\(outputPath, '([^']+)'\)/)?.[1];assert(prefix);const f=fixture();const target=await f.adapter.createPrivateDirectory('C:\\private',prefix);assert.equal(target,f.state.created);assert.match(target,/private-queue-clone-/);});

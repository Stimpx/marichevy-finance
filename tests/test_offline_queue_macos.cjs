'use strict';
// Linux contract mocks exercise fail-closed branches. They do not establish
// actual Darwin ABI/ACL/lock behavior; the owner-device native selftest must pass.
const test=require('node:test');
const assert=require('node:assert/strict');
const {constants}=require('node:fs');
const path=require('node:path');
const {_createAdapterForTests:create,_flockForTests:flock,_localPathForTests:localPath}=require('../tools/offline_queue/macos.cjs');
const rejects=(fn,code)=>assert.rejects(fn,error=>error.code===code&&!/PRIVATE_TEST_PATH/.test(error.message));
function fixture(overrides={}){
  const state={calls:[],processes:['/sbin/launchd','/usr/bin/Terminal'],scan:0,fdOpen:false,held:false,
    entries:['LOCK','CURRENT','MANIFEST-000001','000003.log'],errno:0,type:'apfs',flags:0x1000,
    directories:new Map(),files:new Map(),aclPresent:true};
  const makeStat=(name,directory,options={})=>({dev:1,ino:name,uid:501,nlink:directory?2:1,mode:directory?0o40700:0o100600,
    isDirectory:()=>directory,isFile:()=>!directory,isSymbolicLink:()=>false,...options});
  for(const name of ['/','/Users','/Users/test','/Users/test/profile','/Users/test/profile/Local Storage',
      '/Users/test/profile/Local Storage/leveldb','/Users/test/bundle'])state.directories.set(name,makeStat(name,true));
  state.directories.get('/Users').uid=0;state.directories.get('/').uid=0;
  const original='/Users/test/profile/Local Storage/leveldb';
  for(const name of state.entries)state.files.set(path.posix.join(original,name),makeStat(name,false));
  Object.assign(state,overrides);
  const fs={
    async lstat(name){state.calls.push(['lstat',name]);const result=state.directories.get(name)||state.files.get(name);
      if(!result)throw Object.assign(new Error('PRIVATE_TEST_PATH'),{code:'ENOENT'});return {...result};},
    async realpath(name){return state.realpathOverride||name;},
    async readdir(name){assert.equal(name,original);return state.entries.map(name=>({name,isSymbolicLink:()=>name==='linked',isFile:()=>name!=='folder'}));},
    async mkdir(name,opts){state.calls.push(['mkdir',name,opts]);
      if(state.collision)throw Object.assign(new Error(),{code:'EEXIST'});
      state.created=name;state.directories.set(name,makeStat(name,true,{mode:0o40755}));},
    async open(name,flags){state.calls.push(['open',name,flags]);if(state.openThrows)throw new Error('PRIVATE_TEST_PATH');
      const stat=state.directories.get(name)||state.files.get(name);if(!stat)throw new Error('PRIVATE_TEST_PATH');
      const lock=name.endsWith('/LOCK');if(lock){assert.equal(state.fdOpen,false);state.fdOpen=true;}
      return {fd:lock?80:81,async stat(){return {...stat,...(state.openedIdentityOverride||{})};},
        async chmod(mode){state.calls.push(['chmod',name,mode]);stat.mode=0o40000|mode;},
        async close(){state.calls.push(['close',name]);if(lock){state.fdOpen=false;state.held=false;}
          if(state.closeWait){state.closeEntered?.();await state.closeWait;}
          if(state.closeFails)throw new Error('PRIVATE_TEST_PATH');}};
    }
  };
  const native={
    lock(fd,type){state.calls.push(['fcntl',fd,type]);assert.equal(fd,80);assert.equal(type,1);if(state.busy)return -1;state.held=true;return 0;},
    statfs(dir,out){state.calls.push(['statfs',dir]);out.writeUInt32LE(state.flags,64);out.write(state.type,72,'ascii');return state.statfsFails?-1:0;},
    acl_init(count){state.calls.push(['acl_init',count]);return state.aclInitNull?null:100n;},
    acl_valid(ptr){state.calls.push(['acl_valid',ptr]);return (ptr===200n?state.parentAclInvalid:state.aclInvalid)?-1:0;},
    acl_set_fd_np(fd,ptr,type){state.calls.push(['acl_set',fd,ptr,type]);return state.aclSetFails?-1:0;},
    acl_get_fd_np(fd,type){state.calls.push(['acl_get',fd,type]);if(state.aclNull){state.errno=state.aclNullErrno??2;return null;}return 101n;},
    acl_get_link_np(name,type){state.calls.push(['acl_get_link',name,type]);state.aclParentIndex=0;
      if(state.parentAclNull){state.errno=state.parentAclNullErrno??2;return null;}return 200n;},
    acl_get_entry(ptr,which,entry){state.calls.push(['acl_entry',ptr,which]);
      if(ptr===200n){if(state.parentAclEntry&&state.aclParentIndex++===0){entry.writeBigUInt64LE(777n);return 0;}state.errno=22;return -1;}
      if(state.aclEntry){state.errno=0;return 0;}state.errno=state.aclEndErrno??22;return -1;},
    acl_get_tag_type(ptr,out){assert.equal(ptr,777n);out.writeUInt32LE(state.parentAclTag??1);return 0;},
    acl_get_permset_mask_np(ptr,out){assert.equal(ptr,777n);out.writeBigUInt64LE(state.parentAclMask??4n);return 0;},
    acl_free(ptr){state.calls.push(['acl_free',ptr]);return 0;},
    clearErrno(){state.errno=0;},errno(){return state.errno;},
  };
  async function run(file,args,opts){state.calls.push(['ps',file,args,opts]);state.scan++;
    if(state.psFails)throw new Error('PRIVATE_TEST_PATH');
    if(state.secondBrowser&&state.scan===2)return {stdout:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n'};
    return {stdout:state.processes.join('\n')};}
  return {state,original,adapter:create({platform:'darwin',arch:'arm64',uid:()=>501,fs,native,execFile:run,randomBytes:()=>Buffer.alloc(12,7)})};
}
test('unsupported OS, architecture and root stop before native use',async()=>{
  await rejects(()=>create({platform:'linux',arch:'x64',uid:()=>501}).assertBrowserClosed(),'MAC_UNSUPPORTED');
  await rejects(()=>create({platform:'darwin',arch:'ia32',uid:()=>501}).assertBrowserClosed(),'MAC_UNSUPPORTED');
  await rejects(()=>create({platform:'darwin',arch:'arm64',uid:()=>0}).assertBrowserClosed(),'MAC_UNSUPPORTED');
  await rejects(()=>create({platform:'darwin',arch:'arm64',uid:()=>501,euid:()=>0}).assertBrowserClosed(),'MAC_UNSUPPORTED');
});
test('Darwin flock uses authoritative 24-byte ABI and whole-file read lock',()=>{
  const value=flock(1);assert.equal(value.length,24);assert.equal(value.readBigInt64LE(0),0n);
  assert.equal(value.readBigInt64LE(8),0n);assert.equal(value.readInt32LE(16),0);
  assert.equal(value.readInt16LE(20),1);assert.equal(value.readInt16LE(22),0);
});
test('absolute POSIX profile path preserves spaces and rejects traversal, UNC-like and control input',()=>{
  assert.equal(localPath('/Users/test/Library/Application Support/Google/Chrome/Profile 1'),'/Users/test/Library/Application Support/Google/Chrome/Profile 1');
  for(const value of ['relative','//server/share','/Users/../other','/Users/./test','/x\0y','/x\ny'])assert.throws(()=>localPath(value),e=>e.code==='SOURCE_PATH_UNSAFE');
  for(const value of ['/'+('я'.repeat(128)),('/'+('a'.repeat(255))).repeat(5)])assert.throws(()=>localPath(value),e=>e.code==='SOURCE_PATH_UNSAFE');
});
test('ps command inspects executable names only; browser variants and helpers are refused',async()=>{
  for(const name of ['Google Chrome','Google Chrome Helper (Renderer)','Google Chrome Beta','Yandex','Chromium']){
    const f=fixture({processes:['/Applications/x.app/Contents/MacOS/'+name]});
    await rejects(()=>f.adapter.assertBrowserClosed(),'BROWSER_RUNNING');
    const call=f.state.calls.find(x=>x[0]==='ps');assert.equal(call[1],'/bin/ps');assert.deepEqual(call[2],['-A','-ww','-o','comm=']);
    assert.equal(f.state.calls.filter(x=>x[0]==='open').length,0);
  }
  for(const settings of [{psFails:true},{processes:[]}]){const f=fixture(settings);await rejects(()=>f.adapter.assertBrowserClosed(),'BROWSER_CHECK_FAILED');}
  const browserCrashpad=fixture({processes:['/Applications/Google Chrome.app/Contents/Frameworks/Crashpad/chrome_crashpad_handler']});
  await rejects(()=>browserCrashpad.adapter.assertBrowserClosed(),'BROWSER_RUNNING');
  const electronCrashpad=fixture({processes:['/Applications/Discord.app/Contents/Frameworks/Electron Framework.framework/Helpers/chrome_crashpad_handler']});
  await electronCrashpad.adapter.assertBrowserClosed();
});
test('existing LOCK has one O_RDONLY|O_NOFOLLOW FD held through awaited copy and hash',async()=>{
  const f=fixture();const result=await f.adapter.withSourceLock(f.original,async()=>{
    assert(f.state.fdOpen&&f.state.held);await Promise.resolve();assert(f.state.held);return 'verified-copy';});
  assert.equal(result,'verified-copy');assert(!f.state.held&&!f.state.fdOpen);assert.equal(f.state.scan,2);
  const opens=f.state.calls.filter(x=>x[0]==='open');assert.deepEqual(opens,[['open',f.original+'/LOCK',constants.O_RDONLY|constants.O_NOFOLLOW]]);
  assert.equal(f.state.calls.filter(x=>x[0]==='close').length,1);
  assert.equal(f.state.calls.filter(x=>['chmod','mkdir','acl_set'].includes(x[0])).length,0);
});
test('held source guard is non-reentrant and core callback errors remain caller-owned',async()=>{
  const f=fixture();await f.adapter.withSourceLock(f.original,async()=>{
    await rejects(()=>f.adapter.withSourceLock(f.original,async()=>{}),'SOURCE_INVALID');assert(f.state.held);
    await rejects(()=>f.adapter.withSourceLock(f.original,async()=>{}),'SOURCE_INVALID');assert(f.state.held);});
  const g=fixture(),sentinel=Object.assign(new Error('fixed-safe-code'),{code:'fixture'});
  await assert.rejects(()=>g.adapter.withSourceLock(g.original,async()=>{throw sentinel;}),e=>e===sentinel);
  assert(!g.state.held&&!g.state.fdOpen);
});
test('concurrent guard is reserved synchronously before the initial browser check',async()=>{
  const f=fixture();const first=f.adapter.withSourceLock(f.original,async()=>true);
  await rejects(()=>f.adapter.withSourceLock(f.original,async()=>assert.fail()),'SOURCE_INVALID');
  assert.equal(await first,true);assert.equal(f.state.calls.filter(x=>x[0]==='open').length,1);
});
test('guard remains reserved until asynchronous LOCK close is confirmed',async()=>{
  let releaseClose,enteredClose;
  const closed=new Promise(resolve=>{enteredClose=resolve;});
  const f=fixture({closeWait:new Promise(resolve=>{releaseClose=resolve;}),closeEntered:enteredClose});
  const first=f.adapter.withSourceLock(f.original,async()=>true);await closed;
  await rejects(()=>f.adapter.withSourceLock(f.original,async()=>assert.fail()),'SOURCE_INVALID');
  assert.equal(f.state.calls.filter(x=>x[0]==='open').length,1);releaseClose();assert.equal(await first,true);
});
test('missing or busy LOCK prevents callbacks without creating source files',async()=>{
  for(const settings of [{busy:true},{entries:['CURRENT','MANIFEST-000001']}]){
    const f=fixture(settings);let entered=false;await rejects(()=>f.adapter.withSourceLock(f.original,async()=>{entered=true;}),'SOURCE_LOCK_UNAVAILABLE');
    assert(!entered&&!f.state.held&&!f.state.fdOpen);assert(!f.state.created);
  }
});
test('symlinks, shared parents, foreign-owned files, hardlinks, nonlocal and unsupported volumes fail closed',async()=>{
  for(const mode of ['parentlink','entrylink','subdirectory','foreign','hardlink','shared','network','filesystem','realpath','ignoreowners']){
    const f=fixture();
    if(mode==='parentlink')f.state.directories.get('/Users/test/profile').isSymbolicLink=()=>true;
    if(mode==='entrylink')f.state.entries.push('linked');if(mode==='subdirectory')f.state.entries.push('folder');
    if(mode==='foreign')f.state.files.get(f.original+'/CURRENT').uid=502;
    if(mode==='hardlink')f.state.files.get(f.original+'/LOCK').nlink=2;
    if(mode==='shared')f.state.directories.get('/Users/test/profile').mode=0o40777;
    if(mode==='network')f.state.flags=0;if(mode==='filesystem')f.state.type='nfs';
    if(mode==='ignoreowners')f.state.flags|=0x00200000;
    if(mode==='realpath')f.state.realpathOverride='/other';
    await rejects(()=>f.adapter.withSourceLock(f.original,async()=>assert.fail()),'SOURCE_PATH_UNSAFE');
    assert(!f.state.fdOpen&&!f.state.held);
  }
});
test('source lock identity substitution and browser restart refuse callback; guard still closes',async()=>{
  for(const settings of [{openedIdentityOverride:{ino:'changed'}},{secondBrowser:true}]){
    const f=fixture(settings);await rejects(()=>f.adapter.withSourceLock(f.original,async()=>assert.fail()),settings.secondBrowser?'BROWSER_RUNNING':'SOURCE_PATH_UNSAFE');
    assert(!f.state.held&&!f.state.fdOpen);assert.equal(f.state.calls.filter(x=>x[0]==='close').length,1);
  }
});
test('native open and close failures have fixed safe codes',async()=>{
  const f=fixture({openThrows:true});await rejects(()=>f.adapter.withSourceLock(f.original,async()=>{}),'SOURCE_INVALID');
  const g=fixture({closeFails:true});await rejects(()=>g.adapter.withSourceLock(g.original,async()=>{}),'SOURCE_LOCK_RELEASE_FAILED');
});
test('new private directory gets empty Darwin ACL and0700 before returning; source ACL untouched',async()=>{
  const f=fixture();const result=await f.adapter.createPrivateDirectory('/Users/test/bundle','private-');
  assert.match(result,/^\/Users\/test\/bundle\/private-[0-9a-f]{24}$/);assert.equal(result,f.state.created);
  assert.deepEqual(f.state.calls.find(x=>x[0]==='mkdir').slice(2),[{mode:0o700}]);
  assert.deepEqual(f.state.calls.find(x=>x[0]==='acl_set'),['acl_set',81,100n,0x100]);
  assert.deepEqual(f.state.calls.find(x=>x[0]==='acl_entry'&&x[1]===101n),['acl_entry',101n,0]);
  assert.deepEqual(f.state.calls.filter(x=>x[0]==='chmod'),[['chmod',result,0o700]]);
  assert.deepEqual(f.state.calls.filter(x=>x[0]==='acl_free'&&x[1]!==200n).map(x=>x[1]),[101n,100n]);
});
test('ACL entry found, unverifiable null, invalid ACL and failed set are rejected',async()=>{
  for(const settings of [{aclEntry:true},{aclNull:true,aclNullErrno:13},{aclInvalid:true},{aclSetFails:true},{aclInitNull:true},{aclEndErrno:13}]){
    const f=fixture(settings);await rejects(()=>f.adapter.createPrivateDirectory('/Users/test/bundle','private-'),'PRIVATE_ACL_UNAVAILABLE');
    assert.equal(f.state.calls.filter(x=>x[0]==='close').length,1);
  }
  const empty=fixture({aclNull:true,aclNullErrno:2});assert(await empty.adapter.createPrivateDirectory('/Users/test/bundle','private-'));
});
test('existing ancestor ACLs are read-only checked and dangerous allow entries cannot replace private directories',async()=>{
  for(const settings of [{parentAclEntry:true},{parentAclEntry:true,parentAclMask:64n},
      {parentAclEntry:true,parentAclMask:1n<<40n},
      {parentAclNull:true,parentAclNullErrno:13},{parentAclInvalid:true}]){
    const f=fixture(settings);await rejects(()=>f.adapter.createPrivateDirectory('/Users/test/bundle','private-'),'SOURCE_PATH_UNSAFE');
    assert(!f.state.created);assert(!f.state.calls.some(x=>x[0]==='acl_set'||x[0]==='chmod'));
  }
  for(const settings of [{parentAclEntry:true,parentAclTag:2},{parentAclEntry:true,parentAclMask:2n},{parentAclNull:true,parentAclNullErrno:2}]){
    const f=fixture(settings);assert(await f.adapter.createPrivateDirectory('/Users/test/bundle','private-'));
    assert(f.state.calls.filter(x=>x[0]==='acl_set').every(x=>x[1]===81));
  }
});
test('read-only private volume, shared parent and repeated directory collisions do not modify existing paths',async()=>{
  for(const mode of ['readonly','shared','collision']){
    const f=fixture();if(mode==='readonly')f.state.flags|=1;if(mode==='shared')f.state.directories.get('/Users/test/bundle').mode=0o40777;
    if(mode==='collision')f.state.collision=true;
    await rejects(()=>f.adapter.createPrivateDirectory('/Users/test/bundle','private-'),mode==='collision'?'PRIVATE_DIRECTORY_FAILED':'SOURCE_PATH_UNSAFE');
    assert(!f.state.created);assert(!f.state.calls.some(x=>x[0]==='acl_set'||x[0]==='chmod'));
  }
});
test('production native binding is variadic, uses system lib only, and core never opens source LOCK',()=>{
  const fs=require('node:fs');const adapter=fs.readFileSync(require.resolve('../tools/offline_queue/macos.cjs'),'utf8');
  assert(adapter.includes("lib.func('int fcntl(int fd, int command, ...)')"));assert(adapter.includes("'/usr/lib/libSystem.B.dylib'"));
  const capture=fs.readFileSync(require.resolve('../tools/offline_queue/capture.cjs'),'utf8');
  const expression=capture.match(/const SOURCE_FILE = (\/.*\/);/)?.[1];assert(expression);
  const filter=Function('return '+expression)();assert(!filter.test('LOCK'));assert(filter.test('CURRENT'));
});

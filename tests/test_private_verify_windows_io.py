"""Windows verifier IO contracts with explicit native API doubles.

These are not native Windows acceptance and never inspect a browser profile.
The same JS reader/writer/security-descriptor logic runs against fixed synthetic
handles, identities, file bytes and SID values.
"""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');
const api=require('./tools/private_verify/windows-io.cjs');
const mode=process.argv[1], SID='S-1-5-21-42';
const SOURCE='C:\\synthetic\\inputs\\01.json', OUT='C:\\synthetic\\private';
const clean=p=>p.startsWith('\\\\?\\')?p.slice(4):p;
function fixture(change={}){
 const state={nextHandle:100n,nextId:20,calls:[],handles:new Map(),files:new Map(),last:122,
   acl:'O:'+SID+'D:P(A;OICI;FA;;;'+SID+')(A;OICI;FA;;;SY)',...change};
 const file=(p,bytes,options={})=>state.files.set(p,{bytes:Buffer.from(bytes),id:state.nextId++,version:1,attrs:32,links:1,...options});
 for(const p of ['C:\\','C:\\synthetic','C:\\synthetic\\inputs',OUT])file(p,'',{attrs:16});
 file(SOURCE,'{"fictional":true}');
 const current=h=>{const item=state.handles.get(h);assert(item,'unknown handle');return {item,f:state.files.get(item.path)};};
 function sidBytes(value){
  const aliases={LA:SID,SY:'S-1-5-18',BA:'S-1-5-32-544',WD:'S-1-1-0',BU:'S-1-5-32-545'};
  value=aliases[value]??value;const parts=value.split('-').slice(1).map(BigInt),b=Buffer.alloc(8+4*(parts.length-2));
  b[0]=Number(parts[0]);b[1]=parts.length-2;let authority=parts[1];for(let i=7;i>=2;i--){b[i]=Number(authority&255n);authority>>=8n;}
  for(let i=2;i<parts.length;i++)b.writeUInt32LE(Number(parts[i]),8+4*(i-2));return b;
 }
 const sid=sidBytes(SID),aces=()=>state.acl.match(/\([^()]*\)/g)??[];
 function nativeSid(pointer){if(pointer===1000n)return sid;
  if(pointer===300n)return sidBytes(/^O:([^:()]+)D:/.exec(state.acl)?.[1]??'BA');
  if(pointer>=5008n&&(pointer-5008n)%1000n===0n){const index=Number((pointer-5008n)/1000n);return sidBytes(aces()[index].slice(1,-1).split(';')[5]);}
  assert.fail('unknown SID pointer');}
 const native={
  systemDirectory:'C:\\Windows\\System32',
  GetDriveTypeW(root){state.calls.push(['drive',root]);return state.remote?4:3;},
  GetFileAttributesW(p){const f=state.files.get(clean(p));return f?f.attrs:0xffffffff;},
  CreateFileW(p,rights,share,security,creation,flags,template){
   const name=clean(p);state.calls.push(['open',name,rights,share,security,creation,flags,template]);
   if(state.openThrows)throw Error('SECRET-PRIVATE-PATH');
   if(state.openFails)return 0xffffffffffffffffn;
   if(creation===1){if(state.files.has(name))return 0xffffffffffffffffn;file(name,'');}
   if(!state.files.has(name))return 0xffffffffffffffffn;
   const h=state.nextHandle++;state.handles.set(h,{path:name,offset:0,rights,share});return h;
  },
  GetFileType(h){return state.nonDisk?3:1;},
  GetFileInformationByHandle(h,b){const {f}=current(h);b.fill(0);b.writeUInt32LE(f.attrs,0);b.writeBigUInt64LE(1n,4);
   b.writeBigUInt64LE(BigInt(f.version),20);b.writeUInt32LE(7,28);b.writeUInt32LE(Math.floor(f.bytes.length/2**32),32);
   b.writeUInt32LE(f.bytes.length>>>0,36);b.writeUInt32LE(f.links,40);b.writeUInt32LE(0,44);b.writeUInt32LE(f.id,48);return 1;},
  GetFileInformationByHandleEx(h,kind,b,size){const {f}=current(h);assert.equal(size,b.length);b.fill(0);
   if(kind===9)b.writeUInt32LE(state.tagReparse?f.attrs|0x400:f.attrs,0);
   else {assert.equal(kind,0);assert.equal(size,40);b.writeBigUInt64LE(1n,0);b.writeBigUInt64LE(BigInt(f.version),16);
    b.writeBigUInt64LE(BigInt(f.version),24);b.writeUInt32LE(f.attrs,32);}return 1;},
  GetFinalPathNameByHandleW(h,b,size,flags){const {item}=current(h);assert.equal(flags,0);const name=state.canonical??('\\\\?\\'+item.path);
   assert(size>name.length);b.write(name,0,'utf16le');return name.length;},
  ReadFile(h,b,count,out,overlap){assert.equal(overlap,null);const {item,f}=current(h);state.calls.push(['read',item.path,count]);
   if(state.readFails)return 0;let n=Math.min(count,f.bytes.length-item.offset);if(state.shortRead)n=0;
   f.bytes.copy(b,0,item.offset,item.offset+n);item.offset+=n;out.writeUInt32LE(n,0);
   if(state.mutateOnRead&&n){f.version++;state.mutateOnRead=false;}
   if(state.growOnRead&&n){f.bytes=Buffer.concat([f.bytes,Buffer.from('x')]);state.growOnRead=false;}
   return 1;},
  WriteFile(h,b,count,out,overlap){assert.equal(overlap,null);const {item,f}=current(h);state.calls.push(['write',item.path,count]);
   if(state.writeFails)return 0;const n=state.partialWrite?Math.min(3,count):count;
   f.bytes=Buffer.concat([f.bytes,b.subarray(0,n)]);item.offset+=n;f.version++;out.writeUInt32LE(n);return 1;},
  FlushFileBuffers(h){state.calls.push(['flush',h]);return !state.flushFails;},
  CloseHandle(h){state.calls.push(['close',h]);if(h===50n)return 1;const {item,f}=current(h);
   state.handles.delete(h);if(item.rights&0x40000000){if(state.finalizeTime)f.version++;
    if(state.replaceOnClose)f.id++;if(state.corruptOnClose)f.bytes[0]^=1;}
   return !state.closeFails;},
  GetLastError(){return 122;},GetCurrentProcess(){return 0xffffffffffffffffn;},
  OpenProcessToken(process,rights,out){assert.equal(rights,8);out.writeBigUInt64LE(50n);return 1;},
  GetTokenInformation(token,kind,out,size,needed){assert.equal(kind,1);needed.writeUInt32LE(32);
   if(!out)return 0;out.writeBigUInt64LE(1000n);return 1;},
  GetLengthSid(p){return nativeSid(p).length;},CopySid(length,out,p){assert.equal(length,nativeSid(p).length);nativeSid(p).copy(out);return 1;},
  GetSecurityInfo(h,type,flags,owner,group,dacl,sacl,descriptor){assert.equal(current(h).f.attrs,16);assert.equal(type,1);assert.equal(flags,5);
   owner.writeBigUInt64LE(300n);dacl.writeBigUInt64LE(state.nullDacl?0n:400n);descriptor.writeBigUInt64LE(200n);return state.securityFails?5:0;},
  GetSecurityDescriptorControl(sd,out,revision){assert.equal(sd,200n);out.writeUInt16LE(state.acl.includes('D:P')?0x1004:4);revision.writeUInt32LE(1);return 1;},
  GetAclInformation(acl,out,size,kind){assert.equal(acl,400n);assert.equal(size,12);assert.equal(kind,2);const list=aces();out.writeUInt32LE(list.length,0);
   out.writeUInt32LE(8+list.reduce((n,ace)=>n+8+sidBytes(ace.slice(1,-1).split(';')[5]).length,0),4);return 1;},
  GetAce(acl,index,out){assert.equal(acl,400n);out.writeBigUInt64LE(5000n+1000n*BigInt(index));return 1;},
  copyBytes(pointer,length){assert.equal(length,8);const index=Number((pointer-5000n)/1000n),fields=aces()[index].slice(1,-1).split(';');
   const flags=fields[1].match(/../g)??[],b=Buffer.alloc(8);b[0]=fields[0]==='A'?0:1;
   b[1]=(flags.includes('OI')?1:0)|(flags.includes('CI')?2:0)|(flags.includes('IO')?8:0);
   b.writeUInt16LE(8+sidBytes(fields[5]).length,2);b.writeUInt32LE(/^(?:FA|0x1f01ff)$/i.test(fields[2])?0x1f01ff:0x120089,4);return b;},
  LocalFree(p){state.calls.push(['free',p]);return null;},
 };
 const io=api._createAdapterForTests({platform:'win32',arch:'x64',native,
  loadPrivateAdapter:()=>({async createPrivateDirectory(parent,prefix){state.calls.push(['create-private',parent,prefix]);
   const created=path.win32.join(parent,prefix+'synthetic');file(created,'',{attrs:16});return created;}})});
 return {io,state,file,native};
}
function rejects(action,code){assert.throws(action,e=>e.name==='WindowsIOError'&&e.code===code&&e.message===code&&!String(e.stack).includes('SECRET-PRIVATE-PATH'));}
async function rejectsAsync(action,code){await assert.rejects(action,e=>e.name==='WindowsIOError'&&e.code===code&&e.message===code&&!String(e.stack).includes('SECRET-PRIVATE-PATH'));}
(async()=>{
 if(mode==='read-contract'){
  const f=fixture(),proof=f.io.inspectInput(SOURCE);assert.equal(proof.stat.size,18n);assert.equal(typeof proof.identity,'string');
  assert(f.io.unchangedInput(proof));assert.equal(f.io.readInput(proof).toString(),'{"fictional":true}');
  for(const call of f.state.calls.filter(x=>x[0]==='open'))assert.deepEqual(call.slice(2),[0x80000000,1,null,3,0x00200000,null]);
  assert.equal(f.state.handles.size,0);assert.equal(f.state.calls.filter(x=>x[0]==='write').length,0);
 }else if(mode==='paths'){
  for(const name of ['\\\\host\\share\\file.json','\\\\?\\C:\\a.json','C:\\synthetic\\inputs\\01.json:ads','C:\\synthetic\\..\\01.json',
   'C:\\synthetic\\inputs\\con.json','C:\\synthetic\\inputs\\01.json.','C:\\synthetic\\inputs\\01.json ','C:/synthetic/01.json','C:\\synthetic\\\\01.json']){
    const f=fixture();rejects(()=>f.io.inspectInput(name),'input-path-unsafe');assert.equal(f.state.calls.filter(x=>x[0]==='open').length,0);}
  const f=fixture();assert.equal(api._localPathForTests('C:\\literal $() `name`\\one.json'),'C:\\literal $() `name`\\one.json');
 }else if(mode==='reparse-network-canonical'){
  for(const change of ['parent','leaf','tag','network','canonical','non-disk','hard-link']){
   const f=fixture();let code='input-path-unsafe';
   if(change==='parent')f.state.files.get('C:\\synthetic').attrs|=0x400;
   if(change==='leaf')f.state.files.get(SOURCE).attrs|=0x400;
   if(change==='tag')f.state.tagReparse=true;
   if(change==='network')f.state.remote=true;
   if(change==='canonical')f.state.canonical='\\\\?\\C:\\other\\file.json';
   if(change==='non-disk'){f.state.nonDisk=true;code='input-file-invalid';}
   if(change==='hard-link'){f.state.files.get(SOURCE).links=2;code='input-file-invalid';}
   rejects(()=>f.io.inspectInput(SOURCE),code);assert.equal(f.state.handles.size,0);
   if(['parent','leaf','network'].includes(change))assert.equal(f.state.calls.filter(x=>x[0]==='open').length,0);
  }
 }else if(mode==='bounds'){
  for(const bytes of ['', 'x'.repeat(20)]){const f=fixture();f.file(SOURCE,bytes);rejects(()=>f.io.inspectInput(SOURCE,19),'input-file-size-limit');}
  const f=fixture();for(const limit of [0,-1,1.5,160*1024*1024+1])rejects(()=>f.io.inspectInput(SOURCE,limit),'input-file-size-limit');
  const big=Buffer.alloc(33*1024*1024,7);f.file(SOURCE,big);rejects(()=>f.io.inspectInput(SOURCE),'input-file-size-limit');
  assert.deepEqual(f.io.readCodeFileSync(SOURCE,big.length),big);
 }else if(mode==='replacement-and-change'){
  for(const change of ['id','version','same-size-bytes']){const f=fixture(),proof=f.io.inspectInput(SOURCE),file=f.state.files.get(SOURCE);
   if(change==='id')file.id++;else file.version++;
   if(change==='same-size-bytes')file.bytes[0]^=1;
   rejects(()=>f.io.unchangedInput(proof),'input-file-changed');rejects(()=>f.io.readInput(proof),'input-file-changed');assert.equal(f.state.handles.size,0);}
  for(const option of ['mutateOnRead','growOnRead','shortRead']){const f=fixture(),proof=f.io.inspectInput(SOURCE);f.state[option]=true;
   rejects(()=>f.io.readInput(proof),'input-file-changed');assert.equal(f.state.handles.size,0);}
 }else if(mode==='safe-errors'){
  for(const option of ['openThrows','openFails']){const f=fixture({[option]:true});rejects(()=>f.io.inspectInput(SOURCE),'input-file-read-failed');}
  const f=fixture(),proof=f.io.inspectInput(SOURCE);f.state.readFails=true;rejects(()=>f.io.readInput(proof),'input-file-read-failed');
  const g=fixture({closeFails:true});rejects(()=>g.io.inspectInput(SOURCE),'input-file-close-failed');
 }else if(mode==='platform'){
  for(const [platform,arch] of [['linux','x64'],['win32','arm64'],['darwin','x64']]){
   const io=api._createAdapterForTests({platform,arch});rejects(()=>io.assertPlatform(),'unsupported-owner-runtime');
   rejects(()=>io.inspectInput(SOURCE),'unsupported-owner-runtime');}
  const f=fixture();assert(f.io.assertPlatform());assert.equal(f.io.getSystemDirectory(),'C:\\Windows\\System32');
 }else if(mode==='private-acl'){
  const f=fixture();assert(f.io.verifyPrivateDirectory(OUT));assert.equal(f.state.handles.size,0);
  assert(f.state.calls.some(x=>x[0]==='free'&&x[1]===200n));
  const valid=['O:'+SID+'D:PAI(A;CIOI;0x1f01ff;;;S-1-5-18)(A;CIOI;FA;;;'+SID+')',
   'O:LAD:P(A;OICI;FA;;;LA)(A;OICI;FA;;;SY)'];
  for(const acl of valid)assert(fixture({acl}).io.verifyPrivateDirectory(OUT));
  const invalid=[f.state.acl.replace('D:P','D:'),f.state.acl.replace('O:'+SID,'O:BA'),f.state.acl+'(A;OICI;FA;;;BU)',
   f.state.acl.replace(';;;SY',';;;WD'),f.state.acl.replace('OICI','OICIIO'),f.state.acl.replace('FA','FR'),
   f.state.acl.replace('A;OICI','D;OICI'),f.state.acl.replace(';;;SY',';;;'+SID)];
  for(const acl of invalid){const g=fixture({acl});rejects(()=>g.io.verifyPrivateDirectory(OUT),'private-directory-failed');assert.equal(g.state.handles.size,0);}
  for(const option of ['securityFails','nullDacl'])rejects(()=>fixture({[option]:true}).io.verifyPrivateDirectory(OUT),'private-directory-failed');
 }else if(mode==='create-private'){
  const f=fixture();assert.equal(await f.io.createPrivateDirectory('C:\\synthetic','PRIVATE-verification-'),'C:\\synthetic\\PRIVATE-verification-synthetic');
  assert(f.state.calls.some(x=>x[0]==='create-private'));assert.equal(f.state.handles.size,0);
  const g=fixture({acl:'O:BA D:'});await rejectsAsync(()=>g.io.createPrivateDirectory('C:\\synthetic','PRIVATE-verification-'),'private-directory-failed');
 }else if(mode==='private-write'){
  const f=fixture({partialWrite:true,finalizeTime:true}),bytes=Buffer.from('private fictional bytes');
  assert(await f.io.writePrivate(OUT,'verification-report.json',bytes));assert.deepEqual(f.state.files.get(OUT+'\\verification-report.json').bytes,bytes);
  const write=f.state.calls.find(x=>x[0]==='open'&&x[2]===0xc0000000);assert.deepEqual(write.slice(2),[0xc0000000,0,null,1,0x80|0x00200000,null]);
  assert(f.state.calls.some(x=>x[0]==='flush'));assert(f.state.calls.some(x=>x[0]==='read'&&x[1]===OUT+'\\verification-report.json'));
  assert.equal(f.state.handles.size,0);await rejectsAsync(()=>f.io.writePrivate(OUT,'verification-report.json',bytes),'private-output-failed');
 }else if(mode==='private-races'){
  for(const option of ['replaceOnClose','corruptOnClose']){const f=fixture({[option]:true});
   await rejectsAsync(()=>f.io.writePrivate(OUT,'result.json',Buffer.from('fictional')),'private-output-changed');assert.equal(f.state.handles.size,0);}
  for(const option of ['writeFails','flushFails']){const f=fixture({[option]:true});
   await rejectsAsync(()=>f.io.writePrivate(OUT,'result.json',Buffer.from('fictional')),'private-output-failed');assert.equal(f.state.handles.size,0);}
 }else if(mode==='private-write-validation'){
  for(const name of ['../secret.json','\\secret.json','result:ads.json','result.txt','Result.json']){
   const f=fixture();await rejectsAsync(()=>f.io.writePrivate(OUT,name,Buffer.from('fictional')),'private-output-failed');assert.equal(f.state.calls.length,0);}
  const f=fixture();await rejectsAsync(()=>f.io.writePrivate(OUT,'result.json',Buffer.alloc(0)),'private-output-failed');
  await rejectsAsync(()=>f.io.writePrivate(OUT,'result.json','string'),'private-output-failed');
 }else throw Error('unknown-test-mode');
 process.stdout.write(JSON.stringify({outcome:'passed',case:mode,native_windows_tested:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


class WindowsVerifierIOTests(unittest.TestCase):
    def run_case(self, case):
        result = subprocess.run(['node', '-e', HARNESS, case], cwd=ROOT,
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            'outcome':'passed', 'case':case, 'native_windows_tested':False})

    def test_reader_uses_existing_read_only_write_and_delete_denying_handle(self):
        self.run_case('read-contract')

    def test_device_unc_ads_reserved_and_ambiguous_paths_are_refused_before_open(self):
        self.run_case('paths')

    def test_reparse_network_hardlinks_and_final_path_mismatch_fail_closed(self):
        self.run_case('reparse-network-canonical')

    def test_file_and_explicit_code_asset_size_bounds(self):
        self.run_case('bounds')

    def test_file_identity_growth_partial_read_and_metadata_change_are_detected(self):
        self.run_case('replacement-and-change')

    def test_native_error_text_never_escapes_and_close_failure_is_reported(self):
        self.run_case('safe-errors')

    def test_runtime_and_known_system_directory_selection(self):
        self.run_case('platform')

    def test_actual_protected_directory_owner_and_complete_dacl_are_checked(self):
        self.run_case('private-acl')

    def test_private_creator_is_followed_by_actual_acl_verification(self):
        self.run_case('create-private')

    def test_new_private_file_flush_partial_writes_readback_and_no_overwrite(self):
        self.run_case('private-write')

    def test_private_file_replacement_corruption_write_and_flush_failures(self):
        self.run_case('private-races')

    def test_private_artifact_names_and_empty_or_unbounded_content(self):
        self.run_case('private-write-validation')


if __name__ == '__main__':
    unittest.main()

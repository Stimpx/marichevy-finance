'use strict';

// Owner-selected export files only. No profile discovery, browser/database IO,
// shell invocation or networking. The verified bootstrap loads this module
// only after checking the complete code/native-dependency closure.
const path = require('node:path');
const crypto = require('node:crypto');
const MAX_FILE = 32 * 1024 * 1024;
const C = Object.freeze({
  INVALID_HANDLE: 0xffffffffffffffffn, INVALID_ATTRIBUTES: 0xffffffff,
  GENERIC_READ: 0x80000000, GENERIC_WRITE: 0x40000000,
  READ_CONTROL: 0x00020000, FILE_READ_ATTRIBUTES: 0x80,
  FILE_SHARE_READ: 1, OPEN_EXISTING: 3, CREATE_NEW: 1,
  FILE_ATTRIBUTE_DIRECTORY: 0x10, FILE_ATTRIBUTE_REPARSE_POINT: 0x400,
  FILE_ATTRIBUTE_NORMAL: 0x80, FILE_FLAG_OPEN_REPARSE_POINT: 0x00200000,
  FILE_FLAG_BACKUP_SEMANTICS: 0x02000000,
  FILE_TYPE_DISK: 1, FILE_ATTRIBUTE_TAG_INFO: 9, FILE_BASIC_INFO: 0,
  TOKEN_QUERY: 8, TOKEN_USER: 1, ERROR_INSUFFICIENT_BUFFER: 122,
  OWNER_AND_DACL: 5, SE_FILE_OBJECT: 1, ACL_SIZE_INFORMATION: 2,
});
const CODES = new Set(['unsupported-owner-runtime', 'input-path-unsafe',
  'input-file-invalid', 'input-file-size-limit', 'input-file-changed',
  'input-file-read-failed', 'input-file-close-failed', 'private-directory-failed',
  'private-output-failed', 'private-output-changed']);
class WindowsIOError extends Error {
  constructor(code) {
    const safe = CODES.has(code) ? code : 'input-file-read-failed';
    super(safe); this.name = 'WindowsIOError'; this.code = safe;
  }
}
const fail = code => { throw new WindowsIOError(code); };
function invalidHandle(value) {
  return value == null || BigInt(value) === 0n || BigInt(value) === C.INVALID_HANDLE;
}
function localPath(value, {directory = false} = {}) {
  if (typeof value !== 'string' || value.length > 32700 || !/^[A-Za-z]:\\/.test(value) ||
      /[\x00-\x1f\x7f]/.test(value) || value.includes('/')) fail('input-path-unsafe');
  const parts = value.slice(3).split('\\');
  if (parts.some((part, index) => (!part && !(directory && parts.length === 1 && index === 0)) ||
      part === '.' || part === '..' || /[:<>"|?*]/.test(part) || /[. ]$/.test(part) ||
      /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))) fail('input-path-unsafe');
  if (path.win32.normalize(value) !== value || (!directory && value.length === 3)) fail('input-path-unsafe');
  return value;
}
const key = value => value.toLowerCase();
const nativePath = value => '\\\\?\\' + value;
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function loadNative() {
  try {
    const koffi = require('koffi');
    const kernel = koffi.load('kernel32.dll'); // Windows KnownDLL.
    const bind = (library, name, result, args) => library.func('__stdcall', name, result, args);
    const GetSystemDirectoryW = bind(kernel, 'GetSystemDirectoryW', 'uint32_t', ['void *', 'uint32_t']);
    const buffer = Buffer.alloc(65536), length = GetSystemDirectoryW(buffer, buffer.length / 2);
    if (!length || length >= buffer.length / 2) fail('unsupported-owner-runtime');
    const systemDirectory = localPath(buffer.subarray(0, length * 2).toString('utf16le'), {directory:true});
    const security = koffi.load(path.win32.join(systemDirectory, 'advapi32.dll'));
    return {
      systemDirectory,
      CreateFileW: bind(kernel, 'CreateFileW', 'void *', ['str16', 'uint32_t', 'uint32_t', 'void *', 'uint32_t', 'uint32_t', 'void *']),
      GetDriveTypeW: bind(kernel, 'GetDriveTypeW', 'uint32_t', ['str16']),
      GetFileAttributesW: bind(kernel, 'GetFileAttributesW', 'uint32_t', ['str16']),
      GetFileType: bind(kernel, 'GetFileType', 'uint32_t', ['void *']),
      GetFileInformationByHandle: bind(kernel, 'GetFileInformationByHandle', 'int32_t', ['void *', 'void *']),
      GetFileInformationByHandleEx: bind(kernel, 'GetFileInformationByHandleEx', 'int32_t', ['void *', 'uint32_t', 'void *', 'uint32_t']),
      GetFinalPathNameByHandleW: bind(kernel, 'GetFinalPathNameByHandleW', 'uint32_t', ['void *', 'void *', 'uint32_t', 'uint32_t']),
      ReadFile: bind(kernel, 'ReadFile', 'int32_t', ['void *', 'void *', 'uint32_t', 'void *', 'void *']),
      WriteFile: bind(kernel, 'WriteFile', 'int32_t', ['void *', 'void *', 'uint32_t', 'void *', 'void *']),
      FlushFileBuffers: bind(kernel, 'FlushFileBuffers', 'int32_t', ['void *']),
      CloseHandle: bind(kernel, 'CloseHandle', 'int32_t', ['void *']),
      GetLastError: bind(kernel, 'GetLastError', 'uint32_t', []),
      GetCurrentProcess: bind(kernel, 'GetCurrentProcess', 'void *', []),
      OpenProcessToken: bind(security, 'OpenProcessToken', 'int32_t', ['void *', 'uint32_t', 'void *']),
      GetTokenInformation: bind(security, 'GetTokenInformation', 'int32_t', ['void *', 'uint32_t', 'void *', 'uint32_t', 'void *']),
      GetLengthSid: bind(security, 'GetLengthSid', 'uint32_t', ['void *']),
      CopySid: bind(security, 'CopySid', 'int32_t', ['uint32_t', 'void *', 'void *']),
      GetSecurityInfo: bind(security, 'GetSecurityInfo', 'uint32_t', ['void *', 'uint32_t', 'uint32_t', 'void *', 'void *', 'void *', 'void *', 'void *']),
      GetSecurityDescriptorControl: bind(security, 'GetSecurityDescriptorControl', 'int32_t', ['void *', 'void *', 'void *']),
      GetAclInformation: bind(security, 'GetAclInformation', 'int32_t', ['void *', 'void *', 'uint32_t', 'uint32_t']),
      GetAce: bind(security, 'GetAce', 'int32_t', ['void *', 'uint32_t', 'void *']),
      LocalFree: bind(kernel, 'LocalFree', 'void *', ['void *']),
      copyBytes(pointer, length) { return Buffer.from(koffi.decode(pointer, 'uint8_t', length)); },
    };
  } catch (_) { fail('unsupported-owner-runtime'); }
}

function createAdapter(options = {}) {
  const platform = options.platform ?? process.platform, arch = options.arch ?? process.arch;
  let bindings = options.native, currentSid;
  const loadPrivateAdapter = options.loadPrivateAdapter ?? (() => require('./windows.cjs'));
  function assertPlatform() {
    if (platform !== 'win32' || arch !== 'x64') fail('unsupported-owner-runtime');
    return true;
  }
  function api() { assertPlatform(); if (!bindings) bindings = loadNative(); return bindings; }
  function getSystemDirectory() {
    return localPath(api().systemDirectory, {directory:true});
  }
  function attributes(filename) {
    const value = api().GetFileAttributesW(nativePath(filename));
    if (value === C.INVALID_ATTRIBUTES) fail('input-file-invalid');
    if (value & C.FILE_ATTRIBUTE_REPARSE_POINT) fail('input-path-unsafe');
    return value;
  }
  function checkParents(filename, directory = false) {
    localPath(filename, {directory});
    const root = path.win32.parse(filename).root;
    // Drive letters can identify mapped shares. Do not enumerate those.
    if (![2, 3, 6].includes(api().GetDriveTypeW(root))) fail('input-path-unsafe');
    if (!(attributes(root) & C.FILE_ATTRIBUTE_DIRECTORY)) fail('input-path-unsafe');
    const target = directory ? filename : path.win32.dirname(filename);
    let current = root;
    for (const component of target.slice(root.length).split('\\').filter(Boolean)) {
      current = path.win32.join(current, component);
      if (!(attributes(current) & C.FILE_ATTRIBUTE_DIRECTORY)) fail('input-path-unsafe');
    }
    return filename;
  }
  function canonical(handle) {
    const buffer = Buffer.alloc(65536);
    const length = api().GetFinalPathNameByHandleW(handle, buffer, buffer.length / 2, 0);
    if (!length || length >= buffer.length / 2) fail('input-path-unsafe');
    const name = buffer.subarray(0, length * 2).toString('utf16le');
    if (!name.startsWith('\\\\?\\') || /^\\\\\?\\UNC\\/i.test(name)) fail('input-path-unsafe');
    return localPath(name.slice(4), {directory:true});
  }
  function metadata(handle, filename, {directory = false, maxBytes = MAX_FILE} = {}) {
    const native = api(), info = Buffer.alloc(52), tag = Buffer.alloc(8), basic = Buffer.alloc(40);
    if (native.GetFileType(handle) !== C.FILE_TYPE_DISK || !native.GetFileInformationByHandle(handle, info) ||
        !native.GetFileInformationByHandleEx(handle, C.FILE_ATTRIBUTE_TAG_INFO, tag, tag.length) ||
        !native.GetFileInformationByHandleEx(handle, C.FILE_BASIC_INFO, basic, basic.length)) fail('input-file-invalid');
    const flags = info.readUInt32LE(0);
    if ((flags | tag.readUInt32LE(0) | basic.readUInt32LE(32)) & C.FILE_ATTRIBUTE_REPARSE_POINT) fail('input-path-unsafe');
    if (Boolean(flags & C.FILE_ATTRIBUTE_DIRECTORY) !== directory ||
        Boolean(tag.readUInt32LE(0) & C.FILE_ATTRIBUTE_DIRECTORY) !== directory ||
        Boolean(basic.readUInt32LE(32) & C.FILE_ATTRIBUTE_DIRECTORY) !== directory) fail('input-file-invalid');
    if (!directory && info.readUInt32LE(40) !== 1) fail('input-file-invalid');
    const size = (BigInt(info.readUInt32LE(32)) << 32n) | BigInt(info.readUInt32LE(36));
    if (!directory && (size <= 0n || size > BigInt(maxBytes))) fail('input-file-size-limit');
    if (key(canonical(handle)) !== key(filename)) fail('input-path-unsafe');
    const inode = info.readUInt32LE(28) + ':' + info.readUInt32LE(44) + ':' + info.readUInt32LE(48);
    const identity = [flags, info.subarray(4,12).toString('hex'), info.subarray(20,52).toString('hex'),
      basic.subarray(24,32).toString('hex')].join(':');
    return Object.freeze({filename, stat:Object.freeze({size}), identity, inode});
  }
  function close(handle, code = 'input-file-close-failed') {
    if (!invalidHandle(handle) && !api().CloseHandle(handle)) fail(code);
  }
  function openInput(filename, maxBytes, action) {
    let handle, thrown;
    try {
      checkParents(filename);
      if (attributes(filename) & C.FILE_ATTRIBUTE_DIRECTORY) fail('input-file-invalid');
      // OPEN_EXISTING + read-only + no write/delete sharing. The same handle
      // supplies identity and bytes and stays alive through the final checks.
      handle = api().CreateFileW(nativePath(filename), C.GENERIC_READ, C.FILE_SHARE_READ, null,
        C.OPEN_EXISTING, C.FILE_FLAG_OPEN_REPARSE_POINT, null);
      if (invalidHandle(handle)) fail('input-file-read-failed');
      const before = metadata(handle, filename, {maxBytes});
      checkParents(filename);
      const result = action(handle, before);
      const after = metadata(handle, filename, {maxBytes});
      if (before.identity !== after.identity) fail('input-file-changed');
      checkParents(filename);
      if (attributes(filename) & C.FILE_ATTRIBUTE_DIRECTORY) fail('input-file-changed');
      return result;
    } catch (error) {
      thrown = error;
      throw error instanceof WindowsIOError ? error : new WindowsIOError('input-file-read-failed');
    } finally {
      if (!invalidHandle(handle)) try { close(handle); } catch (error) { if (!thrown) throw error; }
    }
  }
  function inspectInput(filename, maxBytes = MAX_FILE) {
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 160 * 1024 * 1024) fail('input-file-size-limit');
    return openInput(filename, maxBytes, (_handle, proof) => proof);
  }
  function unchangedInput(proof) {
    if (!proof || typeof proof.filename !== 'string' || typeof proof.identity !== 'string') fail('input-file-changed');
    const fresh = inspectInput(proof.filename, proof.maxBytes ?? MAX_FILE);
    if (fresh.identity !== proof.identity || fresh.inode !== proof.inode || fresh.stat.size !== proof.stat?.size)
      fail('input-file-changed');
    return true;
  }
  function readBytes(handle, size) {
    const bytes = Buffer.alloc(Number(size));
    for (let offset = 0; offset < bytes.length;) {
      const count = Math.min(bytes.length - offset, 1024 * 1024), read = Buffer.alloc(4);
      if (!api().ReadFile(handle, bytes.subarray(offset, offset + count), count, read, null)) fail('input-file-read-failed');
      const actual = read.readUInt32LE(0);
      if (actual < 1 || actual > count) fail('input-file-changed');
      offset += actual;
    }
    const read = Buffer.alloc(4);
    if (!api().ReadFile(handle, Buffer.alloc(1), 1, read, null)) fail('input-file-read-failed');
    if (read.readUInt32LE(0) !== 0) fail('input-file-changed');
    return bytes;
  }
  function readInput(proof) {
    if (!proof || typeof proof.filename !== 'string') fail('input-file-changed');
    const maxBytes = proof.maxBytes ?? MAX_FILE;
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 160 * 1024 * 1024) fail('input-file-size-limit');
    return openInput(proof.filename, maxBytes, (handle, before) => {
      if (before.identity !== proof.identity || before.inode !== proof.inode || before.stat.size !== proof.stat?.size)
        fail('input-file-changed');
      return readBytes(handle, before.stat.size);
    });
  }
  function readCodeFileSync(filename, maxBytes) {
    const proof = inspectInput(filename, maxBytes);
    // Code assets can exceed the private-export limit. Keep the exact explicit
    // caller bound with the proof; identity and every other read guard remain.
    return readInput(Object.freeze({...proof, maxBytes}));
  }
  function copySid(pointer) {
    if (!pointer) fail('private-directory-failed');
    const native = api(), length = native.GetLengthSid(pointer);
    if (length < 8 || length > 68) fail('private-directory-failed');
    const sid = Buffer.alloc(length);
    if (!native.CopySid(sid.length, sid, pointer) || sid[0] !== 1 || sid[1] > 15 ||
        8 + 4 * sid[1] !== sid.length) fail('private-directory-failed');
    return sid;
  }
  function userSid() {
    if (currentSid) return currentSid;
    const native = api(); let token, thrown;
    try {
      const pointer = Buffer.alloc(8);
      if (!native.OpenProcessToken(native.GetCurrentProcess(), C.TOKEN_QUERY, pointer)) fail('private-directory-failed');
      token = pointer.readBigUInt64LE(0);
      if (invalidHandle(token)) fail('private-directory-failed');
      const length = Buffer.alloc(4);
      if (native.GetTokenInformation(token, C.TOKEN_USER, null, 0, length) ||
          native.GetLastError() !== C.ERROR_INSUFFICIENT_BUFFER) fail('private-directory-failed');
      const needed = length.readUInt32LE(0);
      if (needed < 16 || needed > 65536) fail('private-directory-failed');
      const info = Buffer.alloc(needed);
      if (!native.GetTokenInformation(token, C.TOKEN_USER, info, info.length, length)) fail('private-directory-failed');
      currentSid = copySid(info.readBigUInt64LE(0));
      return currentSid;
    } catch (error) { thrown = error; throw new WindowsIOError('private-directory-failed'); }
    finally { if (!invalidHandle(token)) try { close(token, 'private-directory-failed'); } catch (error) { if (!thrown) throw error; } }
  }
  function protectedAcl(handle) {
    const native = api(), descriptor = Buffer.alloc(8), owner = Buffer.alloc(8), dacl = Buffer.alloc(8);
    let sd;
    try {
      if (native.GetSecurityInfo(handle, C.SE_FILE_OBJECT, C.OWNER_AND_DACL, owner, null, dacl, null, descriptor) !== 0)
        fail('private-directory-failed');
      sd = descriptor.readBigUInt64LE(0);
      const acl = dacl.readBigUInt64LE(0), sid = userSid();
      if (!sd || !owner.readBigUInt64LE(0) || !acl || !copySid(owner.readBigUInt64LE(0)).equals(sid)) fail('private-directory-failed');
      const control = Buffer.alloc(2), revision = Buffer.alloc(4), info = Buffer.alloc(12);
      if (!native.GetSecurityDescriptorControl(sd, control, revision) || revision.readUInt32LE(0) !== 1 ||
          (control.readUInt16LE(0) & 0x1004) !== 0x1004 || // DACL_PRESENT + DACL_PROTECTED.
          !native.GetAclInformation(acl, info, info.length, C.ACL_SIZE_INFORMATION) || info.readUInt32LE(0) !== 2 ||
          info.readUInt32LE(4) < 8 || info.readUInt32LE(4) > 65536 || info.readUInt32LE(8) > 65536)
        fail('private-directory-failed');
      const trustees = new Set();
      const systemSid = Buffer.from('010100000000000512000000', 'hex'); // S-1-5-18.
      let used = 8;
      for (let index = 0; index < 2; index++) {
        const pointer = Buffer.alloc(8);
        if (!native.GetAce(acl, index, pointer) || !pointer.readBigUInt64LE(0)) fail('private-directory-failed');
        const ace = pointer.readBigUInt64LE(0), header = native.copyBytes(ace, 8);
        // Exactly ACCESS_ALLOWED_ACE, OI|CI inheritance, FILE_ALL_ACCESS; no
        // inherited/deny/object/conditional ACEs or extra principals. Compare
        // binary SIDs, avoiding locale and SDDL aliases such as LA or SY.
        if (!Buffer.isBuffer(header) || header.length !== 8 || header[0] !== 0 || header[1] !== 3 ||
            header.readUInt16LE(2) < 16 || header.readUInt16LE(2) > 76 ||
            header.readUInt32LE(4) !== 0x001f01ff) fail('private-directory-failed');
        const trusteeSid = copySid(ace + 8n);
        if (header.readUInt16LE(2) !== trusteeSid.length + 8) fail('private-directory-failed');
        used += header.readUInt16LE(2);
        const trustee = trusteeSid.equals(sid) ? 'owner' : trusteeSid.equals(systemSid) ? 'system' : 'other';
        if (trustee === 'other' || trustees.has(trustee)) fail('private-directory-failed');
        trustees.add(trustee);
      }
      if (used !== info.readUInt32LE(4)) fail('private-directory-failed');
      return true;
    } catch (_) { fail('private-directory-failed'); }
    finally { if (sd) native.LocalFree(sd); }
  }
  function verifyPrivateDirectory(directory) {
    let handle, thrown;
    try {
      checkParents(directory, true);
      handle = api().CreateFileW(nativePath(directory), C.READ_CONTROL | C.FILE_READ_ATTRIBUTES, C.FILE_SHARE_READ,
        null, C.OPEN_EXISTING, C.FILE_FLAG_OPEN_REPARSE_POINT | C.FILE_FLAG_BACKUP_SEMANTICS, null);
      if (invalidHandle(handle)) fail('private-directory-failed');
      const before = metadata(handle, directory, {directory:true});
      protectedAcl(handle);
      const after = metadata(handle, directory, {directory:true});
      if (before.identity !== after.identity) fail('private-directory-failed');
      checkParents(directory, true);
      return true;
    } catch (error) { thrown = error; throw new WindowsIOError('private-directory-failed'); }
    finally { if (!invalidHandle(handle)) try { close(handle, 'private-directory-failed'); } catch (error) { if (!thrown) throw error; } }
  }
  async function createPrivateDirectory(parent, prefix) {
    try {
      checkParents(parent, true);
      const directory = await loadPrivateAdapter().createPrivateDirectory(parent, prefix);
      verifyPrivateDirectory(directory);
      return directory;
    } catch (_) { fail('private-directory-failed'); }
  }
  async function writePrivate(directory, name, bytes) {
    if (typeof name !== 'string' || !/^[a-z][a-zA-Z0-9-]{0,63}\.(?:json|bin)$/.test(name) ||
        !(bytes instanceof Uint8Array) || bytes.byteLength < 1 || bytes.byteLength > MAX_FILE) fail('private-output-failed');
    let handle, thrown, proof;
    const filename = path.win32.join(directory, name);
    try {
      verifyPrivateDirectory(directory);
      handle = api().CreateFileW(nativePath(filename), (C.GENERIC_WRITE | C.GENERIC_READ) >>> 0, 0, null, C.CREATE_NEW,
        C.FILE_ATTRIBUTE_NORMAL | C.FILE_FLAG_OPEN_REPARSE_POINT, null);
      if (invalidHandle(handle)) fail('private-output-failed');
      for (let offset = 0; offset < bytes.byteLength;) {
        const count = Math.min(bytes.byteLength - offset, 1024 * 1024), written = Buffer.alloc(4);
        if (!api().WriteFile(handle, bytes.subarray(offset, offset + count), count, written, null)) fail('private-output-failed');
        const actual = written.readUInt32LE(0);
        if (actual < 1 || actual > count) fail('private-output-failed');
        offset += actual;
      }
      if (!api().FlushFileBuffers(handle)) fail('private-output-failed');
      proof = metadata(handle, filename);
      if (proof.stat.size !== BigInt(bytes.byteLength)) fail('private-output-changed');
    } catch (error) { thrown = error; throw new WindowsIOError(error?.code === 'private-output-changed' ? error.code : 'private-output-failed'); }
    finally { if (!invalidHandle(handle)) try { close(handle, 'private-output-failed'); } catch (error) { if (!thrown) throw error; } }
    try {
      verifyPrivateDirectory(directory);
      // Windows finalizes some last-write metadata when the writer closes.
      // Pin the file ID across that close, then use the fully settled proof for
      // readback. A replacement with identical content still has a different ID.
      const settled = inspectInput(filename);
      if (settled.inode !== proof.inode || settled.stat.size !== proof.stat.size) fail('private-output-changed');
      const readback = readInput(settled);
      if (sha(readback) !== sha(bytes)) fail('private-output-changed');
      verifyPrivateDirectory(directory);
    } catch (_) { fail('private-output-changed'); }
    return true;
  }
  return Object.freeze({assertPlatform, getSystemDirectory, inspectInput, unchangedInput, readInput,
    readCodeFileSync, createPrivateDirectory, verifyPrivateDirectory, writePrivate});
}

module.exports = Object.freeze({...createAdapter(), WindowsIOError, MAX_FILE,
  _createAdapterForTests:createAdapter, _localPathForTests:localPath});

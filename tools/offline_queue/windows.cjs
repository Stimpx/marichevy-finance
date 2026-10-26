'use strict';

// Windows x64 filesystem guards only. The LevelDB engine must open a clone,
// never this source directory. No shell, browser automation or network code.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

const C = Object.freeze({
  INVALID_HANDLE: 0xffffffffffffffffn, INVALID_ATTRIBUTES: 0xffffffff,
  GENERIC_READ: 0x80000000, OPEN_EXISTING: 3,
  FILE_ATTRIBUTE_DIRECTORY: 0x10, FILE_ATTRIBUTE_REPARSE_POINT: 0x400,
  FILE_FLAG_OPEN_REPARSE_POINT: 0x00200000,
  FILE_TYPE_DISK: 1, FILE_ATTRIBUTE_TAG_INFO: 9,
  SNAP_PROCESS: 2, ERROR_NO_MORE_FILES: 18, ERROR_INSUFFICIENT_BUFFER: 122,
  ERROR_ALREADY_EXISTS: 183, TOKEN_QUERY: 8, TOKEN_USER: 1,
  FILE_PERSISTENT_ACLS: 8, SDDL_REVISION: 1,
});
const MESSAGES = Object.freeze({
  WINDOWS_UNSUPPORTED: 'Нужна 64-разрядная Windows и версия программы для Windows x64.',
  WINDOWS_BINDINGS_UNAVAILABLE: 'Не удалось загрузить системный адаптер Windows. Используйте полный проверенный комплект программы.',
  BROWSER_RUNNING: 'Полностью закройте Google Chrome и Яндекс Браузер, включая фоновые процессы, и повторите запуск.',
  BROWSER_CHECK_FAILED: 'Не удалось проверить закрытие браузеров. Копирование остановлено.',
  SOURCE_PATH_UNSAFE: 'Путь должен вести в обычную локальную папку без ссылок, точек подключения и дополнительных потоков.',
  SOURCE_INVALID: 'Не удалось проверить исходную папку Local Storage. Копирование остановлено.',
  SOURCE_LOCK_UNAVAILABLE: 'Исходная база занята или её существующий LOCK недоступен. Закройте браузеры и повторите запуск.',
  SOURCE_LOCK_RELEASE_FAILED: 'Не удалось подтвердить закрытие защитного дескриптора. Завершите программу перед повторным запуском.',
  PRIVATE_ACL_UNAVAILABLE: 'Не удалось создать каталог с доступом только для текущего пользователя и SYSTEM. Нужна локальная файловая система с ACL.',
  PRIVATE_DIRECTORY_FAILED: 'Не удалось создать частный каталог для копии. Выберите другую обычную локальную папку.',
});

function failure(code) {
  const error = new Error(MESSAGES[code]);
  error.code = code;
  error.windowsAdapter = true;
  return error;
}
function mapped(error, fallback) {
  return error?.windowsAdapter && Object.hasOwn(MESSAGES, error.code) ? error : failure(fallback);
}
function invalidHandle(value) {
  return value == null || BigInt(value) === 0n || BigInt(value) === C.INVALID_HANDLE;
}
function localPath(value) {
  if (typeof value !== 'string' || value.length > 32700 || !/^[a-z]:[\\/]/i.test(value) || /[\x00-\x1f]/.test(value)) throw failure('SOURCE_PATH_UNSAFE');
  const parts = value.slice(3).split(/[\\/]/).filter(Boolean);
  if (parts.some(part => part === '.' || part === '..' || /[:<>"|?*]/.test(part) || /[. ]$/.test(part) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))) throw failure('SOURCE_PATH_UNSAFE');
  return path.win32.normalize(value);
}
// Add the long-path prefix internally only after rejecting UNC/device/ADS input.
const nativePath = value => '\\\\?\\' + value;

function loadNative() {
  try {
    const koffi = require('koffi');
    // kernel32 is a Windows KnownDLL. Resolve advapi32 from its actual System32,
    // rather than searching the portable application's working directory.
    const kernel = koffi.load('kernel32.dll');
    const bind = (library, name, result, args) => library.func('__stdcall', name, result, args);
    const GetSystemDirectoryW = bind(kernel, 'GetSystemDirectoryW', 'uint32_t', ['void *', 'uint32_t']);
    const systemBuffer = Buffer.alloc(65536);
    const systemLength = GetSystemDirectoryW(systemBuffer, systemBuffer.length / 2);
    if (!systemLength || systemLength >= systemBuffer.length / 2) throw failure('WINDOWS_BINDINGS_UNAVAILABLE');
    const systemDirectory = localPath(systemBuffer.subarray(0, systemLength * 2).toString('utf16le'));
    const security = koffi.load(path.win32.join(systemDirectory, 'advapi32.dll'));
    return {
      CreateToolhelp32Snapshot: bind(kernel, 'CreateToolhelp32Snapshot', 'void *', ['uint32_t', 'uint32_t']),
      Process32FirstW: bind(kernel, 'Process32FirstW', 'int32_t', ['void *', 'void *']),
      Process32NextW: bind(kernel, 'Process32NextW', 'int32_t', ['void *', 'void *']),
      GetLastError: bind(kernel, 'GetLastError', 'uint32_t', []),
      CloseHandle: bind(kernel, 'CloseHandle', 'int32_t', ['void *']),
      CreateFileW: bind(kernel, 'CreateFileW', 'void *', ['str16', 'uint32_t', 'uint32_t', 'void *', 'uint32_t', 'uint32_t', 'void *']),
      GetFileAttributesW: bind(kernel, 'GetFileAttributesW', 'uint32_t', ['str16']),
      GetDriveTypeW: bind(kernel, 'GetDriveTypeW', 'uint32_t', ['str16']),
      GetFileType: bind(kernel, 'GetFileType', 'uint32_t', ['void *']),
      GetFileInformationByHandleEx: bind(kernel, 'GetFileInformationByHandleEx', 'int32_t', ['void *', 'uint32_t', 'void *', 'uint32_t']),
      GetCurrentProcess: bind(kernel, 'GetCurrentProcess', 'void *', []),
      OpenProcessToken: bind(security, 'OpenProcessToken', 'int32_t', ['void *', 'uint32_t', 'void *']),
      GetTokenInformation: bind(security, 'GetTokenInformation', 'int32_t', ['void *', 'uint32_t', 'void *', 'uint32_t', 'void *']),
      GetLengthSid: bind(security, 'GetLengthSid', 'uint32_t', ['void *']),
      CopySid: bind(security, 'CopySid', 'int32_t', ['uint32_t', 'void *', 'void *']),
      ConvertStringSecurityDescriptorToSecurityDescriptorW: bind(security, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', 'int32_t', ['str16', 'uint32_t', 'void *', 'void *']),
      CreateDirectoryW: bind(kernel, 'CreateDirectoryW', 'int32_t', ['str16', 'void *']),
      GetVolumeInformationW: bind(kernel, 'GetVolumeInformationW', 'int32_t', ['str16', 'void *', 'uint32_t', 'void *', 'void *', 'void *', 'void *', 'uint32_t']),
      LocalFree: bind(kernel, 'LocalFree', 'void *', ['void *']),
    };
  } catch (error) { throw mapped(error, 'WINDOWS_BINDINGS_UNAVAILABLE'); }
}

function createAdapter(options = {}) {
  const platform = options.platform ?? process.platform;
  const arch = options.arch ?? process.arch;
  const fsApi = options.fs ?? fs;
  const randomBytes = options.randomBytes ?? crypto.randomBytes;
  let bindings = options.native;
  function native() {
    if (platform !== 'win32' || arch !== 'x64') throw failure('WINDOWS_UNSUPPORTED');
    if (!bindings) bindings = loadNative();
    return bindings;
  }
  function attributes(value) {
    const result = native().GetFileAttributesW(nativePath(value));
    if (result === C.INVALID_ATTRIBUTES) throw failure('SOURCE_INVALID');
    if (result & C.FILE_ATTRIBUTE_REPARSE_POINT) throw failure('SOURCE_PATH_UNSAFE');
    return result;
  }
  function checkDirectory(value) {
    const normalized = localPath(value);
    const root = path.win32.parse(normalized).root;
    // A mapped network share can also have a drive letter. Reject it before
    // enumerating or inspecting any profile contents through that mapping.
    if (![2, 3, 6].includes(native().GetDriveTypeW(root))) throw failure('SOURCE_PATH_UNSAFE');
    let current = root;
    if (!(attributes(current) & C.FILE_ATTRIBUTE_DIRECTORY)) throw failure('SOURCE_INVALID');
    for (const part of normalized.slice(root.length).split('\\').filter(Boolean)) {
      current = path.win32.join(current, part);
      if (!(attributes(current) & C.FILE_ATTRIBUTE_DIRECTORY)) throw failure('SOURCE_INVALID');
    }
    return normalized;
  }
  async function checkSource(value) {
    const directory = checkDirectory(value);
    const entries = await fsApi.readdir(directory, {withFileTypes: true});
    let hasLock = false;
    for (const entry of entries) {
      if (!entry || typeof entry.name !== 'string' || entry.name.includes('\\') || entry.name.includes('/') || entry.name === '.' || entry.name === '..') throw failure('SOURCE_PATH_UNSAFE');
      const file = localPath(path.win32.join(directory, entry.name));
      const flags = attributes(file);
      if (entry.isSymbolicLink() || !entry.isFile() || flags & C.FILE_ATTRIBUTE_DIRECTORY) throw failure('SOURCE_PATH_UNSAFE');
      if (entry.name === 'LOCK') hasLock = true;
    }
    if (!hasLock) throw failure('SOURCE_LOCK_UNAVAILABLE');
    return directory;
  }
  async function assertBrowserClosed() {
    const api = native();
    let snapshot;
    try {
      snapshot = api.CreateToolhelp32Snapshot(C.SNAP_PROCESS, 0);
      if (invalidHandle(snapshot)) throw failure('BROWSER_CHECK_FAILED');
      // PROCESSENTRY32W: Windows x64 size 568; szExeFile begins at byte 44.
      // Only the executable name is read. PIDs, paths and command lines are not.
      const entry = Buffer.alloc(568);entry.writeUInt32LE(entry.length, 0);
      let present = api.Process32FirstW(snapshot, entry), count = 0;
      while (present) {
        const executable = entry.subarray(44, 564).toString('utf16le').split('\0', 1)[0].toLowerCase();
        if (executable === 'chrome.exe' || executable === 'browser.exe') throw failure('BROWSER_RUNNING');
        if (++count > 100000) throw failure('BROWSER_CHECK_FAILED');
        entry.writeUInt32LE(entry.length, 0);
        present = api.Process32NextW(snapshot, entry);
      }
      if (api.GetLastError() !== C.ERROR_NO_MORE_FILES) throw failure('BROWSER_CHECK_FAILED');
    } catch (error) { throw mapped(error, 'BROWSER_CHECK_FAILED'); }
    finally { if (!invalidHandle(snapshot)) { try { api.CloseHandle(snapshot); } catch (_) {} } }
  }
  async function withSourceLock(leveldbDir, fn) {
    const api = native();
    let handle, thrown, callbackStarted = false;
    try {
      if (typeof fn !== 'function') throw failure('SOURCE_INVALID');
      await assertBrowserClosed();
      let directory;
      try { directory = await checkSource(leveldbDir); }
      catch (error) { throw mapped(error, 'SOURCE_INVALID'); }
      // Existing LOCK only: no create, write, truncate, delete or ACL operation.
      handle = api.CreateFileW(nativePath(path.win32.join(directory, 'LOCK')), C.GENERIC_READ, 0, null, C.OPEN_EXISTING, C.FILE_FLAG_OPEN_REPARSE_POINT, null);
      if (invalidHandle(handle)) throw failure('SOURCE_LOCK_UNAVAILABLE');
      const tag = Buffer.alloc(8);
      if (api.GetFileType(handle) !== C.FILE_TYPE_DISK || !api.GetFileInformationByHandleEx(handle, C.FILE_ATTRIBUTE_TAG_INFO, tag, tag.length)) throw failure('SOURCE_PATH_UNSAFE');
      if (tag.readUInt32LE(0) & (C.FILE_ATTRIBUTE_DIRECTORY | C.FILE_ATTRIBUTE_REPARSE_POINT)) throw failure('SOURCE_PATH_UNSAFE');
      await assertBrowserClosed();
      try { await checkSource(directory); }
      catch (error) { throw mapped(error, 'SOURCE_INVALID'); }
      // Await deliberately: this exclusive read handle remains alive through all
      // copying and before/after source hashes performed by the caller.
      callbackStarted = true;
      return await fn();
    } catch (error) {
      thrown = error;
      if (error?.windowsAdapter) throw error;
      // The caller owns errors from its clone/copy/hash callback. It must use its
      // own fixed safe messages; this adapter never prints callback exceptions.
      if (callbackStarted) throw error;
      throw mapped(error, 'SOURCE_INVALID');
    } finally {
      if (!invalidHandle(handle)) {
        let closed = false;try { closed = Boolean(api.CloseHandle(handle)); } catch (_) {}
        if (!closed && !thrown) throw failure('SOURCE_LOCK_RELEASE_FAILED');
      }
    }
  }
  function currentUserSid(api) {
    let token;
    try {
      const pointer = Buffer.alloc(8);
      if (!api.OpenProcessToken(api.GetCurrentProcess(), C.TOKEN_QUERY, pointer)) throw failure('PRIVATE_ACL_UNAVAILABLE');
      token = pointer.readBigUInt64LE(0);
      if (invalidHandle(token)) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const length = Buffer.alloc(4);
      if (api.GetTokenInformation(token, C.TOKEN_USER, null, 0, length) || api.GetLastError() !== C.ERROR_INSUFFICIENT_BUFFER) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const needed = length.readUInt32LE(0);
      if (needed < 16 || needed > 65536) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const information = Buffer.alloc(needed);
      if (!api.GetTokenInformation(token, C.TOKEN_USER, information, information.length, length)) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const sidPointer = information.readBigUInt64LE(0);
      if (!sidPointer) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const sidLength = api.GetLengthSid(sidPointer);
      if (sidLength < 8 || sidLength > 68) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const sid = Buffer.alloc(sidLength);
      if (!api.CopySid(sid.length, sid, sidPointer) || sid[0] !== 1 || sid[1] > 15 || 8 + sid[1] * 4 !== sid.length) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const authority = BigInt('0x' + sid.subarray(2, 8).toString('hex')).toString();
      const parts = Array.from({length:sid[1]}, (_, index) => sid.readUInt32LE(8 + index * 4));
      return 'S-1-' + authority + (parts.length ? '-' + parts.join('-') : '');
    } catch (error) { throw mapped(error, 'PRIVATE_ACL_UNAVAILABLE'); }
    finally { if (!invalidHandle(token)) { try { api.CloseHandle(token); } catch (_) {} } }
  }
  async function createPrivateDirectory(parent, prefix) {
    const api = native();
    let descriptor;
    try {
      if (typeof prefix !== 'string' || !/^[a-z0-9_-][a-z0-9._-]{0,63}$/i.test(prefix)) throw failure('PRIVATE_DIRECTORY_FAILED');
      const directory = checkDirectory(parent), root = path.win32.parse(directory).root;
      const flags = Buffer.alloc(4);
      if (!api.GetVolumeInformationW(root, null, 0, null, null, flags, null, 0) || !(flags.readUInt32LE(0) & C.FILE_PERSISTENT_ACLS)) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const sid = currentUserSid(api), output = Buffer.alloc(8);
      const sddl = `O:${sid}D:P(A;OICI;FA;;;${sid})(A;OICI;FA;;;SY)`;
      if (!api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, C.SDDL_REVISION, output, null)) throw failure('PRIVATE_ACL_UNAVAILABLE');
      descriptor = output.readBigUInt64LE(0);
      if (!descriptor) throw failure('PRIVATE_ACL_UNAVAILABLE');
      const securityAttributes = Buffer.alloc(24);
      securityAttributes.writeUInt32LE(securityAttributes.length, 0);
      securityAttributes.writeBigUInt64LE(descriptor, 8);
      for (let attempt = 0; attempt < 8; attempt++) {
        const name = prefix + randomBytes(12).toString('hex');
        const destination = path.win32.join(directory, name);
        if (api.CreateDirectoryW(nativePath(destination), securityAttributes)) {
          checkDirectory(destination);
          return destination;
        }
        if (api.GetLastError() !== C.ERROR_ALREADY_EXISTS) throw failure('PRIVATE_DIRECTORY_FAILED');
      }
      throw failure('PRIVATE_DIRECTORY_FAILED');
    } catch (error) { throw mapped(error, 'PRIVATE_DIRECTORY_FAILED'); }
    finally { if (descriptor) { try { api.LocalFree(descriptor); } catch (_) {} } }
  }
  return Object.freeze({assertBrowserClosed, withSourceLock, createPrivateDirectory});
}

const adapter = createAdapter();
module.exports = {
  ...adapter,
  // Dependency injection permits Linux guard tests without loading Windows DLLs
  // or opening any real browser profile. Production uses only the three methods.
  _createAdapterForTests: createAdapter,
};

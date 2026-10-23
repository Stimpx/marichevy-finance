/* Read-only local capture. Run only after reading docs/LOCAL_QUEUE_BACKUP_RU.md.
 * No session reads, storage writes, network requests or application import.
 * The returned console status contains no financial contents.
 */
(async () => {
  'use strict';
  const fail = reason => { throw new Error(reason); };
  try {
    if (location.origin !== 'https://finance.marichev.pro') fail('wrong-origin');
    if (!window.isSecureContext || !crypto.subtle) fail('secure-hashing-unavailable');

    const exactKeys = new Set([
      'marichevy_state_v10', 'marichevy_state_v10_corrupt_v1',
      'marichevy_state_v10_cloud_base_v1', 'marichevy_state_v10_cloud_conflict_v1',
      'marichevy_pending_v10', 'marichevy_pending_v10_corrupt_v1',
      'marichevy_state_backup_v44', 'marichevy_state_backup_v44_corrupt_v1',
      'marichevy_pre_import_backup_v73', 'marichevy_pre_import_backup_v73_corrupt_v1'
    ]);
    const isAllowed = key => exactKeys.has(key) ||
      /^marichevy_state_v10_cloud_conflict_v1_archive_[A-Za-z0-9_-]+$/.test(key);
    const storage = window.localStorage;
    const selectedKeys = () => {
      const selected = [];
      for (let index = 0, count = storage.length; index < count; index += 1) {
        const key = storage.key(index);
        if (key !== null && isAllowed(key)) selected.push(key);
      }
      return [...new Set(selected)].sort();
    };
    const keys = selectedKeys();
    if (!keys.length) fail('no-financial-keys');
    const rawValues = keys.map(key => {
      const raw = storage.getItem(key);
      if (raw === null) fail('storage-changed-during-capture');
      return {key, raw};
    });
    const capturedAt = new Date().toISOString();
    const encoder = new TextEncoder();
    const hex = digest => Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    const records = [];
    for (const item of rawValues) {
      const bytes = encoder.encode(item.raw);
      // UTF-16LE also distinguishes a lone surrogate from TextEncoder's U+FFFD.
      const codeUnitBytes = new Uint8Array(item.raw.length * 2);
      for (let index = 0; index < item.raw.length; index += 1) {
        const codeUnit = item.raw.charCodeAt(index);
        codeUnitBytes[index * 2] = codeUnit & 255;
        codeUnitBytes[index * 2 + 1] = codeUnit >>> 8;
      }
      const utf8Digest = await crypto.subtle.digest('SHA-256', bytes);
      const utf16Digest = await crypto.subtle.digest('SHA-256', codeUnitBytes);
      records.push({key: item.key, raw: item.raw, utf16_code_units: item.raw.length,
        utf8_bytes: bytes.byteLength, sha256_utf8: hex(utf8Digest), sha256_utf16le: hex(utf16Digest)});
    }
    // Hashing yields to the application. Refuse a visibly changing capture.
    if (JSON.stringify(selectedKeys()) !== JSON.stringify(keys) ||
        rawValues.some(item => storage.getItem(item.key) !== item.raw)) {
      fail('storage-changed-during-capture');
    }
    const capture = {
      format: 'marichevy-local-queue-capture-v1',
      purpose: 'PRIVATE-read-only-local-recovery-capture-not-an-application-import',
      origin: location.origin, captured_at_device_utc: capturedAt,
      device_clock_verified: false, key_count: records.length,
      session_included: false, storage_modified: false, records
    };
    const filename = 'marichevy-local-queue-PRIVATE-' + capturedAt.replace(/[^0-9]/g, '') + '.json';
    const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(capture, null, 2) + '\n'],
      {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    link.hidden = true;
    try {
      document.body.appendChild(link);
      link.click();
    } finally {
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
    }
    return {outcome: 'download-requested', key_count: records.length, filename};
  } catch (error) {
    const known = new Set(['wrong-origin', 'secure-hashing-unavailable', 'no-financial-keys',
      'storage-changed-during-capture']);
    const reason = error instanceof Error && known.has(error.message) ? error.message : 'capture-failed';
    console.error('Локальная копия не создана (' + reason + '). Скрипт не изменял данные и очередь.');
    return {outcome: 'blocked', reason};
  }
})();

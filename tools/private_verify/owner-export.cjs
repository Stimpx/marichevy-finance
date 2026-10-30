'use strict';

// Only decode the selected owner SQL Editor download. No file access, network,
// credentials, JSON-number parsing, database commands or file modifications.
const {TextDecoder} = require('node:util');
const MAX_FILE = 32 * 1024 * 1024;
const CODES = new Set(['owner-export-input-type','owner-export-size-limit',
  'owner-export-invalid-utf8','owner-export-csv-invalid','owner-export-csv-shape',
  'owner-export-csv-header','owner-export-empty']);
class OwnerExportError extends Error {
  constructor(code) {
    const safe = CODES.has(code) ? code : 'owner-export-csv-invalid';
    super(safe); this.name = 'OwnerExportError'; this.code = safe;
  }
}
const fail = code => { throw new OwnerExportError(code); };

function csvRows(text) {
  const rows = [];
  let position = 0;
  while (position < text.length) {
    if (rows.length >= 2) fail('owner-export-csv-shape');
    const row = [];
    for (;;) {
      let field = '';
      if (text[position] === '"') {
        position++;
        let closed = false;
        while (position < text.length) {
          const at = text.indexOf('"', position);
          if (at < 0) fail('owner-export-csv-invalid');
          field += text.slice(position, at); position = at + 1;
          if (text[position] === '"') { field += '"'; position++; }
          else { closed = true; break; }
        }
        if (!closed) fail('owner-export-csv-invalid');
        if (position < text.length && ![',','\r','\n'].includes(text[position]))
          fail('owner-export-csv-invalid');
      } else {
        const start = position;
        while (position < text.length && ![',','\r','\n'].includes(text[position])) {
          if (text[position] === '"') fail('owner-export-csv-invalid');
          position++;
        }
        field = text.slice(start, position);
      }
      row.push(field);
      if (row.length > 1) fail('owner-export-csv-shape');
      if (text[position] === ',') { position++; continue; }
      if (text[position] === '\r') {
        if (text[position + 1] !== '\n') fail('owner-export-csv-invalid');
        position += 2;
      } else if (text[position] === '\n') position++;
      rows.push(row);
      break;
    }
  }
  return rows;
}

function decodeOwnerExport(bytes) {
  if (!(bytes instanceof Uint8Array)) fail('owner-export-input-type');
  if (bytes.byteLength > MAX_FILE) fail('owner-export-size-limit');
  if (!bytes.byteLength) fail('owner-export-empty');
  let text;
  try { text = new TextDecoder('utf-8', {fatal:true,ignoreBOM:true}).decode(bytes); }
  catch (_) { fail('owner-export-invalid-utf8'); }
  // A single UTF-8 BOM is accepted only at the start of the downloaded file.
  if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
  if (text.charCodeAt(0) === 0xFEFF) fail('owner-export-invalid-utf8');
  if (!text.trim()) fail('owner-export-empty');
  if (text.trimStart().startsWith('{')) {
    // Full wrapper validation, duplicate keys and every numeric token belong
    // to core.parse(), never JSON.parse() or a conversion through JS Number.
    return {format:'marichevy-owner-export-decoded-v1', inputFormat:'json', backupJson:text};
  }
  const rows = csvRows(text);
  if (rows.length !== 2 || rows.some(row => row.length !== 1)) fail('owner-export-csv-shape');
  if (rows[0][0] !== 'backup_json') fail('owner-export-csv-header');
  if (!rows[1][0].trim()) fail('owner-export-empty');
  return {format:'marichevy-owner-export-decoded-v1', inputFormat:'csv', backupJson:rows[1][0]};
}

module.exports = Object.freeze({MAX_FILE, OwnerExportError, decodeOwnerExport});

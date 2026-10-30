#!/usr/bin/env python3
"""Build the explicit public account candidate ZIP; never read runtime secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    'public/index.html',
    'public/accounts.js',
    'public/accounts.css',
    'public/ledger.js',
    'public/ledger-template.html',
    'server/account_gateway.py',
    'server/004_public_accounts.sql',
    'docs/ACCOUNT_GATEWAY_RUNTIME.md',
    'docs/ACCOUNT_ACCESS_PLAN_RU.md',
)
GENERATED_FILES = ('README_RU.md', 'MANIFEST.json')
ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)
README_RU = '''# Публичные аккаунты · проверяемый кандидат

Это отдельная сборка кандидата из Draft PR5, а не опубликованный сервис.
Установка и настоящая отправка писем не включаются распаковкой архива.
Общих логина и пароля нет: каждый пользователь создаёт собственный аккаунт,
подтверждает почту и получает доступ только к своим семьям.

В архив включены только новый публичный клиент public/, account gateway,
миграция отдельного namespace finance_app и два документа по настройке.
Личный корневой index.html, старая семейная история, .env, ключи, тестовые
учётные данные, резервные копии и production-конфигурация сюда не включены.

Для работающего сервиса нужны Python 3.11+, HTTPS-домен, отдельный настроенный
Supabase/GoTrue/PostgREST, почта GoTrue для подтверждения и восстановления,
а также SMTP с проверяемым TLS для приглашений. URL, публичный ключ, стабильный
защищённый HMAC-ключ и почтовые credentials задаются защищённой конфигурацией
окружения сервера. Service credential нужен только отдельному mail worker;
пользовательские запросы всегда выполняются с JWT пользователя и публичным ключом.
Не помещайте секреты в HTML, архив, Git или аргументы команд.

Порядок установки и переменные: docs/ACCOUNT_GATEWAY_RUNTIME.md.
Возможности, роли, ограничения и проверки: docs/ACCOUNT_ACCESS_PLAN_RU.md.
После подготовки защищённой конфигурации сервер запускается из корня распаковки:

    python3 server/account_gateway.py --host 127.0.0.1 --port 8787

Наружный HTTPS reverse proxy должен сохранять публичные Host/Origin и закрывать
прямой доступ к backend. Новая миграция не запускается этим архивом автоматически.
Применяйте её только в отдельно проверенном окружении; действующий семейный сайт,
production, старые таблицы и резерв владельца не переключаются автоматически.

В процессе разработки письма принимал локальный SMTP-приёмник, данные и адреса
были вымышленными. Это не подтверждает настройку реальной доставки. Статус
«отправлено» означает принятие SMTP-сервером, а не попадание во входящие.
Настоящие SMTP/DNS/GoTrue-настройки, проверка реальной доставки, нативный
Safari/iPhone и отдельная приёмка остаются условиями публичного запуска.

MANIFEST.json перечисляет SHA-256 каждого включённого исходника и этого README.
Имена файлов относительные; архив не содержит symlink. Фиксированные timestamp,
порядок и права файлов делают повторную сборку тех же исходников детерминированной.
'''


def read_source(root: Path, name: str) -> bytes:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Archive members must be relative explicit paths')
    source = root
    for part in path.parts:
        source = source / part
        if source.is_symlink():
            raise ValueError('Symbolic links are not accepted as bundle sources')
    # O_NOFOLLOW also closes the final-component symlink race on supported OSes.
    descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Bundle sources must be regular files')
        return stream.read()


def validate_public_payload(files: dict[str, bytes]) -> None:
    forbidden = (
        re.compile(rb'sb_secret_[A-Za-z0-9_-]{12,}'),
        re.compile(rb'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}'),
        re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        re.compile(rb'(?:marichev\.coach|chebotareva\.web)@gmail\.com', re.I),
    )
    for payload in files.values():
        if any(pattern.search(payload) for pattern in forbidden):
            raise ValueError('Sensitive credential/personal marker found in public bundle sources')


def build(output: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve()
    output = Path(output).absolute()
    if output.is_symlink():
        raise ValueError('Bundle output must not be a symbolic link')
    files = {name: read_source(root, name) for name in SOURCE_FILES}
    files['README_RU.md'] = README_RU.encode('utf-8')
    validate_public_payload(files)
    manifest = {
        'format': 1,
        'status': 'candidate-not-published',
        'files': {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(files.items())},
    }
    files['MANIFEST.json'] = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.accounts-bundle-', suffix='.zip', dir=output.parent)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, payload in sorted(files.items()):
                entry = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
                entry.create_system = 3
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(entry, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'preview/public-accounts-candidate.zip')
    args = parser.parse_args()
    build(args.output)
    print('Built public account candidate bundle with explicit manifest.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

# marichevy-finance

Проверяемый кандидат v95 в Draft PR5. Рабочий семейный сайт не переключён.

- [Что реализовано и проверено](docs/RELEASE_CANDIDATE.md)
- [Регистрация, семьи и приглашения](docs/ACCOUNT_ACCESS_PLAN_RU.md)
- [Запуск публичного клиента и защищённые настройки](docs/ACCOUNT_GATEWAY_RUNTIME.md)
- [Экран входа](preview/public-accounts-login-desktop.png) · [Телефон](preview/public-accounts-family-mobile.png) · [Настройки](preview/public-accounts-settings-desktop.png)
- [Архив публичного кандидата](preview/public-accounts-candidate.zip)
- [Финансовое демо на вымышленных данных](preview/safe-demo-v95.zip)

Корневой `index.html` — прежний личный клиент. Новый публичный клиент находится в
`public/`, gateway — в `server/account_gateway.py`, изолированная схема — в
`server/004_public_accounts.sql`. Настоящие SMTP, платежи и публичный запуск ещё
требуют отдельной настройки и приёмки. Общего демонстрационного логина нет.

Общая регрессия: `python3 -m unittest discover -s tests -v`.
Реальный локальный GoTrue/PostgREST/SMTP/Chromium:
`python3 tools/check_accounts_stack.py --report /tmp/accounts-stack.json`.
Эти проверки требуют Docker, локальные pinned images и Playwright/Chromium;
runtime gateway использует только Python 3.11+ standard library.

# Отдельный Supabase-стенд · подключение

Разрешён только новый `marichevy-finance-staging`:

- Project ref: `iqpoxphtvtogjowruufe`.
- Project URL: `https://iqpoxphtvtogjowruufe.supabase.co`.
- Организация по снимку владельца: `b2b_up`, план FREE.
- Dashboard по снимку: Healthy, GitHub не подключён, миграций нет.

Это наблюдение из Dashboard владельца, а не проверенный доступ из облачной среды.
Реальную семейную историю на стенд не копировать. Рабочий проект не менять.

## Единственное защищённое подключение

В Dashboard: https://supabase.com/dashboard/account/tokens → Generate new token.
Выбрать Resource access **Project**, организацию `b2b_up`, только проект
`marichevy-finance-staging`, Expires in **24 hours**. Не создавать legacy token.

Начать с Permissions **Preset · No access** и включить только:

| Раздел | Строка | Уровень |
| --- | --- | --- |
| Project | Project Settings | Read |
| Database | Database | Read-write |
| Application services | API Keys | Read |
| Application services | API Key Secrets | Read |

Всё остальное None. После Review access проверить точное имя выбранного стенда.
Новая форма Supabase поддерживает токен с ограничением одним проектом на этом
аккаунте. Прежнее предположение об обязательном account-wide PAT не применяется.

Полученное значение вводится только в защищённые настройки облачной среды:
Secret `STAGING_SUPABASE_MANAGEMENT_TOKEN`, destination `api.supabase.com`.
Токен, пароль БД и API secret keys не отправлять в чат, Git, логи или SQL-файлы.
Отдельные пароль БД и service_role key для этого подключения не нужны.
Требование секрета и точные сетевые адреса уже сохранены в черновик среды.
Сохранение черновика не подставляет значение, не применяет доступ и не публикует банк.

## Подготовленный инструмент

Из `/workspace/marichevy-finance`:

```sh
python3 tools/supabase_staging.py inspect
python3 tools/supabase_staging.py run
```

Сначала inspect проверяет Management API project ref/name/Healthy и читает только
число таблиц, auth-пользователей и наличие тестового маркера. Значения секретов
в отчёт не попадают. Даже с токеном runner не принимает другой URL/project ref,
не следует redirect и блокирует подмену проекта в URL.

`run` допустим только на пустом стенде. Он отказывается продолжать при существующих
public-таблицах, пользователях или маркере, не делает DROP/reset и не повторяет
частично выполненную настройку автоматически. При прерывании сначала inspect и
разбор безопасного отчёта; нельзя удалять данные ради повторного зелёного запуска.

При доступном подключении run создаёт только фиктивную схему, применяет точный
`server/001_family_state_cas.sql`, создаёт через Auth Admin API три вымышленных
аккаунта (два члена одной семьи, один другой) и получает их настоящие сессии.
Далее проверяет PostgREST чтение, CAS, конфликт и повтор, запрет legacy-записей,
чужое/анонимное чтение и запись, защиту членства, синтетическое восстановление
JSON и возврат/повторную активацию протокола без изменения JSON.

Ключ администратора используется только для Auth setup; RLS проверяется с JWT
обычных пользователей и anon. Пароли, ключи и сессии держатся в памяти одного
запуска. Отчёт: `/workspace/artifacts/supabase-staging-report.json`. При ошибке
результат failed/blocked заменяет старый отчёт, а прошедшие шаги перечисляются
отдельно. До успешного hosted-запуска это подготовка, не доказательство Supabase.

## Границы проверки

Схема членства стенда явно синтетическая. Даже успешный hosted-прогон не проверяет
неизвестную схему/права/функции production и не заменяет частный семейный резерв,
проверку восстановления реальной истории или приёмку устройств.

Локальные проверки новых файлов:

```sh
PYTHONPATH=tests python3 -m unittest test_staging_fixture test_supabase_staging_runner -v
```

Они не требуют токена и не обращаются в Supabase. Повтор прежнего клиентского
регресса не нужен, пока `index.html` и его условия выполнения не изменились.

Источники точных прав и API:

- https://raw.githubusercontent.com/supabase/supabase/master/packages/shared-data/scoped-access-token-permissions.ts
- https://raw.githubusercontent.com/supabase/supabase/master/apps/docs/spec/api_v1_openapi.json

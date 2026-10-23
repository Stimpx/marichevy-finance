# Реальная схема: выводы и кандидат серверных исправлений

На 23 октября 2026 подготовлены отдельные миграции для лишних табличных прав и
открытого поиска членства. Рабочая база этим анализом не изменена; семейные строки
не читались. Это проверка совместимости и кандидатов, не подтверждение живой RLS
production и не разрешение публиковать HTML.

## Основание и границы

Фиксированный read-only запрос каталога выполнен 23.10.2026 в 14:18 UTC. Сохранён
частный metadata-артефакт `production-schema-inventory-PRIVATE.json`; сюда перенесены
только структура и свойства доступа. Рабочий PostgreSQL — 17.11. Отдельная проверка
тела `public.is_household_member(uuid,uuid)` совпала с исходным fingerprint
`ee70441dfc53e994de80474ad6fb344a`. Её разрешённый результат — простой `SELECT EXISTS`
по полностью указанной `public.household_members`, двум входным UUID, без записи.

Этот снимок не доказывает настройку всех exposed schemas PostgREST, отсутствие
неизвестных внешних writers, правильность резервной копии, состояние настоящих
семейных очередей или поведение браузера. Реальные строки и API keys не нужны для
описанных локальных проверок. Их отсутствие нельзя считать проверенным резервом.

## Фактический контракт

| Объект | Наблюдение |
| --- | --- |
| `family_state` | Ровно исходные `household_id uuid`, `data jsonb`, `updated_at timestamptz`, `updated_by uuid`; первые три NOT NULL; PK по household_id; FK на households.id с ON DELETE CASCADE и на auth.users.id для updated_by. |
| `households` | id/name/created_at, PK id. |
| `household_members` | household_id/user_id/role/created_at; составной PK; FK на households и auth.users с ON DELETE CASCADE. |
| `family_chore_deliveries` | Отдельный журнал доставки задач; составной PK household_id/chore_id/due_date/chat_id; приложение anon/authenticated не имеет доступа. |
| RLS/владелец | Все четыре таблицы — обычные таблицы, RLS включён, owner postgres. Пользовательских row triggers на момент снимка нет. |
| Политики | Пять permissive policies только для authenticated: state SELECT/INSERT/UPDATE, membership SELECT, households SELECT. Предикат вызывает is_household_member с auth.uid(). DELETE policy для state отсутствует. |
| Helper | SQL, SECURITY DEFINER, owner postgres, volatile, search_path=public; `EXISTS` проверяет переданный p_user_id. EXECUTE эффективен для anon/authenticated/service_role. |

Проверенный `001_family_state_cas.sql` принимает эту форму `family_state`:
дополнительные FK и внутренние FK-триггеры не нарушают его preflight; NOT NULL у
updated_at сохраняется. CAS остаётся SECURITY INVOKER, пользуется существующей RLS
и серверной версией. Миграция не заменяет JSON, политики и старые grants.

DELETE в этой схеме отсекается RLS до row trigger: нормальный DELETE возвращает
ноль строк, а не обязательно `PT409`. Добавлять DELETE policy ради совпадения с
прежним упрощённым тестом нельзя. Широкие authenticated CRUD grants на membership
и households сами по себе не позволяют запись: при SELECT-only policies INSERT
отклоняется, UPDATE/DELETE не находят разрешённых строк. Это отдельно воспроизведено.

## Два установленных пробела

**Табличные возможности.** У anon/authenticated эффективны TRUNCATE и TRIGGER на
state, households и membership. TRUNCATE не ограничен RLS и не запускает row-level
DELETE trigger CAS. В изолированной модели anon удаляет обе фиктивные state-строки,
даже когда SELECT запрещён и protocol=2; TRUNCATE households CASCADE также очищает
зависимые таблицы. TRIGGER разрешает создание триггера при наличии подходящей функции.

Это доказанный лишний SQL privilege. Обычный REST table endpoint PostgREST не
предоставляет команду TRUNCATE или CREATE TRIGGER. Проверенный публичный helper тоже
не выполняет произвольный SQL. Следовательно, из метаданных нельзя делать вывод
«anon сейчас может стереть рабочую базу по обычному HTTP-запросу». Риск возникает
при доступном SQL/DDL или дополнительном уязвимом RPC; лишние права нужно убрать.

**Поиск чужого членства.** Исходный helper принимает произвольные household/user UUID
и доступен anon. При известных UUID он возвращает boolean о чужом членстве; таблица
state для этого не читается. Политики передают auth.uid(), поэтому сам этот пробел
не означает доказанный обход RLS истории. Локальная модель подтверждает oracle, а
hosted direct-RPC проверку исправления нужно выполнить на фиктивных аккаунтах.

## Точные кандидаты

| Файл | SHA-256 локального исходника |
| --- | --- |
| `server/001_family_state_cas.sql` | `a97333d25d903cd013e53973bd5756602756aa0c127effb46814a685e948a7c8` |
| `server/002_restrict_table_capabilities.sql` | `2dcc99d29923fae4627201c923327a5ccb07fbd205abf144b8e121e6424d8fb7` |
| `server/003_bound_membership_lookup.sql` | `34ee3b3fcae3e5e5b7c7672d17bda3d332d9dea04031e459a493d7ed058e7ea3` |

`002` транзакционно отзывает только TRUNCATE/TRIGGER у PUBLIC, anon и authenticated
на четырёх перечисленных таблицах. Preflight требует postgres и ожидаемые обычные
RLS-таблицы того же владельца, необходимые роли. После REVOKE проверяются эффективные
права: если они остались через наследование, вся транзакция откатывается. CRUD,
service_role, политики, FK, функции и строки не меняются. Это не исправление default
privileges для любых будущих таблиц; новые таблицы требуют отдельного контроля.

`003` сохраняет сигнатуру, postgres owner, SQL/volatile/SECURITY DEFINER, но ограничивает
поиск обычного authenticated пользователя условием `p_user_id=auth.uid()`. Исходный
EXISTS и lookup произвольного пользователя для доверенного service_role сохраняются.
Этот исключительный доступ определяется `auth.role()='service_role'`; current_user
в SECURITY DEFINER равен владельцу и для такой проверки непригоден. Функция использует
search_path `pg_catalog, public`, квалифицированные таблицу/auth-функции. PUBLIC/anon
EXECUTE отзывается, authenticated/service_role выдаётся явно; унаследованный anon
EXECUTE вызывает полный откат.

Проверка JWT role полагается на проверенный JWT и роль, установленную PostgREST.
Произвольный SQL/GUC доступ недоверенного пользователя вне этого протокола в эти
гарантии не входит; аналогичная граница уже есть у CAS request marker. Service-role
запрос с JWT role=service_role и без user sub сохраняет прежний результат helper.

`003` отказывается от неизвестного тела, overload, аргументов, настроек безопасности,
RLS или пяти ожидаемых policies. Повтор разрешён только при точном новом теле и его
ожидаемых атрибутах; произвольное «похоже настроено» не принимается. Строки и revisions
не меняются. Все пять текущих policies передают auth.uid() и совместимы с ограничением.
Сторонние callers с нестандартным использованием должны соблюдать этот явный контракт.

Удалять остальные CRUD grants или менять provisioning/invite policies в этих
миграциях не требуется. У service_role на журнале доставки сохраняются существующие
SELECT/INSERT/UPDATE; уведомления при проверках не отправляются.

## Проверки и следующий серверный этап

`tests/test_production_permissions.py` запускается только в отдельном PostgreSQL 16
контейнере: pinned image, network=none, tmpfs, без портов, секретов и production
connection string. auth.uid()/auth.role() здесь — явные stand-ins. Синтетические
таблицы воспроизводят имена, типы, FK и policies каталога; значения полностью вымышлены.
Это проверяет PostgreSQL semantics и миграции, не заменяет Supabase 17/PostgREST.

```sh
PYTHONPATH=tests python3 -m unittest test_production_permissions -v
```

Локальный результат 23.10.2026: **18/18 passed**, 13.103s, без skips.

Проверяются применение точных SQL, сохранность JSON/FK/NOT NULL/revisions/policies,
CAS двух членов и чужой семьи, прямые SQL TRUNCATE/TRIGGER до/после hardening,
атомарный отказ при наследовании/неожиданной схеме, блокировка чужих user UUID,
запрет anon helper и сохранение service-role lookup без uid.

На отдельном Supabase-стенде требуется воспроизвести production-shaped membership,
households, FK и пять policies без копирования реальной истории. После `002` и `003`
нужны обычные Auth JWT двух семей, anon и service-role lookup: прямые table/RPC HTTP,
свой/чужой ID пользователя, запрет self-enrollment, CAS-конкуренция, отсутствие DELETE
policy, локальная очередь, синтетический reserve/restore. Только после такого hosted
прогона можно включать эти SHA в согласованный выпуск server+client. Подготовка и
проверки не дают разрешения менять production или публиковать новый HTML отдельно.

# Продолжение семейного обновления · пауза 27 октября 2026

Владелец закончил работу на сегодня и попросил план на завтра. Никаких новых
действий от него сейчас не требуется. Обновление рабочего банка не выполнялось.
Владелец уже разрешил основной семейный выпуск; повторно разрешение не спрашивать.

## Что уже получено

- Семейные правки подготовлены: точный клиент SHAde2828a8 прошёл 588 проверок
  и свежий hosted staging run. Отдельная static ветка f21a9c1 меняет только
  index.html против основного bfc7ce5; всю рабочую PR5 ветку в main не сливать.
- Серверный резерв в worker восстановлен на настоящем изолированном PostgreSQL.
  Это четыре app-таблицы с Auth UUID stubs, не полный Supabase/Auth restore.
  Он не доказывает тождество ещё не полученной owner-local серверной копии.
- Windows ordinary/raw сохранены у владельца на Windows. Ответ владельца:
  файл очереди пока НЕ перенесён на Mac.
- iPhone raw получен из исходной Safari-вкладки; AirDrop на Mac подтверждён.
- Mac helper на настоящем устройстве прошёл все native fictional selftests,
  затем сообщил СОХРАНЕНО после actual capture. Это актуальный успешный receipt;
  позднее присланный native-policy screenshot был от более раннего запуска —
  владелец это подтвердил. Заново диагностировать уже прошедшую загрузку не нужно.
  Побайтовое сопоставление сохранённых файлов ещё не выполнено.
- SQL Editor владельца показал postgres/off на неизменяющем SELECT. Полный
  production project URL/ref перед серверными шагами ещё требуется проверить.
- Deploy binding в worker недоступен; публикацию среды с private backups не
  выполнять. Для серверных шагов выбран путь через SQL Editor владельца.

## Семь оставшихся этапов

1. Перенести на Mac обычный JSON Windows и raw JSON очереди в отдельную папку
   Windows. Оригиналы на Windows сохранить; файлы в чат не прикладывать.
2. Сохранить постоянную серверную копию у владельца через проверенный read-only
   экспорт четырёх таблиц. Worker copy её не заменяет. Проверить выбранный project
   ref; название postgres само по себе не идентифицирует проект.
3. Доделать и проверить локальный путь сверки, затем сопоставить все три пары
   устройств с серверным оригиналом и настоящим результатом восстановления.
   Файлы остаются частными. При расхождении, conflict/quarantine или pending
   остановиться и разобрать варианты/подтверждение ACK; ничего автоматически
   не удалять, не объединять и не считать подтверждённым из-за равных сумм.
4. Проверить новую форму на настоящих устройствах на вымышленных данных,
   подтвердить совместимость всех writers и остановить не только ручной ввод,
   но также отправку старых очередей/автоматические writes на время переключения.
5. Снять свежий preflight/резерв, применить точные 001→002→003, проверить
   сохранность и активировать protocol2 с заранее сверенными параметрами.
   Сохранить настоящий activation receipt до публикации статики.
6. Опубликовать только проверенный six-file static release через main/Pages;
   проверить выбранный commit, HTTPS/CNAME и фактический SHA HTML.
7. Проверить вход и прежнюю историю на Windows/Mac/iPhone, затем разрешённую
   настоящую правку и её подтверждённое появление на другом устройстве.
   Только после подтверждения очередей снять паузу ввода.

Время зависит от результата сверки. Условный ориентир без расхождений —
1–2 часа совместной работы; это не гарантия. Локальный verifier ещё не готов,
поэтому не обещать владельцу «остался один клик» или точный короткий срок.

## Технический checkpoint для сопровождающего

Успешный Mac helper: preview/mac-private-backup-helper-v95.zip, SHA9db462ea…,
commit a43d85c. Маленькая диагностика — preview/mac-helper-check-v95.zip,
SHAe0a1cd10…, commit da88fe7. Обе pinned raw download ссылки проверены HTTP200
и по полному SHA. Оригинальный helper/source не заменены и работают у владельца.

Незакоммиченные tools/private_verify/ и новые тесты — НЕ готовый инструмент:

- core.cjs — fail-closed stub STATUS.ready=false. Exact decimal parser, snapshot,
  health/capture/device comparison пока НЕ реализованы. README.WIP.md содержит API.
- mac-main.cjs — fail-closed stub без IO. Семь slots/OS chooser/private copy flow
  описаны в комментарии; реального выбора/проверки пока нет.
- owner-export.sql/cjs — WIP unique-household SELECT и CSV decoder. Только syntax
  check; PostgreSQL/CSV behavior tests не выполнены. Не давать SQL владельцу сейчас.
- tests/test_private_device_verifier_node.py — WIP differential cases по прежнему
  Python verifier. AST проверен; поведенческих passes нет.
- tests/test_private_verify_mac.py — единственный checkpoint test подтверждает
  отсутствие IO у заглушки; это НЕ проверка работоспособности local workflow.

Существующий tools/verify_private_backup.py — oracle с Decimal, raw UTF8/UTF16,
unknown fields/tombstones/duplicates/links/periods, точным scope и pending gate.
Не подменять restore сравнением серверного файла с самим собой или его копией.
Для phased verification нужны H(T0)=H(owner CSV)=H(T1), project/family/timezone/
query/schema identity и настоящий restore receipt того же H. Закрытого join пока
нет; равные T0/T1 сами по себе не исключают промежуточные изменения writers.
Owner base household/url проверяются, но legacy primary/pending без household ID
всё ещё требуют подтверждённого владельцем происхождения. Публикация блокируется
до закрытия реальной сохранности, не повторным вопросом разрешения.

SQL Editor activation code-only prototype вне checkout:
/tmp/code-only-sql-editor-receipt-v95. Он проверен 9 synthetic cases с PostgreSQL,
заканчивается настоящим EXECUTE, отдельная cleanup не выполняется автоматически.
Native SQL Editor grid/download receipt ещё не проверены. Приватные параметры
планом не заполнены; не подставлять автоматически текущую revision вместо сверенной.

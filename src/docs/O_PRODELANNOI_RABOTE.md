# О проделанной работе (MetaPlatform)

## 2026-08-16 — IDE workspace и UX редакторов

### Что сделано
- Рабочая область конфигуратора переведена из плавающих MDI-окон в единое табовое IDE-пространство. Форма и модуль теперь являются документами/режимами внутри общего workspace, а не перекрывающимися окнами.
- Модуль, открытый из дерева, диагностики, перехода по определению или отладчика, теперь проходит через общий `open_object_tab()` и получает одинаковый lifecycle, dirty-защиту, заголовок, свойства и повторное открытие.
- Для вкладок добавлена единая визуальная иерархия: активный документ, контекстные панели дерева/свойств и нижняя диагностика.
- Свежая установка больше не скрывает панель свойств из-за отсутствующего значения QSettings; строковые значения `false/0/off` обрабатываются корректно.
- Дерево конфигурации и Problems dock получили минимальные размеры и более заметное keyboard-focus состояние.

### Проверка
- `137 passed` для configurator editors, control API, window refactor и form designer.
- `python -m compileall -q src/configurator/configurator_main_window.py` завершился без ошибок.

---

## 2026-08-16 — IDE: автоотступы, клавиатурное completion и конструкторы кода

### Что сделано
- `Ctrl+Space` открывает контекстное автодополнение и выделяет первый вариант; popup остается доступным для перемещения стрелками и подтверждения клавишей Enter.
- Автодополнение не переоткрывается после полного совпадения идентификатора, но явный `Ctrl+Space` всегда выполняет запрос повторно.
- Enter учитывает украинские и английские блоки, включая `Інакше`/`Else`, и нормализует отступ закрывающей ветви.
- `Ctrl+Alt+Space` открывает клавиатурный конструктор процедур, функций, условий, циклов, `Try/Except` и `While`.
- Шаблоны локализованы для `uk`/`en`; имя счетчика выбирается с учетом уже использованных идентификаторов (`Счетчик`/`Сч`, `Counter`/`I`).

### Проверка
- `54 passed` для code editor, completion и lexer tests.
- `python -m compileall -q src` завершился без ошибок.

---

## 2026-08-16 — Семантические ссылки 1C после импорта

### Что сделано
- Добавлена явная таблица совместимости для подтвержденных ссылок, которые встречаются в выгруженном BSL под старым или фасадным именем.
- Алиасы разрешаются только по точной паре модуль/член и только если целевой экспорт действительно присутствует в индексе. Fuzzy-сопоставление не используется, поэтому реальные отсутствующие API остаются в Problems.
- После пересборки live-индекса `metabase.mpdb`: 4549 модулей, 57559 символов, 27 диагностик вместо 38 до этого шага; unresolved callable отсутствуют.
- 27 оставшихся ссылок проверены по `F:\ConfigFiles` и резервной `WorkedData\XMLConf`: реализаций этих API в выгрузке нет. Они теперь классифицируются как `source_gap`, а не как ложные `unresolved_member`/`unresolved_module`; настоящих unresolved-ссылок в live-индексе нет.

### Проверка
- `37 passed` для semantic index и MPDB concurrency tests.
- Runtime semantic index rebuilt successfully on the active database.
- Runtime reports `unresolved_references=0`, `unresolved_modules=0`, `unresolved_callables=0`, `source_gaps=27`.

---

Этот документ фиксирует, что уже сделано, какие решения приняты, и какие правила считаются **инвариантами**. Цель — остановить регрессии, когда «починили одно — сломали другое».

---

## 2026-05-25 — Packed 1C data через виртуальные таблицы runtime

### Что сделано
- Runtime теперь умеет читать packed `onec__data_rows` как виртуальные logical tables:
  - `data_catalog_<name>`
  - `data_document_<name>`
  - `data_tp_<doc>_<part>`
  - `data_document_<name>_rows`
  - `data_reg_<name>`
  - `data_constants`
- `table.select/insert/update/delete` для этих logical tables маршрутизируются через runtime adapter, а не требуют физических `data_*` таблиц на диске.
- `data_constants` больше не читается по одному `select` на каждую константу; rows собираются из packed source cache.
- Для document tabular parts runtime синтезирует system fields `_doc_guid`, `_owner_guid`, `_line_no`, `_row_guid`, чтобы posting/print/client forms могли работать поверх packed rows.

### Инвариант
- Клиент и runtime должны читать packed 1C data через runtime RPC и virtual table adapter; отсутствие физических `data_*` таблиц на диске не является ошибкой, если logical tables доступны через adapter.
- `data_reg_*` должен маппиться на `information_register`/`accumulation_register`/`accounting_register`/`calculation_register` families, а не на legacy aliases.

## 2026-03-14 — Импорт 1C: phase 2 должен быть batch-path

### Контекст
После исправления phase 3 (`enrich`) стало видно второе узкое место:
`phase 2 — importing manifest objects` всё ещё работал по legacy-path:

- `manifest_io.add_object(...)` вызывался по одному объекту;
- на каждый объект отдельно создавались системные папки и module stubs;
- модульные тексты шли через `upsert_module(...)` по одному;
- runtime-path при reset manifest не чистил `cfg_modules`, из-за чего таблица модулей
  разрасталась от переимпорта к переимпорту и phase 2 деградировал всё сильнее.

### Что сделано
1. `src/infra/onec/importer.py`
   - `import_manifest_objects(...)` переведён на накопление manifest-объектов в память
     и `add_objects_bulk(...)`;
   - module rows для `cfg_modules` теперь собираются через `make_module_row(...)`
     и пишутся пачкой через `insert_modules_bulk(...)`;
   - добавлен progress-callback для живого статуса phase 2.

2. `src/runtime/server_handlers_import.py`
   - перед новым import runtime теперь очищает `cfg_modules` через `purge_all_modules(db)`;
   - progress phase 2 берётся из callback `import_manifest_objects(...)`, а не висит
     на статическом `18%`.

### Инвариант
- Phase 2 импорта (`import_manifest_objects`) не должен возвращаться к поштучным
  `manifest_io.add_object(...)` и `upsert_module(...)` внутри внутренних циклов.
- Перед новым runtime-import обязательно очищается `cfg_modules`, иначе переимпорт
  накапливает устаревшие module rows и деградирует по времени.

---

## 2026-03-14 — Post-import structure cache не должен гидрировать heavy payload

### Контекст
После ускорения `phase 2/3` стало видно новое узкое место:
импорт заканчивался успешно, но следующий `manifest.info` синхронно пересобирал
structure cache через `list_objects(db)`, а тот гидрировал externalized payload:

- `form_model_ref`
- `layout_model_ref`
- `requisites_ref`
- `tabular_parts_ref`

На больших 1C-дампах это давало сотни секунд лишней работы уже **после** `DONE`.

### Что сделано
1. `src/configurator/persistence/manifest_io.py`
   - добавлен raw-path `list_object_rows(...)`;
   - `list_objects(..., hydrate_payload=False)` теперь позволяет читать manifest
     без загрузки heavy asset payload.

2. `src/runtime/server_handlers_manifest.py`
   - `manifest.info` больше не пишет raw structure cache;
   - при отсутствии полного cache runtime должен строить именно hydrated
     `structure_cache_snapshot`, а не отдавать configurator огромный `manifest.open`
     ответ на десятки мегабайт;
   - `meta-only` допускается только как аварийный fallback, если запись полного
     snapshot не удалась.

3. `src/runtime/server_handlers_import.py`
   - в конце импорта runtime должен сохранять полный hydrated structure cache,
     чтобы следующий запуск configurator шёл по `cache-hit`;
   - `meta-only` допускается только как fallback при сбое записи snapshot;
   - memory cache для `manifest.info` прогревается немедленно.

### Инвариант
- Structure cache и `manifest.info` не должны зависеть от многократной
  поштучной гидрации heavy payload через `db.get_asset(...)`.
- Полный structure cache, который читает configurator при `open_db`, нельзя
  заполнять raw manifest rows без гидрации `*_ref`, иначе UI теряет
  `requisites/form_model/layout_model`.
- Если полного cache нет, runtime должен предпочитать локальное построение
  hydrated snapshot на стороне сервера, а не огромный `manifest.open` RPC-ответ.

### Дополнение
- `manifest.open` не должен гидрировать manifest несколько раз внутри одного
  RPC-вызова на этапах `seed/prune/check-empty`.
- Все структурные проверки внутри `manifest.open` должны работать по raw rows;
  полная гидрация externalized payload допустима только один раз в самом конце.
- Hydration `form_model/layout_model/requisites/tabular_parts` не должен
  выполняться через поштучный `db.get_asset(...)` для каждого manifest row, если
  доступен batched prefetch locator-ов asset table.

---

## 1) Инварианты

### 1.1. Для `common_picture` нет «Формы/Команды/Макеты»
- Для объектов типа **`common_picture`** системные подпапки **не создаются**.
- Если такие подпапки были созданы в старых версиях — они **не отображаются** в дереве.

### 1.2. Для служебных объектов с `no_object_folders` нет «Формы/Команды/Макеты»
- Любой объект, у которого в payload установлено `no_object_folders: true`, не должен получать системные подпапки.
- Если подпапки уже есть (наследие) — они должны скрываться в дереве.

### 1.3. Палитра хранится в manifest
- Решение: **палитра проекта хранится в manifest**, а не в бинарных ресурсах mpdb.
- Минимум две темы: `light` и `dark`.
- Токены цветов — `#RRGGBB`.

### 1.4. SVG-редактор: без автоправок и «очисток»
- Не добавляем автокоманды, которые «исправляют viewBox» или «очищают fill/stroke» без явного запроса.
- Выбор цвета: сразу открывает `QColorDialog` (заголовок локализован), и записывает корректный HEX.

Дополнительно:
- Пустое значение в поле атрибута означает **«не менять»**.
- Удаление атрибута — только явным действием (кнопка × рядом с полем).
- Если атрибут помечен на удаление, поле подсвечивается **красной рамкой** до нажатия «Застосувати».

### 1.5. Дерево прикладного объекта: стабильный контракт секций
- Для прикладных metadata-объектов (`document`, `catalog`, `report`, `data_processor` и т.п.)
  дерево должно оставаться 1С-подобным и стабильным:
  - разрешённые системные folder-секции (`forms`, `commands`, `layouts`) видимы;
  - схемные секции (`attributes/requisites`, `tabular_parts`, и др. по policy) видимы;
  - секция `modules` внутри самого объекта в дереве **не показывается**.
- Доступ к модулям прикладного объекта остаётся через editor самого объекта, а не через отдельную
  ветку дерева.
- Исключение: верхнеуровневая системная папка `common_modules` в группе `common` должна оставаться
  видимой и не подпадает под правило скрытия `modules`.
- Любые правки логики дерева обязаны сохранять этот контракт; проверка закреплена регрессиями
  в `src/tests/test_tree_builder.py`.

### 1.6. `Нумератори` и `Послідовності` проецируются под `Документи`
- В дереве конфигурации `document_numerator` и `sequence` должны отображаться
  не как отдельные верхнеуровневые ветки, а как подпапки группы `Документи`.
- Под `Документи` обязаны существовать две системные ветки:
  - `Нумератори`
  - `Послідовності`
- Старое физическое размещение этих узлов в manifest допускается, но в UI оно
  должно быть скрыто и перепроецировано под `Документи`.
- Проверка закреплена регрессией в `src/tests/test_tree_builder.py`.

---

## 2) Центральная точка истины по правилам типов

### 2.1. Политики объектов
Единый модуль:
- `src/core/object_policies.py`

Он содержит:
- `OBJECT_POLICIES` — политики типов объектов.
- `should_create_object_folders(obj_type, payload)` — единственный способ принять решение о создании системных подпапок.

Нельзя разносить `if type == ...` по проекту: любые правила добавляются сюда.

### 2.2. Секции объектов (SECTIONS)
Добавлен единый реестр секций `SECTIONS`, который описывает "разделы" дерева
для объектов (как в 1С). Секция содержит:

- `kind`: тип секции (`schema` или `folder`)
- `i18n`: ключ локализации для отображения в UI

Реестр расширен и включает не только базовые узлы (`dimensions/resources/attributes/forms/...`),
но и дополнительные, которые понадобятся для регистров/аналитики:

- **Графы** (`tree.graphs`)
- **Значения** (`tree.values`)
- **Перерасчеты** (`tree.recalculations`)
- **Реквизиты адресации** (`tree.addressingAttrs`)
- **Таблицы** (`tree.tables`)
- **Кубы** (`tree.cubes`)

- **Функции** (`tree.functions`)

Важно:
- В проекте нет RU локали — для всех секций добавлены ключи в **EN/UK**.
- При отображении системных папок дерево использует `section_i18n_key(name)` и `t(key)`.

---

## 3) Стабилизация рендера иконок

### 3.1. Резолвинг `var(token)` для SVG
Единый резолвер:
- `src/ui_qt/services/svg_var_resolver.py`

Поддерживает:
- `var(primary)`
- `var(--primary)`
- `var(primary, #ffffff)` (fallback)

### 3.2. Единый провайдер иконок
- `src/ui_qt/services/icon_provider.py`

Принцип: галерея/формы/превью не должны сами «подменять» SVG. Они запрашивают иконку/пиксмап через провайдер.

---

## 4) Регрессионный барьер (selfcheck)

Файл:
- `src/scripts/selfcheck.py`

Запуск:
```bash
python -m src.scripts.selfcheck
```

Проверяет:
1) `common_picture` не получает `forms/commands/layouts`.
2) объект с `no_object_folders:true` не получает `forms/commands/layouts`.
3) `SvgVarResolver` реально заменяет `var(...)` на HEX.
4) Если доступен Qt (`PySide6`) — headless рендер SVG не должен быть пустым.

---

## 5) Где править при проблемах

- Создание/seed manifest и системных подпапок:
  - `src/configurator/persistence/manifest_io.py`
- Формирование дерева в UI (скрытие наследных подпапок):
  - `src/ui_qt/viewmodels/configurator_vm.py`
- Палитра/тема (как источник palette_map):
  - `src/ui_qt/viewmodels/configurator_vm.py` (должна отдавать palette_map для активной темы)

### 5.1. Канонический manifest_io
- Канонический модуль работы с manifest: `src/configurator/persistence/manifest_io.py`
- `src/configurator/manifest_io.py` — только compatibility shim для старых импортов.
- Любая новая логика manifest (seed, migration, externalized payload, batch updates) добавляется
  только в `src/configurator/persistence/manifest_io.py`.

### 5.2. `src/storage` удалён как мёртвый слой
- Исторический каталог `src/storage/` удалён.
- Причина: он не использовался кодом, содержал пустые заглушки и конфликтовал с текущей архитектурой,
  где единственный storage-слой платформы — `src/mpdb`, а прикладное хранение идёт через
  `src/configurator/persistence`.
- Новый код не должен возрождать `src/storage` как параллельную абстракцию над storage.

---

## 6) Ближайшие шаги по roadmap (после стабилизации)

1) Метаданные + палитра проекта (продолжение: полноценные фильтры/теги/категории)
2) SVG как структура (дерево элементов + операции)
3) Конструктор иконок (DSL → SVG)
4) Интеграция с формами (использование иконок в компонентах формы)
5) История и блокировки

---

## 7) 2026-01-17 — Устранение дубля `_populate_tree` (Вариант A)

### Что было
В проекте существовали две реализации построения дерева конфигурации:

- `src/ui_qt/viewmodels/configurator_vm.py` (ViewModel)
- `src/configurator/configurator_controller.py` (Controller)

Из‑за этого правки по дереву (фильтрация legacy‑папок, поиск, порядок построения)
могли попасть только в одно место, что приводило к регрессиям.

### Что сделано
1) Добавлен единый модуль-строитель дерева:
   - `src/ui_qt/services/tree_builder.py`

   Он включает:
   - фильтрацию устаревших автосозданных папок `forms/commands/layouts` (через `object_policies`)
   - поиск (оставляем совпадения + всех предков)
   - построение `QStandardItemModel` (pending-loop + обработка сирот)

2) ViewModel и Controller теперь используют один алгоритм:
   - VM: `ConfiguratorViewModel._populate_tree()` вызывает `prepare_tree_objects()` + `build_tree_model()`
   - Controller: `ConfiguratorController._populate_tree()` вызывает `prepare_tree_objects()` + `build_tree_model()`

   При этом:
   - прогресс/`pulse UI` остаётся в Controller (через callback `progress`)
   - `expand_default()` остаётся в View/Controller, а в VM — `expandDefaultRequested`

### Инвариант
Любые изменения правил построения дерева (фильтры, поиск, порядок) делаются
ТОЛЬКО в `src/ui_qt/services/tree_builder.py`. В VM/Controller допускается
менять только UX-обвязку (progress, expand, блокировки UI).

---

## 2026-01-17 — Унификация иконок дерева через IconProvider

### Проблема
Иконки узлов дерева конфигурации задавались разными способами:
- в `ConfiguratorViewModel` иконка приходила через внешний `icon_provider(meta)`
- в `ConfiguratorController` использовался собственный метод `_icon_for_node(meta)`

Это приводило к расхождениям: правка карты типов/иконок в одном месте не
гарантировала одинаковый результат в другом.

### Решение
Сделали `IconProvider` единой точкой для всех иконок:

1) `src/ui_qt/services/icon_provider.py`
   - добавлен параметр `tree_icon_provider: Callable[[dict], QIcon] | None`
   - добавлен метод `tree_icon(meta)` с безопасным fallback на стандартную иконку Qt

2) `src/ui_qt/viewmodels/configurator_vm.py`
   - VM создаёт `IconProvider(..., tree_icon_provider=icon_provider)`
   - `_mk_item()` запрашивает иконку через `self.icon_provider.tree_icon(meta)`

3) `src/configurator/configurator_controller.py`
   - Controller создаёт `IconProvider(tree_icon_provider=self._icon_for_node)`
   - `_mk_item()` запрашивает иконку через `self.icon_provider.tree_icon(meta)`

### Инвариант
Иконки дерева конфигурации берём только через `IconProvider.tree_icon(meta)`.
Логику маппинга типов в конкретные SVG (Lucide) допускается менять в
передаваемой функции (`tree_icon_provider`) или в `_icon_for_node`, но точка
вызова в UI должна быть единой.

## 2026-01-17 — Стабилизация: configurator_vm.py (docstrings + исключения)

- Исправлены предупреждения линтера в `src/ui_qt/viewmodels/configurator_vm.py`:
  - Добавлены недостающие docstring для публичных методов/алиасов и `__init__`.
  - Убраны широкие обработчики `except Exception` — заменены на ограниченный набор ожидаемых исключений.
  - Удалены ошибочно добавленные docstring внутри `Protocol`-методов (stubs с `...`).
- Проверено, что модуль компилируется (`python -m py_compile`).

## 2026-01-18 — Политики объектов и секции дерева (Policy + Sections)

## 2026-01-18 — Системные таблицы: Users/Roles/AuditLog + версии конфигурации

### Контекст
Для подготовки мульти-юзерного режима и будущих командных модулей (Repo/Checkout)
нужно иметь базовую инфраструктуру в mpdb:

- пользователи и роли (чтобы фиксировать автора действий)
- аудит (кто/когда/что)
- версионирование конфигурации в MainDB (immutable releases + atomic switch)

Эта часть **не включает UI для пользователей** — только системные таблицы и
минимальный API для публикации конфигурации.

### Что сделано
1) Добавлен модуль `src/configurator/persistence/system_tables.py`:
   - `ensure_users_tables()` создаёт: `sys_users`, `sys_roles`, `sys_user_roles`, `sys_audit_log`
   - `ensure_config_versioning_tables()` создаёт: `config_releases`, `config_head`
   - `ensure_system_tables()` вызывает оба ensure-метода
   - seeded роли: `Admin`, `ConfigMaintainer`, `Developer`, `Reviewer`, `Deployer`, `Viewer`
   - seeded пользователь `system` (служебный)

2) Реализован минимальный API:

## 2026-03-14 — Импорт 1C: живой status channel и batch enrich

### Что зафиксировано
- UI импорта конфигурации не должен поллить несуществующий RPC. Для long-running
  операции `onec.import` обязателен серверный status channel `onec.import_status`.
- Прогресс-диалог импорта должен показывать живой статус фаз, а не статический `0%`.
- Phase `enriching objects with requisites/tabular-parts` не должен выполнять
  `manifest.update_payload(...)` по одному объекту. Допустим только batch path через
  `manifest_io.bulk_update_payloads(...)`.

### Почему
- Per-object update на больших dump'ах приводил к минутным задержкам и визуально
  выглядел как зависание импорта после `UUID index size ...`.
- UI уже содержал polling-логику, но runtime/gateway не поддерживали соответствующий
  action, поэтому progress dialog оставался декоративным.
- Для live-debug импорта нужен не только текущий status, но и discoverable surface:
  список импорт-сессий и history tail, чтобы можно было подключиться к уже
  запущенной сессии даже если её `session_id` не был сохранён заранее.

### Инвариант
- Любые будущие изменения import pipeline обязаны сохранять:
  - работающий `onec.import_status`;
  - discoverable `onec.import_sessions` для live-debug;
  - batch rebuild manifest в phase 3;
  - совместимость configurator UI с этим status path.
   - `audit_log(...)` — запись события
   - `get_active_config_release_id(db)` — текущая активная ревизия
   - `publish_config_release(...)` — публикация новой конфигурации как immutable release
     с optimistic guard `expected_active_release_id` и атомарным переключением `config_head`.

3) `ConfiguratorService.open_db()` теперь гарантирует наличие системных таблиц:
   - вызывает `ensure_system_tables(db)` до любых UI-операций.

4) Добавлены тесты:
   - `test_system_tables_and_config_versioning.py` проверяет идемпотентность
     ensure-методов и работу `publish_config_release()`.

### Инварианты
- Системные таблицы создаются идемпотентно и не мешают существующим базам.
- Публикация конфигурации не перезаписывает прошлые версии: создаётся новая запись
  в `config_releases`, а активная версия определяется через `config_head`.
- На текущем MVP-этапе публикация выполняется в **2 шага** (release -> head switch),
  потому что таблица-слой mpdb пока не поддерживает вложенные транзакции.
  Это безопасно (head никогда не указывает на несуществующий release),
  но позже следует добавить tx-aware операции или один составной tx.
- Аудит фиксирует `CONFIG_PUBLISH` и будет расширяться по мере включения модулей.

### Следующие шаги
- Добавить feature flags (в настройках/manifest): `features.config_repo.enabled`,
  `features.team_checkout.enabled` (пока только gating UI).
- Реализовать объектные блокировки (checkout) как опциональный модуль
  поверх Users/Audit.

## 2026-01-18 — Manifest Editing UX: dirty-state + защита от потери изменений

### Что добавили
1) **Dirty-state** для редактирования manifest:
   - Окно конфигуратора отображает `*` в заголовке при наличии несохранённых изменений.
   - Кнопка **Save** активна только когда есть изменения.
   - В статус-баре показывается короткий индикатор `Modified / Змінено`.

2) **Защита при закрытии окна**:
   - Если есть несохранённые изменения, показывается диалог:
     - **Save** — попытка сохранения
     - **Discard** — закрыть без сохранения
     - **Cancel** — отменить закрытие

### Где реализовано
- `src/configurator/configurator_window.py`
  - `_on_editor_state_changed(...)` — синхронизация заголовка/кнопок/статуса.
  - `closeEvent(...)` — диалог при закрытии, интеграция с `ViewModel.on_save()`.
- `src/ui_qt/viewmodels/configurator_vm.py`


### Инвариант
Dirty-state берётся строго из `ManifestEditorState.is_dirty`. Никаких отдельных флагов, которые могут рассинхронизироваться.

### Задача
Нормализовать структуру дерева конфигурации по аналогии с 1С через единый механизм:
`policy + sections` — чтобы у каждого типа объектов показывались только те секции,
которые ему действительно нужны (Измерения/Ресурсы/Реквизиты/Графы/Значения/... и т.д.).

### Реализация
1) `src/core/object_policies.py`
   - Расширен `SECTIONS`:
     - добавлены: `columns`, `values`, `recalculations`, `addressing_attributes`, `tables`, `cubes`, `functions`.
   - Полностью заполнен `OBJECT_POLICIES` под типы из manifest (плюральные коды групп):
     - `constants`, `catalogs`, `documents`, `document_journals`, `enumerations`, `reports`, `data_processors`.
     - `chart_of_characteristic_types`, `chart_of_accounts`, `chart_of_calculation_types`.
     - `info_registers`, `accumulation_registers`, `accounting_registers`, `calculation_registers`.
     - `business_processes`, `tasks`, `external_data_sources`.
   - Добавлена поддержка подтипов для `common` (через `payload.subtype`) — для последующего точного управления секциями.

2) `src/ui_qt/services/tree_builder.py`
   - Добавлена инъекция виртуальных "схемных" узлов (`kind="schema"`) на основе `policy.sections`.
     Эти узлы не записываются в manifest, но отображаются в дереве как в 1С.
   - Узлы создаются с детерминированным GUID (`<parent_guid>::<section_key>`), что позволяет:
     - корректно работать поиску (оставлять предков/ветви);
     - не нарушать существующие GUID реальных объектов.

3) `src/ui_qt/viewmodels/configurator_vm.py`
   - Добавлена локализация заголовков для виртуальных секций (`kind="schema"`) и системных папок-секций.
   - Обработчики исключений сужены до ожидаемых (`TypeError`, `AttributeError`, `KeyError`, `ValueError`).

4) `src/ui_qt/i18n.py`
   - Добавлены ключи:
     - `tree.addressingAttributes`, `tree.columns`.
   - Оставлен `tree.addressingAttrs` для обратной совместимости.

### Результат
Дерево конфигурации формируется строго по политике типа объекта:
вложенные секции отображаются единообразно и без "лишних" автосозданных папок.

### Hotfix (2026-01-18)
- Исправлен `NameError: section_kind is not defined` в `src/ui_qt/services/tree_builder.py`:
  добавлен корректный импорт `section_kind` из `src.core.object_policies`.
- Исправлен `AttributeError: 'str' object has no attribute 'kind'` в `_inject_schema_sections()`:
  политика `ObjectPolicy.sections` хранит **ключи секций** (строки), поэтому параметры секции
  (`kind/i18n`) берутся через `section_kind()`/`section_i18n_key()`.

---

## 2026-01-18 — Базовый слой редактирования manifest (Editor foundation)

### Задача
Перейти от «просмотра» конфигурации к полноценному редактированию manifest, при этом:

- не затаскивать Qt-логику в слой данных (MVVM)
- делать правки атомарно (одна перестройка manifest на одно применение изменений)
- получить базовую валидацию и состояние `dirty` для UI

### Реализация
1) `src/configurator/persistence/manifest_io.py`
   - добавлена функция `update_fields(...)`, которая обновляет **несколько полей** одной строки manifest
     (type/name/title/payload) за **одну** перестройку таблицы (mpdb append-only).
   - `update_title()` и `update_payload()` переведены на `update_fields()` (обратная совместимость сохранена).

2) `src/configurator/application/service.py`
   - добавлен метод `ConfiguratorService.update_object_fields(...)` — единый API для редактора,
     чтобы избежать «двойных rebuild» при изменении нескольких полей.

3) `src/configurator/application/manifest_editor.py`
   - добавлен Qt‑free слой редактирования:
     - `ManifestEditorState` (snapshots original/current + `is_dirty`)
     - `ValidationIssue` (ошибки валидации для UI)
     - `ManifestEditorService` (load/set/validate/revert/apply)
   - валидация пока минимальная (name/title/payload), чтобы не блокировать UI.

4) `src/ui_qt/viewmodels/configurator_vm.py`
   - ViewModel создаёт `ManifestEditorService` и подготавливает состояние при выделении узла дерева.
   - добавлен сигнал `editorStateChanged` (передача состояния редактора в View).
   - `on_save()` теперь применяет изменения редактора при `dirty` и перезагружает дерево.

5) `src/ui_qt/i18n.py`
   - добавлены ключи локализации:
     - `status_saved` (EN/UK)
     - `dlg_error_title` (EN/UK)

### Инвариант
- Любые обновления полей объекта manifest, которые должны быть применены «одним действием»,
  выполняем через `update_fields()` / `ConfiguratorService.update_object_fields()`.
  Это снижает риск неконсистентных промежуточных состояний и лишних rebuild.

---

## 2026-01-18 — Панель свойств: просмотр + редактирование (ManifestPropertiesPanel)

### Задача
Сделать в конфигураторе нормальную **Property-panel**:

- вкладка «Инфо» (read-only) — как раньше, для быстрого просмотра ключевых полей
- вкладка «Редактирование» — привязка к `ManifestEditorService` (MVVM), без прямой работы UI с mpdb
- Apply/Cancel (применить/откатить) + базовая подсветка ошибок (включая JSON)

### Реализация
1) `src/ui_qt/widgets/manifest_properties_panel.py`
   - добавлен `ManifestPropertiesPanel`:
     - Tab 1: таблица свойств (`props_tbl`) — legacy UI
     - Tab 2: редактор полей `title/name/type` + `payload` как JSON
   - сигнализация для MVVM:
     - `editorFieldChanged(field, value)`
     - `editorPayloadChanged(payload_dict)`
     - `applyRequested()` / `revertRequested()`
   - JSON парсится в UI: если текст некорректен — кнопка Apply блокируется, показывается локализованное сообщение.

2) `src/configurator/configurator_window.py`
   - заменён `QTableWidget` в Dock «Properties» на `ManifestPropertiesPanel`.
   - биндинги:
     - `propertiesRowsChanged -> props_panel.set_properties_rows()`
     - `editorStateChanged -> props_panel.update_editor()`
     - `props_panel.* -> ViewModel` (field/payload/revert)
     - `props_panel.applyRequested -> saveRequested` (единая точка сохранения)

3) `src/ui_qt/viewmodels/configurator_vm.py`
   - добавлены слоты для редактирования состояния:
     - `on_editor_field_changed()`
     - `on_editor_payload_changed()`
     - `on_editor_revert()`
   - после каждого изменения выполняется `validate()` и эмитится `editorStateChanged`.

4) `src/ui_qt/i18n.py`
   - добавлены ключи (EN/UK): вкладки, подписи полей, плейсхолдеры, Apply/Cancel, сообщение о некорректном JSON.

### Инварианты
- UI **не пишет** в mpdb напрямую: только через ViewModel + `ManifestEditorService`.
- `payload` редактируется как JSON без “автопочинок” структуры.

---

## 7) 2026-01-18 — Меню «Администрирование» (UI)

Добавлено верхнее меню **«Администрирование»** в Configurator (Qt), по образцу 1С.

- Пункты меню добавлены как **плейсхолдеры** (пока без бизнес‑логики).
- Все строки вынесены в локализацию **EN/UK** (`src/ui_qt/i18n.py`).
- Реализация действий будет подключена на следующем шаге вместе с модулем пользователей и блокировок.

Файлы:
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`

---

## 8) 2026-01-18 — Администрирование: пользователи и журнал регистрации (MVP)

Подключены первые реальные пункты меню **«Администрирование»**:

1) **Пользователи…** / **Активные пользователи**
   - добавлено read-only окно со списком пользователей из системной таблицы `sys_users`.
   - «Активные пользователи» в MVP трактуется как `is_active = true`.

2) **Журнал регистрации**
   - добавлено read-only окно просмотра `sys_audit_log` (последние 500 событий).
   - отображается человекочитаемое имя пользователя (по логину), если возможно.

3) Локализация
   - добавлены ключи EN/UK для заголовков/колонок и общих значений Yes/No.

Файлы:
- `src/configurator/configurator_window.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/ui_qt/widgets/admin_users_dialog.py`
- `src/ui_qt/widgets/admin_audit_log_dialog.py`
- `src/ui_qt/i18n.py`

---

## 9) 2026-01-18 — RepoDB ↔ Основная БД: checkout/submit + блокировки (MVP)

Реализован MVP-механизм «связки» между **RepoDB** (текущая открытая БД в конфигураторе) и **Основной БД** (указывается в настройках):

### 9.1. Долговременные блокировки объектов/компонентов

- Добавлены таблицы:
  - `sys_object_locks` — активные/снятые блокировки.
  - `sys_checkout_sessions` — задел под устойчивые сессии и heartbeat (пока создаётся как инфраструктура).
  - `repo_checkouts` — в RepoDB хранит «активные взятия в работу» (lock_key/token, связь с MainDB).
- Реализован иерархический ключ блокировки:
  - формат: `<object_type>/<object_id>/<component_type>/<component_id>`
  - конфликт, если ключи совпадают или один является префиксом другого (объект целиком ↔ компоненты).
  - это позволяет схему: один разработчик держит `ObjectModule`, другой — `FormModule/FormName`.

### 9.2. Команды RepoDB

В меню **Администрирование → Сховище конфігурації / Configuration repository** добавлены команды:

- «Налаштувати основну БД… / Configure main DB…» — выбрать путь к MainDB.
- «Взяти з основної БД… / Take from main DB…» —
  - ставит блокировку в MainDB,
  - копирует manifest-строку объекта в RepoDB,
  - сохраняет состояние checkout в `repo_checkouts`.
- «Відправити в основну БД… / Send to main DB…» —
  - пишет изменения из RepoDB обратно в MainDB (по manifest GUID),
  - снимает блокировку.
- «Примусово розблокувати… / Force unlock…» — форс-снятие блокировки (MVP: разрешение на уровне UI будет уточняться через роли).

Примечание MVP:
- В текущей интеграции идентификатор пользователя временно фиксирован как `system`. После подключения модуля пользователей будет подставляться активный пользователь/роль.

Файлы:
- `src/configurator/persistence/system_tables.py`
- `src/configurator/persistence/object_locks.py`
- `src/configurator/application/repo_bridge.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`

### 9.3. Контекстное меню дерева: «Сховище конфігурації / Configuration storage»

Добавлено подменю в контекстном меню дерева конфигурации (1С-подобно):

- «Підключити... / Connect...» — выбор файла Mpdb, который является хранилищем конфигурации.
- «Взяти об'єкт / Take object» — ставит блокировку на объект целиком.
- «Взяти модуль об'єкта / Take object module» — блокировка компонента `ObjectModule`.
- «Взяти модуль форми / Take form module» — доступно для узлов форм (блокировка компонента `FormModule/<FormName>`).
- «Зняти мої блокування / Release my locks» — снимает блокировки, для которых у клиента есть сохранённый token.
- «Примусове розблокування... / Force unlock...» — снимает все блокировки по объекту (MVP; политики по ролям подключим после модуля пользователей).

MVP-подход:
- Блокировки хранятся в отдельном Mpdb-файле (опционально), а токены блокировок сохраняются локально (QSettings), что позволяет корректно завершать сессии после падения клиента.

Файлы:
- `src/configurator/application/config_storage_service.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`

### 9.4. Сховище конфігурації: «Помістити / Отримати / Історія» (MVP)

Расширен workflow, аналогичный 1С «Хранилище конфигурации», для отдельного Mpdb-файла хранилища:

- «Помістити в сховище... / Put to storage...» — сохраняет в хранилище снимок payload выбранного объекта (MVP-формат JSON) и автоматически снимает блокировку (release) по соответствующему `lock_key`.
- «Отримати зі сховища... / Get from storage...» — извлекает последний снимок и применяет его к локальной конфигурации (MainDB), перезаписывая payload объекта.
- «Історія / History» — показывает последние ревизии по `lock_key` (timestamp / user / commit / message).

Технически (MVP):
- Добавлены таблицы хранилища (append-only):
  - `storage_commits` — метаданные коммитов.
  - `storage_item_revisions` — снимки payload по `lock_key`.
  - `storage_item_head` — “указатель” на последнюю ревизию (для ускорения чтения; фактически event-log).
- Добавлены методы `submit/get_latest/history` в `ConfigStorageService`.
- В `ConfiguratorViewModel` добавлен метод `set_object_payload()` для полного замещения payload.

Ограничения MVP:
- Компонентная гранулярность пока отражается только в `lock_key` (Object/ObjectModule/FormModule). Снимок хранит payload объекта целиком; разделение на реальные под-части (модуль/форма) будет добавлено после появления соответствующих отдельных сущностей.
- Пользователь временно `SYSTEM` до внедрения модуля пользователей и ролей.

Файлы:
- `src/configurator/persistence/config_storage_tables.py`
- `src/configurator/application/config_storage_service.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/ui_qt/i18n.py`


### 9.5. Сховище конфігурації: верхнє меню + адмін-утиліти (MVP)

Добавлен 1С-подобный уровень «глобальных» команд хранилища:

- Верхнее меню: `Configuration → Configuration storage` (EN/UK)
  - `Connect...` — подключить Mpdb-файл хранилища.
  - `Disconnect` — отключиться и забыть путь в настройках.
  - `Status...` — показать текущий путь и состояние подключения.
  - `Storage history...` — история коммитов хранилища (MVP-вывод).
  - `Administration...` — просмотр активных блокировок и точечный `Force unlock` по `lock_key`.

Технически:
- В `ConfigStorageService` добавлены утилитарные методы:
  - `disconnect()`
  - `list_commits()`
  - `list_active_locks()`
  - `force_release_lock()`

Ограничения MVP:
- Role-based policy для `Force unlock` пока не включена (будет завязана на Users/Roles модуль).
- UI администрирования и истории на текущем этапе реализованы в виде простых диалогов/выводов (без diff/merge).

Файлы:
- `src/configurator/application/config_storage_service.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`

### 9.6. Сховище конфігурації: сесії + heartbeat (живучість при падінні клієнта)

Добавлено збереження стану "хто захопив" з можливістю визначати, чи активний сеанс користувача, що утримує блокування.

Що зроблено:
- Додано таблицю прив'язки блокування до сесії/клієнта: `storage_lock_ownership`.
- При `checkout(...)` блокування додатково реєструється в `storage_lock_ownership` (lock_key → session_id/client_id).
- При підключенні до сховища автоматично створюється "storage session" у таблиці `checkout_sessions`.
- Додано періодичний heartbeat:
  - оновлює `checkout_sessions.last_seen_at`
  - оновлює `object_locks.last_heartbeat_at` для локально утримуваних lock_token
- В `ConfiguratorWindow` додано `QTimer`, який викликає heartbeat кожні 30 секунд під час підключення.
- В адмін-вікні (MVP-діалог) список блокувань тепер показує статус сесії (`АКТИВНИЙ/НЕАКТИВНИЙ`) та `last_seen`.

Примітки:
- Політика `force-unlock` за ролями буде включена після впровадження Users/Roles.

Файли:
- `src/configurator/persistence/config_storage_tables.py`
- `src/configurator/application/config_storage_service.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`


### 10.1. DSL інтерпретатор (UA/EN): фундамент (lexer/parser/AST) (MVP)

Почато реалізацію двомовного DSL-інтерпретатора (українською та англійською) з єдиним внутрішнім AST.

Що зроблено (MVP):
- Додано пакет `src/dsl`:
  - `languages.py` — профілі ключових слів для `uk`/`en`.
  - `lexer.py` — лексер з підтримкою коментарів (`#`, `//`) та Unicode-ідентифікаторів.
  - `parser.py` — рекурсивний спуск (мінімальна граматика):
    - сутності: `catalog/document` (UK: `довідник/документ`) з блоком полів (`fields`/`реквізити`).
    - форми: `form` (UK: `форма`) з `table`/`таблиця`.
  - `ast.py` — нейтральні структури AST.
  - `validator.py` — базова семантична валідація (унікальність імен, перевірка форм, попередження по типах).
  - `api.py` — єдиний вхід `parse_dsl(text, language)` з об’єднаною діагностикою.

Додано CLI-хелпер:
- `src/scripts/dsl_parse.py` — парсинг файлу DSL і вивід діагностики.

Тести:
- `src/tests/test_dsl_parser.py` — базові кейси UA/EN.

Примітки:
- На цьому етапі DSL поки що не інтегрований у UI конфігуратора; наступним кроком буде редактор DSL та застосування AST → метадані.

Файли:
- `src/dsl/*`
- `src/scripts/dsl_parse.py`
- `src/tests/test_dsl_parser.py`


### 10.2. DSL у конфігураторі: редактор (Parse/Validate) (MVP)

Додано MVP-інтеграцію DSL у конфігуратор як інструмент для розробки мови.

Що зроблено:
- У меню **Конфігурація** додано пункт **"Редактор DSL..."** (`Ctrl+Alt+D`).
- Реалізовано діалог `DslEditorDialog`:
  - Поле введення DSL (моношрифт).
  - Вибір мови `UA/EN`.
  - Команди **Розібрати** / **Перевірити** (поки що однаковий pipeline: parse + validate).
  - Панель діагностики з позиціями `Lx:Cx` та підсумком `errors/warnings`.
  - Кнопка **Застосувати** відображається, але вимкнена (застосування до метаданих буде додано після повного підключення edit-guard для режиму сховища).

Примітки:
- Редактор не змінює конфігурацію; це свідоме обмеження до завершення політики "редагування лише після захоплення".

Файли:
- `src/ui_qt/widgets/dsl_editor_dialog.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`


### 10.3. Form Designer (Qt) + edit-guard у режимі сховища (MVP)

Додано перший робочий **візуальний дизайнер форм** (без WebEngine), побудований на чистих Qt‑віджетах.

Що зроблено:
- Реалізовано версіоновану модель форми (JSON‑схема v1): `FormModel`/`FormNode`.
- Додано `FormDesignerWidget` з трьома зонами:
  - дерево структури форми,
  - preview рендера (runtime‑подібні Qt‑віджети),
  - інспектор властивостей (name/title/binding, layout для контейнера, колонки для таблиці).
- Збереження форми виконується через оновлення `payload` метаданих (`payload.form_model`).

Політика редагування у режимі сховища:
- Якщо **Сховище конфігурації підключено**, дизайнер працює **тільки для читання**, доки форма не захоплена.
- Для форм використовується компонентний ключ блокування **FormModule/<form_name>** (паралельно з ObjectModule).
- Додано helper‑методи в `ConfigStorageService` для визначення, чи активне блокування належить цьому клієнту (token‑based).

Файли:
- `src/configurator/domain/form_model.py`
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/configurator/application/config_storage_service.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`

Доопрацювання UX (січень 2026):
- У конструкторі форм додано **мультивиділення мишею**: перетягування по порожньому місцю включає
  `RubberBand`-виділення; взаємодія з елементами (move/resize) не блокується.
- Виправлено помилку прапорів `QGraphicsItem`: замінено кілька `setFlags(...)` (які перетирали один одного)
  на `setFlag(..., True)`, щоб елементи завжди були selectable/movable.
- В `FormWindowFrame` шапка форми залишена у кольорі теми, а **фон заголовка (QLabel) зроблено прозорим**
  (`background: transparent; border: none;`).


### 10.4. Виправлено створення елементів у системній папці "Форми"

Проблема:
- Якщо створювати елемент всередині вузла **Форми/Forms** (під об’єктом, наприклад, довідником),
  у дереві створювався **новий об’єкт довідника**, а не форма.

Причина:
- Системні підпапки об’єкта (forms/commands/layouts) зберігаються у manifest з `type`, що дорівнює
  **типу власника** (catalog/document/...), щоб не ускладнювати формат.
- Контекстне меню для `payload.menu=add_only` помилково брало `meta.type` як тип створюваного об’єкта.

Рішення:
- У контекстному меню дерева додано явну розв’язку для auto‑папок (`payload.auto=true`):
  - `forms` -> `form`
  - `commands` -> `command`
  - `layouts` -> `layout`

Файли:
- `src/configurator/configurator_window.py`

### 10.5. Универсальная оболочка формы объекта (Universal Shell) + миграция «Справочник/Catalog»

Цель:
- Сделать единый каркас «форма разработки объекта метаданных» с левым списком разделов.
- Разделы должны быть переиспользуемыми и автоматически «урезаться/дополняться» в зависимости от типа объекта.
- Первым объектом миграции выбран **Справочник (Catalog)**.

Сделано:
- Добавлен виджет `MetaObjectShell`:
  - левый навигационный список разделов;
  - правый `QStackedWidget` для страниц;
  - нижняя панель навигации (Назад/Далі/Закрити/Довідка);
  - сигнал `closeRequested` для закрытия вкладки.
- Добавлен `CatalogEditorWidget` на базе `MetaObjectShell`:
  - Раздел **Основні** — базовые свойства (Им'я/Синонім/Коментар/Подання.../Пояснення).
  - Раздел **Дані** — MVP настроек кода/наименования (длина, тип кода).
  - Раздел **Форми** — MVP-заглушка под следующий шаг (интеграция редактора форм).
  - Сигнал `applyRequested(patch)` для сохранения изменений через `ConfiguratorViewModel.update_object_payload`.
- Подключено открытие `CatalogEditorWidget` при открытии объекта типа `catalog` в конфигураторе.
- Добавлены i18n ключи для Universal Shell и полей/разделов каталога (uk/en).

Файлы:
- `src/ui_qt/widgets/meta_object_shell.py`
- `src/ui_qt/widgets/catalog_editor.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`

### 10.6. CatalogEditor: чистка «лишних» полей + многострочное «Пояснение»

Цель:
- Упростить раздел **Основні** для справочника: оставить только ключевые поля (Им'я/Синонім/Коментар/Пояснення).
- Сделать «Пояснение» **многострочным** (как в 1С) и чтобы поле занимало всё доступное пространство.
- Выровнять подписи слева (1С‑подобное поведение).

Сделано:
- Убраны из UI поля "Подання об’єкта/списку" и их расширенные варианты (пока не используются в нашем конфигураторе).
- Поле "Пояснення" переведено на `QPlainTextEdit`:
  - `placeholder` берётся из i18n (`catalog_hint_placeholder`),
  - значение хранится в payload как `hint`,
  - поле растягивается по ширине и по высоте (`Expanding`) и имеет минимальную высоту.
- Для `QFormLayout` включено:
  - выравнивание подписей **слева**,
  - `AllNonFixedFieldsGrow` для роста полей по ширине.

Файлы:
- `src/ui_qt/widgets/catalog_editor.py`

### 10.7. CatalogEditor: корректное растягивание многострочного поля + восстановление окон редакторов

Цель:
- Исправить проблему, когда многострочное поле **«Пояснення»** не растягивается вниз при увеличении окна.
- Исправить восстановление рабочего пространства: при повторном запуске конфигуратора открытые ранее окна должны восстанавливаться как **реальные редакторы объектов**, а не как заглушка с GUID.

Сделано:
- `CatalogEditorWidget`:
  - Переведён layout страницы **«Основні»** на схему: верхний `QFormLayout` (короткие поля) + отдельная строка для **«Пояснення»** (`QPlainTextEdit`) с вертикальным `stretch`.
  - Теперь поле «Пояснення» корректно занимает всё свободное пространство по высоте.
  - Исправлена загрузка значения: `hint` устанавливается в `setPlainText(...)`, а placeholder остаётся из i18n.
- `ConfiguratorWindow`:
  - Восстановление открытых окон теперь пытается разрешать GUID через `ConfiguratorViewModel.get_meta_by_guid(...)` и открывать корректный редактор через `open_object_tab(...)`.
  - Добавлены короткие повторные попытки восстановления (на случай, если дерево/модель ещё не готовы в момент restore).
  - Заглушка "structure" с UUID в заголовке больше не создаётся.

Файлы:
- `src/ui_qt/widgets/catalog_editor.py`
- `src/configurator/configurator_window.py`

### 10.8. CatalogEditor: выравнивание ширины полей ввода на странице «Основні»

Цель:
- Визуально выровнять правые края всех полей ввода (включая многострочное «Пояснення») и устранить эффект «съехавшего» интерфейса.

Сделано:
- На странице «Основні» выровнены метки по правому краю (`AlignRight`), чтобы поля начинались строго по одной вертикали и выглядели одинаково по ширине.
- Многострочное поле «Пояснення» остаётся в той же сетке и продолжает занимать всё доступное пространство по ширине/высоте.

Файлы:
- `src/ui_qt/widgets/catalog_editor.py`

### 10.9. FormDesigner: графический конструктор (ABSOLUTE) + поддержка vertical/horizontal/grid

Цель:
- Перевести редактор форм из «превью-заглушки» в **графический** конструктор.
- Один дизайнер на все объекты метаданных с формами.
- Добавить альтернативные режимы компоновки контейнеров: **absolute / vertical / horizontal / grid**.

Сделано:
- Добавлено графическое полотно (Design) на базе `QGraphicsView`:
  - перемещение элементов мышью;
  - изменение размера (drag за правый нижний угол);
  - выделение и синхронизация с деревом структуры;
  - drag&drop добавление контролов из Toolbox.
- Добавлены вкладки **Design/Preview** и левая панель **Structure/Toolbox**.
- Реализован рендер Preview с поддержкой компоновок:
  - `absolute`: позиционирование дочерних элементов по `x/y/w/h`;
  - `vertical/horizontal`: классические `QVBoxLayout/QHBoxLayout`;
  - `grid`: `QGridLayout` + `grid_columns` и опциональная позиция для элементов `grid:{row,col,rowspan,colspan}`.
- В инспектор свойств добавлены:
  - размер полотна (root) `w/h`;
  - геометрия `x/y/w/h` (для детей в absolute-контейнере);
  - параметры grid (колонки + позиция элемента).
- Добавлена реализация `MetaObjectEditorShell.title_text()` для интеграций, где нужно получать заголовок владельца.

Файлы:
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/ui_qt/widgets/form_designer_canvas.py`
- `src/configurator/domain/form_model.py`
- `src/ui_qt/widgets/meta_object_shell.py`
- `src/ui_qt/i18n.py`

### 10.10. FormDesigner Preview: исправление повторного рендера (без пересоздания layout)

Проблема:
- При каждом обновлении Preview создавался новый `QVBoxLayout(...)` на одном и том же `preview_host`.
- Это приводило к предупреждениям Qt вида «widget already has a layout» и постепенному накоплению объектов.

Решение:
- `QVBoxLayout` создаётся **один раз** в `__init__` (`self._preview_layout`) и используется повторно.
- Очистка Preview выполняется через `takeAt(...)` у layout, корректно удаляя виджеты и спейсеры.

Файлы:
- `src/ui_qt/widgets/form_designer_widget.py`

### 10.11. FormDesigner Design: элементы видны и при non-absolute layout

Проблема:
- Вкладка **Design** (canvas) отображала элементы только если у корневого контейнера `layout == 'absolute'`.
- Для форм с `vertical/horizontal/grid` пользователь видел пустое окно конструктора, хотя на вкладке **Preview** элементы были видны.

Решение:
- Вкладка **Design** теперь автоматически переключается:
  - `absolute` → показывается графическое полотно (`QGraphicsView`).
  - `vertical/horizontal/grid` → показывается "layout preview" внутри Design (кликабелен для выбора узла).
- Добавлена подсказка, что для drag/resize нужно переключить корневой контейнер на `absolute`.

Файлы:
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/ui_qt/i18n.py`


- FormDesignerCanvasView: fix initial scroll position (reset scrollbars to origin after rebuild).

### 10.12. FormDesigner Design: стабильное отображение после добавления элемента

Проблема:
- После добавления нового элемента на вкладке **Design** могли пропадать видимые контролы (вид был «пустым»), при этом на вкладке **Preview** всё отображалось корректно.
- Причина: `QGraphicsView` сохранял положение скролла после пересборки сцены, а `sceneRect` имел «поля» справа/снизу, из‑за чего viewport мог оказываться вне корневого полотна.

Решение:
- `FormDesignerCanvasView.set_root_size(...)` теперь устанавливает `sceneRect` ровно по границам root‑canvas (без лишнего пустого пространства).
- Добавлен метод `ensure_valid_viewport()` — если viewport не пересекает root‑canvas, скролл автоматически сбрасывается к (0,0).
- В `FormDesignerWidget`:
  - после `rebuild()` вызывается `ensure_valid_viewport()` (через `QTimer.singleShot(0, ...)`);
  - после добавления нового элемента фокус переносится на созданный узел (чтобы он гарантированно был виден).

Файлы:
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/ui_qt/widgets/form_designer_canvas.py`


### 10.13. Дефолтные реквизиты и команды для объектов метаданных

Задача:
- Для объектов метаданных, которые предполагают наличие реквизитов (справочники, документы, регистры),
  автоматически создавать базовый набор **системных реквизитов** (например, «Найменування», «Номер», «Проведено» и т.п.).
- Автоматически задавать **команды по умолчанию** («Закрити», «Зберегти», а для документов также «Провести/Скасувати проведення»).
- Логика должна зависеть от типа объекта (например, для справочников нет команды «Провести»).

Решение:
- Добавлены модули домена (Qt-free):
  - `src/configurator/domain/default_requisites.py` — описания и дефолтные наборы реквизитов по типам объектов + merge-логика.
  - `src/configurator/domain/default_commands.py` — описания и дефолтные наборы команд по типам объектов + merge-логика.
  - `src/configurator/domain/metadata_defaults.py` — единая точка входа `ensure_payload_defaults(...)`.
- Заголовки реквизитов/команд хранятся в payload в виде словаря локализаций:
  - `title: {"uk": "...", "en": "..."}` — подготовка к корректному отображению в UI в зависимости от языка.

Интеграция:
- В `ConfiguratorViewModel.create_object_quick(...)` при создании нового объекта payload обогащается через `ensure_payload_defaults(...)`,
  что добавляет `requisites` и `commands` в зависимости от `obj_type` (и опционального `subtype`).

Файлы:
- `src/configurator/domain/default_requisites.py`
- `src/configurator/domain/default_commands.py`
- `src/configurator/domain/metadata_defaults.py`
- `src/ui_qt/viewmodels/configurator_vm.py`


### 10.14. FormDesigner: отображение полного окна формы в дизайнере

Задача:
- В редакторе форм нужно отображать **полностью окно формы** (title bar + клиентская область),
  чтобы дизайнер соответствовал тому, как форма будет выглядеть в клиентском приложении.

Решение:
- Добавлен UI-компонент `FormWindowFrame` (title bar + фиксируемая клиентская область).
- Вкладки **Design** и **Preview** теперь рендерятся внутри `FormWindowFrame` и обёрнуты во внешний `QScrollArea`,
  что позволяет проектировать большие размеры окна.
- Добавлено поле свойств **Window title** (уровень `FormModel.title`) и синхронизация заголовка/размеров окна с моделью.

Файлы:
- `src/ui_qt/widgets/form_window_frame.py`
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/ui_qt/i18n.py`


### 10.15. FormDesigner: панель реквизитов объекта и вставка "Label + Control"

Задача:
- В редакторе форм вместо общей "Панели инструментов" нужна панель реквизитов объекта.
- Перетаскивание/двойной клик по реквизиту должны добавлять на форму связку **Label + Control**.
  Тип контрола выбирается автоматически по типу данных реквизита.

Решение:
- Добавлена панель `FormRequisitesList` в `FormDesignerWidget` (левый таб "Requisites").
- Реализован drag&drop реквизитов через MIME `application/x-metaplatform-form-requisite`.
- При добавлении реквизита материализуется пара узлов:
  - `Label` с заголовком реквизита
  - Контрол, привязанный по `binding` к `requisite.code`
- Для `absolute` размещения пара ставится рядом (Label слева, Control справа), для `grid` — в одной строке (col 0/1).

Файлы:
- `src/ui_qt/widgets/form_designer_canvas.py`
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/ui_qt/i18n.py`


---

## 2026-01-21 — Гибридная тема (тёмная оболочка + светлый canvas)

- Добавлена функция `apply_hybrid_theme()` (на базе текущей dark theme) для режима: дерево/меню/доки — тёмные, рабочая область и canvas — светлые.
- `ConfiguratorWindow`: задан `objectName="Workspace"` для `QMdiArea` (целевое QSS-стилирование рабочей области).
- `FormDesignerWidget`: заданы `objectName` для canvas и scroll-областей (`FormCanvas`, `CanvasScroll`) для корректного светлого фона.
- В light-canvas режиме добавлены светлые стили для контролов внутри окна формы (`FormWindowClient`), чтобы форма выглядела как “светлая внутрянка” поверх тёмной оболочки.


---

## 2026-01-21 — Hybrid theme: тёмная оболочка + светлый canvas

### Проблема
В конфигураторе фон рабочей области (MDI/Workspace) местами оставался «серым/тёмным»,
в то время как canvas редактора форм уже был светлым. Визуально это ломало концепцию:
**оболочка тёмная, внутрянка (редактируемые формы/полотно) — светлая**.

### Что сделано
1) `src/ui_qt/theme.py`
   - Для `QMdiArea#Workspace` и `QMdiArea#Workspace::viewport` установлен `background-color: {light_bg}`
     (важно именно `background-color`, чтобы перебить общий фон `QWidget`).

2) `src/configurator/configurator_window.py`
   - Для `QMdiArea` принудительно задан фон через `setBackground(QBrush(QColor("#FFFFFF")))`.

### Результат
Рабочее полотно конфигуратора (включая пустую область без открытых подокон) становится
светлым и совпадает по стилю с canvas редактора форм.

---

## 2026-01-21 — Редактор форм: свойства в общем доке (F4) + автозаполнение пустой формы

### Цель
- Убрать локальные «Свойства» из редактора форм и использовать общий док свойств (F4).
- При открытии новой/пустой формы автоматически создавать стартовую разметку на основе реквизитов объекта.
- Визуально выровнять фон «рабочей области» конфигуратора и canvas формы (оба светлые).

### Что сделано
1) **Общий док свойств (F4) — маршрутизация по активному подокну**
   - `ConfiguratorWindow`: док `Properties` переведён на `QStackedWidget`.
   - По событию `QMdiArea.subWindowActivated` автоматически переключаем содержимое дока:
     - для обычных объектов — `ManifestPropertiesPanel` (как и раньше),
     - для `FormDesignerWidget` — его панель свойств (designer-specific).
   - При закрытии `FormDesignerWidget` его страница свойств удаляется из стека.

   **Дополнительно (UX): маршрутизация по фокусу**
   - Подключён `QApplication.focusChanged`.
   - Если фокус в дереве конфигурации или в `ManifestPropertiesPanel` — показываем свойства выбранного узла дерева.
   - Если фокус в активном `FormDesignerWidget` (canvas/структура) или в его странице свойств — показываем свойства выбранного элемента формы.
   - В остальных областях интерфейса (меню/toolbar/пустая MDI) активная страница свойств не дёргается, чтобы избежать «мигания».

2) **Редактор форм — свойства убраны из интерфейса редактора**
   - `FormDesignerWidget`: панель свойств больше не в `QSplitter` (не занимает место в дизайнере).
   - Добавлен метод `properties_widget()` для отдачи панели свойств в общий док.

3) **Новая форма по умолчанию без «пустой таблицы» + авто-наполнение**
   - `default_form_model(...)`: убран placeholder `Table`.
   - `FormDesignerWidget`: добавлена логика `_maybe_autofill_empty_form()`:
     - если форма пустая и режим редактирования включён, генерируется стартовая компоновка
       **Label + Control** по дефолтным реквизитам владельца (`Catalog` / `Document` и т.п.).
     - используется тип реквизита → тип контрола (TextBox/NumberBox/DateBox/CheckBox/ComboBox/TextArea).

4) **Фон «рабочей области» (MDI) приведён к чисто белому**
   - `apply_hybrid_theme()`: `light_bg = "#FFFFFF"`.
   - `ConfiguratorWindow`: `QMdiArea.setBackground(QBrush(QColor("#FFFFFF")))`.

### Файлы
- `src/configurator/configurator_window.py`
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/configurator/domain/form_model.py`
- `src/ui_qt/theme.py`
- `src/docs/O_PRODELANNOI_RABOTE.md`


---

## 2026-01-21 — Редактор форм: "Конструктор" + "Виконання" как в 1С, отступы canvas и панель элементов

### Цель
- Сделать две центральные вкладки, аналогично 1С: **Конструктор** и **Виконання (Runtime)**.
- Убрать визуальный эффект «canvas вылезает за бордеры» (особенно снизу/справа) и выровнять фон.
- Добавить базовую **панель элементов (Toolbox)** для добавления контролов.

### Что сделано
1) `FormWindowFrame`
   - В клиентской области добавлен внутренний padding `12px` (экв. 10–15px), чтобы содержимое не упиралось в скруглённые границы.
   - Заданы явные фоны title bar / client area (client — белый), чтобы в hybrid-теме окно формы выглядело стабильно.

2) `FormDesignerWidget`
   - Добавлена вкладка **Toolbox** слева (перед "Requisites"):
     - двойной клик добавляет контрол в выбранный контейнер,
     - drag&drop на canvas работает для `absolute` компоновки.
   - Центральные вкладки:
     - `Design` → отображается как **Конструктор**,
     - `Preview` → отображается как **Виконання/Runtime**.
   - Для scroll/viewport/host выставлен `background: transparent`, а padding перенесён на уровень `FormWindowFrame`,
     чтобы фон canvas и фон окна формы воспринимались как единое полотно.

3) `i18n`
   - Обновлены подписи вкладок (Preview → Runtime, Design → Конструктор в uk).
   - Добавлены локализованные названия элементов для Toolbox (`form_ctl_*`).

4) Fix UX: фон конструктора и canvas
   - `FormDesignerCanvasView`: фон сцены/вью принудительно **transparent**, чтобы тёмная тема приложения
     не делала canvas «чёрным» и визуально не создавалось ощущение, что он выходит за скруглённые бордеры.
   - `FormDesignerWidget` (Design preview для non-absolute): контейнеры переведены на `NoFrame` + прозрачный фон,
     т.к. `StyledPanel` в тёмной теме рисовал тёмную заливку поверх белого `FormWindowClient`.
   - Клик по контролам в режиме **Конструктор** теперь **перехватывается** (eventFilter возвращает `True`),
     чтобы элементы не переходили в интерактивное состояние (ввод текста/фокус), а только выделялись.

### Файлы
- `src/ui_qt/widgets/form_window_frame.py`
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/ui_qt/widgets/form_designer_canvas.py`
- `src/ui_qt/i18n.py`


## 2026-01-22 — Form Designer: resize root form on canvas

- Added root resize handle (bottom-right) in `FormDesignerCanvasView` to allow changing form size with the mouse.
- Implemented live root size updates via `rootSizeChanged(w,h,finalize)` signal and synced with existing canvas size spinboxes.
- Enforced minimum canvas size (200×200) and prevented shrinking below extents of existing controls.


## 2026-01-22 — Form Designer: rubber-band selection + root resize constraints

Сделано:
- В режиме конструктора реализован **мультивыбор рамкой**: перетаскивание мышью по пустому месту рисует QRubberBand и выделяет элементы (IntersectsItemShape), не ломая перенос/resize элементов.
- Логика переключения `QGraphicsView.DragMode` **убрана** (всегда `NoDrag`) — устранены конфликты, из-за которых элементы могли «прыгать/хаотично двигаться» или некорректно менять размеры.
- Для изменения размера формы (root) добавлено вычисление **минимального размера от содержимого**: root нельзя уменьшить меньше `max(200×200, max(x+w,y+h)+margin)` по top-level элементам.
- Root resize handle позиционируется через `_update_root_handle_position()` после изменения размера.


## 2026-01-23 — Runtime Server: GUI admin for DB registry

Сделано:
- Добавлена серверная Qt-утилита **Runtime Admin** для управления реестром баз (`db_registry.json`): просмотр списка, добавление, редактирование, включение/отключение и удаление записей.
- Утилита работает поверх `src/runtime/db_registry.py` и сохраняет реестр в путь по умолчанию (ProgramData) либо выбранный вручную.
- Добавлены локализации (EN/UK) для GUI реестра.

Файлы:
- `src/ui_qt/runtime_admin_window.py`
- `src/ui_qt/runtime_admin_app.py`
- `src/scripts/run_runtime_admin_qt.py`
- `src/ui_qt/i18n.py`


## 2026-01-24 — Launcher: Wizard добавления БД (1C-like)

- Реализовано мастер-окно добавления БД (QDialog + QStackedWidget) с 3 сценариями: создание новой локальной БД, добавление существующей локальной БД, подключение к удалённой БД через runtime (db.list).
- В лаунчере кнопка «Добавити» теперь открывает мастер (вместо цепочки QInputDialog).
- Добавлены строки локализации (EN/UK) для мастера.

Файлы:
- `src/ui_qt/dialogs/add_db_wizard.py`
- `src/ui_qt/dialogs/__init__.py`
- `src/ui_qt/launcher_window.py`
- `src/ui_qt/i18n.py`


## 2026-01-24 — Client: Qt UI scaffold (navigation + header + placeholder views)

Сделано:
- Удалён временный **Tkinter**-клиент; клиент переведён на **PySide6**.
- Добавлен каркас окна клиента `ClientWindow`:
  - левое навигационное дерево (Dashboard / Справочники / Документы / Операции / Звіти / Налаштування),
  - верхний header (заголовок, поиск, кнопка «Создать»),
  - центральная область `QStackedWidget`.
- Добавлены заглушки представлений:
  - `DashboardView` (карточки-метрики как в генераторе),
  - `SimpleTableView` (универсальный список-таблица),
  - `PlaceholderView`.
- Подключены SVG-иконки (lucide) из `src/assets/icons/svg` для пунктов меню.
- В статус-бар выведен контекст подключения: runtime URL + session либо путь локальной БД.
- Добавлены локализации **EN/UK** для клиентской навигации и заглушек.

Файлы:
- `src/client/client_app.py`
- `src/client/client_window.py`
- `src/client/runtime_context.py`
- `src/client/views/dashboard_view.py`
- `src/client/views/simple_table_view.py`
- `src/client/views/placeholder_view.py`
- `src/ui_qt/i18n.py`


## 2026-01-25 — CatalogEditor: раздел «Підсистеми» (список с флажками)

Цель:
- В форме метаданных объекта (пока: **Справочник/Catalog**) добавить раздел **«Підсистеми»**.
- Отобразить список подсистем из дерева **Загальні → Підсистеми** с булевым флажком (включено/выключено).
- Хранить выбор в payload объекта (в MVP — списком GUID подсистем).

Сделано:
- `CatalogEditorWidget`:
  - Добавлен раздел `obj.section.subsystems`.
  - Реализована страница выбора подсистем на базе `QListWidget` с checkboxes.
  - Выбранные элементы сохраняются в payload ключом `subsystems: list[str]`.
- `ConfiguratorViewModel`:
  - Добавлены helper-методы `list_objects()` и `list_subsystems()` для UI‑списков.
- `ConfiguratorWindow`:
  - При открытии справочника передаётся список доступных подсистем (`available_subsystems`) в редактор.
- `i18n`:
  - Добавлены ключи `obj.section.subsystems`, `obj.subsystems_hint`, `obj.subsystems_empty` (EN/UK).

Файлы:
- `src/ui_qt/widgets/catalog_editor.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`


## 2026-01-25 — FormDesigner: persist формы + корректная работа с хранилищем конфигурации

Цель:
- Зафиксировать стабильный формат хранения модели формы в payload (`form_model` + `form_module`).
- Обеспечить сохранение/загрузку формы в MainDB и корректные операции **Put/Get** в хранилище конфигурации на уровне компонента **FormModule**.
- Исключить потерю изменений при закрытии редактора.

Сделано:
- `FormDesignerWidget`:
  - Добавлена обратная совместимость загрузки модели: принимаются `form_model` (dict), а также legacy-ключи `model`/`designer_model`/`form` и JSON-строка.
  - Добавлен диалог предупреждения о незбережённых изменениях при закрытии редактора (Yes/No/Cancel).
- `ConfiguratorViewModel`:
  - При переименовании формы (`form`/`common_form`) синхронизируется `form_model.title` и `form_model.name`, чтобы runtime/preview не показывали устаревшее название.
  - При создании формы сразу инициализируется payload ключами `form_model` и `form_module` (форма становится персистентной до первого явного сохранения).
- `ConfiguratorWindow` (Storage):
  - **Put** для компонента `FormModule` сохраняет только формо‑специфичные поля (`form_model`, `form_module`, legacy `module`) — меньше конфликтов и стабильнее diff.
  - **Get** для компонентных снапшотов выполняет merge patch в текущий payload вместо полного overwrite (не теряются нерелевантные ключи).
- `object_locks`:
  - Добавлен парсер `parse_lock_key()` для безопасной разбивки canonical lock key.

Файлы:
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/configurator/configurator_window.py`
- `src/configurator/persistence/object_locks.py`


---

## 2026-01-25 — Form Designer: auto-checkout + commit в хранилище конфигурации

### Что было
- Form Designer сохранял изменения только в MainDB через VM (`saveRequested`).
- Хранилище конфигурации использовалось вручную через контекстное меню дерева (Get/Put).
- Блокировки/checkout для формы в дизайнере не выполнялись автоматически, а ревизии в storage не писались из редактора.

### Что сделано
1) `ConfigStorageService`
   - Добавлен метод `commit(...)`: записывает ревизию и обновляет `HEAD`, **не снимая блокировку**.

2) `FormDesignerWidget`
   - При открытии формы, если storage подключено и задан `lock_key`, дизайнер подхватывает **latest snapshot** из storage и мержит `snapshot["payload"]` в локальный payload.
   - Добавлен **авто-checkout** (попытка захвата `FormModule`) при открытии формы в дизайнере.
   - При сохранении — помимо MainDB — выполняется `storage.commit(...)` (если блокировка принадлежит текущему клиенту).

### Инварианты
- Операции storage в редакторе должны быть **non-blocking**: любые ошибки storage не ломают локальное сохранение в MainDB.
- `commit(...)` не снимает lock; снятие происходит только через явный `submit/Put` или админский `force release`.

### Дополнительно
- `CatalogEditorWidget`: реализована вкладка **Forms** для объектов (на примере Catalog): список форм объекта, создание, открытие (в новом табе) и удаление, а также кнопка обновления.
- `ConfiguratorWindow`: передаёт `vm` и `obj_guid` в `CatalogEditorWidget`, чтобы редактор мог управлять дочерними объектами (формами).
- `i18n`: добавлены ключи `obj.forms_*` для EN/UK.
- `CatalogEditorWidget`: добавлены вкладки **Commands** и **Layouts** (список/создание/открытие/удаление) по аналогии с Forms.


## 2026-01-25 — Навигация по виртуальным секциям дерева (schema) и системным папкам

- Добавлено открытие по двойному клику для узлов kind=`schema` и системных папок (forms/commands/layouts): теперь открывается родительский объект и автоматически активируется соответствующая секция редактора.
- `ConfiguratorWindow.node_info_from_index()` расширен для обработки kind=`schema`.
- `ConfiguratorWindow.open_object_tab()` добавлен redirect `virtual:<parent_guid>:<section_key>` и mapping системных папок к секциям редактора.


---

## 2026-01-25 — Реквизиты и табличные части в редакторе метаданных + редактор документа

### Цель
- Довести «форму метаданных объекта» до состояния, когда ключевые элементы схемы (реквизиты/табличные части) редактируются прямо в UI.
- Расширить этот подход на второй базовый тип метаданных — **Документ**.

### Что сделано
1) Универсальные виджеты схемы
   - Добавлен `AttributesEditorWidget`: таблица реквизитов (имя/тип/обязательное/комментарий) с добавлением/удалением строк.
   - Добавлен `TabularPartsEditorWidget`: список табличных частей + редактор колонок выбранной табличной части.
   - Редакторы генерируют patch для payload (`attributes`, `tabular_parts`) и интегрируются с механизмом Apply в `MetaObjectEditorShell`.

2) CatalogEditorWidget
   - Добавлены секции **Attributes** и **Tabular parts**.
   - Встроенная правка сразу работает с виртуальными узлами дерева `schema` (переходы открывают объект и подсвечивают нужную секцию).

3) DocumentEditorWidget
   - Добавлен полноценный редактор документа на базе общего shell: Main, Subsystems, Attributes, Tabular parts, Forms, Commands, Layouts.
   - Подключено открытие редактора документа из дерева объектов.

4) i18n
   - Добавлены ключи секций и подписей таблиц/диалогов подтверждения для реквизитов и табличных частей (EN/UK).

### Файлы
- `src/ui_qt/widgets/schema_editors.py`
- `src/ui_qt/widgets/catalog_editor.py`
- `src/ui_qt/widgets/document_editor.py`
- `src/ui_qt/widgets/meta_object_shell.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/i18n.py`

## 2026-01-25 — Шаблоны схемы и автогенерация типовых форм

1) Шаблоны метаданных (MVP)
   - Добавлены дефолтные шаблоны `attributes` и `tabular_parts` для типов `catalog` и `document`.
   - Дефолты применяются идемпотентно при создании объекта (не перетирают существующую схему).

2) Автогенерация форм (MVP)
   - При создании `catalog`/`document` автоматически создаются 2 формы в системной папке `forms`:
     - `ФормаСписка` (subtype: `list_form`)
     - `ФормаОбъекта` (subtype: `object_form`)
   - Для форм генерируется базовый `form_model` на основе `attributes` (Table для списка, Label+TextBox для объекта).
   - Генерация выполняется только если в папке `forms` ещё нет форм.

### Файлы
- `src/configurator/domain/default_schema.py`
- `src/configurator/domain/form_templates.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/configurator/persistence/manifest_io.py`
- `src/configurator/application/service.py`
- `src/configurator/manifest_schema.py`


## 2026-01-25 — Кнопка «Згенерувати» в редакторе метаданных

1) MetaObjectEditorShell
   - Добавлена кнопка **Generate** рядом с Apply.
   - Добавлен сигнал `generateRequested`.

2) Диалог генерации
   - Добавлен `GenerateDialog` (выбор: схема/формы, режим: безопасный merge или overwrite).

3) ConfiguratorViewModel
   - Добавлен `generate_for_object(...)` для ручной генерации шаблонов существующего объекта.
   - Добавлен helper `_generate_typical_forms_for_owner(...)` для создания/обновления форм.
   - Исправлено ошибочное размещение блока автогенерации форм (раньше ломало файл из-за неверных отступов).

4) CatalogEditorWidget / DocumentEditorWidget
   - Подключена кнопка **Generate**: вызывает диалог и применяет генерацию.
   - После генерации редактор перечитывает payload, чтобы UI сразу обновлялся.

### Файлы
- `src/ui_qt/widgets/meta_object_shell.py`
- `src/ui_qt/widgets/generate_dialog.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/ui_qt/widgets/catalog_editor.py`
- `src/ui_qt/widgets/document_editor.py`
- `src/ui_qt/i18n.py`


## 2026-01-25 — Preview/Diff в диалоге «Згенерувати»

1) GenerateDialog
   - Добавлено поле **Preview** (read-only) с живым обновлением при смене опций.
   - Preview показывает, что будет создано/дополнено/перезаписано до применения изменений.

2) ConfiguratorViewModel
   - Добавлен метод `generate_preview_for_object(...)`, который рассчитывает превью без записи в manifest.
   - Превью включает оценку изменений для схемы (attributes/tabular_parts) и типовых форм (list/object).

3) CatalogEditorWidget / DocumentEditorWidget
   - Диалог генерации вызывается с preview_provider, который берёт данные из VM.

4) i18n
   - Добавлены ключи для текста Preview (EN/UK).

### Файлы
- `src/ui_qt/widgets/generate_dialog.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/ui_qt/widgets/catalog_editor.py`
- `src/ui_qt/widgets/document_editor.py`
- `src/ui_qt/i18n.py`

---

## Команды в превью/дизайнере форм (минимальный runtime-dispatch)

### Сделано
- В `FormDesignerWidget` добавлен минимальный диспетчер команд для тестирования в **Preview** вкладке.
- Кнопки типа `Button` с `props.command` теперь вызывают `_dispatch_command(...)`.
- Добавлены горячие клавиши для быстрого теста:
  - **Esc** → `Close`
  - **Ctrl+S** → `Save`
  - **Ctrl+Shift+S** → `SaveAndClose`
  - **F5** → `Refresh`
- `Refresh` перезагружает модель формы из последнего snapshot (если подключено конф. хранилище) и пересобирает Design + Preview.
- Нереализованные команды показывают `info_not_implemented`.

### Файлы
- `src/ui_qt/widgets/form_designer_widget.py`

---

## Клиент: открытие формы и dispatch команд (MVP)

### Сделано
- В `ClientWindow` добавлено меню **File → Open form…**, позволяющее открыть форму по GUID из локальной mpdb.
- Реализован `FormRuntimeWidget` — облегчённый runtime‑рендерер `form_model` (Container: vertical/horizontal/grid/absolute; Label/TextBox/Button/Table).
- Кнопки `Button` с `props.command` диспатчат команду в контекст клиента.
- Реализованы минимальные команды:
  - `Close` — возвращает на Dashboard.
  - `Refresh` — перечитывает `form_model` из manifest и пересобирает view.
  - остальные команды пока показывают `info_not_implemented`.

### Файлы
- `src/client/client_window.py`
- `src/client/forms/form_runtime_widget.py`
- `src/client/forms/__init__.py`
- `src/ui_qt/i18n.py`

---

## Клиент: навигация от метаданных и открытие типовых форм

### Сделано
- В `ClientWindow` добавлена попытка построить левое меню из **manifest** при наличии открытой mpdb.
- Если в базе есть пользовательские метаданные, меню строится так:
  - **Dashboard** всегда сверху.
  - Если существуют объекты типа **Subsystem** — выводится ветка **Subsystems → [подсистема] → [объекты]**.
  - Если подсистем нет — выводятся группы **Catalogs** и **Documents**.
  - Неназначенные объекты попадают в **Other**.
- Клик по объекту открывает **типовую форму** (по умолчанию `list_form`) из папки `forms` объекта.
  - Поиск формы происходит по `payload.subtype` (`list_form` / `object_form`) и системному GUID папки `forms`.
- Если типовой формы нет, отображается понятное сообщение с подсказкой сгенерировать типовые формы в Конфигураторе.

### Файлы
- `src/client/client_window.py`
- `src/ui_qt/i18n.py`

---

## 2026-01-26 — Form Designer: привязка к сетке и выравнивание (Design)

### Что добавлено
1) **Привязка к сетке (snap-to-grid)** для режима `layout = 'absolute'`:
   - при перемещении и изменении размера элементов;
   - при Drag&Drop добавления элементов на canvas;
   - сетка рисуется фоном в дизайнере (включается вместе со snap).

2) **Панель инструментов в Design**:
   - переключатель “Snap to grid”;
   - настройка “Grid step”;
   - 4 действия выравнивания **для множественного выделения** (Ctrl+click):
     - по левому краю;
     - по правому краю;
     - по верхнему краю;
     - по нижнему краю;
   - выравнивание выполняется **относительно последнего выбранного элемента**.

### Технические детали
- Canvas расширен новыми сигналами/методами:
  - `selectionSetChanged(count, primary_id)` — для управления доступностью команд;
  - `align_selected(edge)` — пакетное выравнивание без “дребезга” превью.
- Обновлена локализация (EN/UK): ключи для snap/grid/align.
---

## 2026-01-28 — Form Designer: Preview (Виконання) для absolute-форм + Qt6 DropAction

### Исправлено
1) **Невидимые кнопки/элементы в Preview** при `layout = 'absolute'`:
   - для абсолютных контейнеров дочерние виджеты теперь явно переводятся в видимое состояние и поднимаются по Z-порядку (`show()` / `raise_()` после `setGeometry()`).
   - после рендера превью принудительно сбрасывается прокрутка в (0, 0), чтобы верхняя зона (командные кнопки) не оказывалась “за кадром”.

2) **Qt6 scoped enums для DnD**:
   - заменено `Qt.CopyAction` → `Qt.DropAction.CopyAction` (default drop action + drag.exec).

### Файлы
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/docs/O_PRODELANNOI_RABOTE.md`

---

## 2026-01-28 — Form Designer: исправление SyntaxError в _refresh_design_surface

### Исправлено
- Устранён **SyntaxError** в `FormDesignerWidget._refresh_design_surface()` (случайно был добавлен лишний `except` без соответствующего `try`).
- Приведена структура `try/except` к корректной: обработка ошибок логируется один раз, затем UI продолжает работать.

### Файлы
- `src/ui_qt/widgets/form_designer_widget.py`
- `src/docs/O_PRODELANNOI_RABOTE.md`

---

## 2026-01-28 — Унификация MetaObject-редакторов (Catalog/Document): общий базовый класс

### Цель
Снизить дублирование кода между редакторами метаданных и стабилизировать общий функционал (Apply/Close/Generate + корректная перезагрузка payload после генерации).

### Что сделано
1) Добавлен **базовый класс** `MetaObjectEditorBase`, который инкапсулирует общий каркас:
   - `MetaObjectEditorShell` (секции слева + стек страниц);
   - сигналы `applyRequested(dict)` / `closeRequested()`;
   - единая обработка **Generate** через `GenerateDialog`;
   - корректный reload объекта после генерации (через `ConfiguratorViewModel.get_meta_by_guid`).

2) `CatalogEditorWidget` переведён на наследование от `MetaObjectEditorBase`:
   - убран дублирующий каркас (`QVBoxLayout + shell wiring`);
   - модель (`CatalogPayload`) теперь пересоздаётся в `_rebuild_model_from_payload()`;
   - обработчик Generate делегирован в базовый класс.

3) `DocumentEditorWidget` переведён на наследование от `MetaObjectEditorBase`:
   - убран дублирующий каркас;
   - модель (`DocumentPayload`) пересоздаётся в `_rebuild_model_from_payload()`;
   - Generate теперь полностью обслуживается базой.

4) Исправлена мелкая ошибка в `GenerateDialog`:
   - удалено **двойное создание** чекбокса `dlg_generate_commands` (дублировался).

### Файлы
- `src/ui_qt/widgets/meta_object_editor_base.py` (новый)
- `src/ui_qt/widgets/catalog_editor.py`
- `src/ui_qt/widgets/document_editor.py`
- `src/ui_qt/widgets/generate_dialog.py`
- `src/docs/O_PRODELANNOI_RABOTE.md`

---

## 9) 2026-02-01 — Импорт структуры 1C/BAS: промежуточная фиксация

### 9.1. Жёсткий повторный импорт
- Перед импортом из XML/ZIP показывается предупреждение о **разрушающем режиме**.
- Импорт выполняется через `ConfiguratorViewModel.import_onec_dump(..., mode="hard")`.
- В этом режиме конфигурация **перезаписывает** структуру метаданных (приоритет — новая конфигурация).

### 9.2. Секция **Модули** в дереве
- Добавлена системная секция `modules` в `src/core/object_policies.py`.
- Секция включена в политики большинства метаданных (аналогично `forms/commands/layouts`).
- Узлы-«наследие» (`forms/commands/layouts/modules`) скрываются через `is_legacy_object_folder_node`.

### 9.3. Ресурсы mpdb по ключам и поддержка REF
- В `ConfiguratorViewModel` добавлены методы:
  - `_resolve_asset(...)` / `resolve_asset_key(...)` — резолвинг semantic REF → raw key.
  - `get_text_asset(...)` / `save_text_asset(...)` — чтение/запись текстовых ассетов (UTF-8).
- `get_picture_asset(...)` и `save_picture_asset(...)` стали REF-aware.
- При сохранении ассета обновление выполняется **по ключу** (перезапись цепочки ассета).

### 9.4. Базовый редактор кода/текста
- Добавлен `src/ui_qt/widgets/code_editor_widget.py`.
- В `ConfiguratorWindow` включено открытие `CodeEditorWidget` для узлов с типом, содержащим `module`/`code`.


---

## 10) 2026-02-01 — mpdb: assets-table вместо META_ASSETS

### 10.1. Проблема
Ранее локатор ассетов (`key -> {first_page,size,mime}`) хранился в `META_ASSETS`. При глубоком импорте 1C/BAS (формы/модули и т.п.) количество ассетов растёт, и META начинает раздуваться до ошибки `Payload too large for page`.

### 10.2. Решение
- Добавлен новый внутренний механизм хранения локаторов ассетов в таблице mpdb: `__assets`.
- В `META` больше не накапливается огромный словарь ассетов; META остаётся компактной.

**Схема `__assets`:**
- `key` (unique)
- `first_page` (int)
- `size` (int)
- `mime` (string)

### 10.3. Совместимость
- Чтение (`get_asset` / `list_assets`) сначала пытается таблицу `__assets`, затем (если не найдено) падает в legacy `META_ASSETS`.
- При перезаписи ассета ключом (`put_asset` / `put_assets_bulk`) legacy-запись в `META_ASSETS` удаляется, чтобы META постепенно «схлопывалась».

### 10.4. Транзакционные bulk-операции
- В `Table` добавлены методы:
  - `insert_tx(tx, row, set_meta=...)`
  - `delete_tx(tx, where, set_meta=...)`
  Эти методы позволяют делать массовую перезапись локаторов ассетов в **одной транзакции** (быстрее и без лишних commit).

### Файлы
- `src/mpdb/mpdb.py`


## 13) 2026-02-02 — MPDB: защита от повреждённой базы при импорте (Page read failed)

Добавлен более устойчивый сценарий для жёсткого импорта конфигурации, когда существующая mpdb
повреждена/обрезана (например, после падения, незавершённой записи или несовместимых индексов).

Что сделано:
- улучшена диагностика ошибки чтения страниц: `Page read failed` теперь содержит смещение и размер файла;
- добавлен recovery-путь в `import_onec_configuration`: если mpdb не открывается или ловится `MpdbCorruptionError`,
  файл переносится в `*.corrupt-<timestamp>.mpdb`, создаётся новая mpdb и импорт повторяется один раз.

### Файлы
- `src/mpdb/mpdb.py`
- `src/tools/onec_import.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/docs/O_PRODELANNOI_RABOTE.md`


---

## 11) 2026-02-02 — Импорт 1C/BAS: «по‑взрослому» (wipe-prefix + модули как узлы)

### 11.1. Wipe-prefix с освобождением blob‑цепочек
Добавлен безопасный (и быстрый) способ очистки ранее импортированных ассетов по префиксам:
- `onec_raw/` (сырые файлы выгрузки)
- `onec/` (semantic REF)

Реализовано в `Mpdb.delete_assets_by_prefixes(...)`:
- удаляет локаторы из таблицы `__assets` и legacy `META_ASSETS`;
- освобождает blob‑цепочки через `_free_blob_chain(...)`, чтобы страницы реально возвращались в пул и mpdb не раздувалась при повторных импортах.

### 11.2. Hard import без «сноса» всей mpdb
Ранее `hard` импорт делал `os.replace(db → backup)` и пересоздавал mpdb.
Теперь:
- делаем **копию** mpdb в `*.backup-YYYYmmdd-HHMMSS.mpdb`;
- выполняем **reset только манифеста** (структура метаданных) без разрушения не‑конфигурационных данных.

### 11.3. UI‑опция «очистить импортированные ассеты»
В предупреждении «разрушающего импорта» добавлен чекбокс:
- **Wipe previously imported assets (onec_raw/, onec/) before import**
(UA‑локализация добавлена)

### 11.4. Модули как отдельные узлы в дереве (asset‑based)
Импортёр больше не пытается сохранять BSL как текст прямо в payload.
Вместо этого:
- модульные файлы `.bsl` остаются в `onec_raw/...`;
- создаются semantic REF ассеты `onec/...` (только для `.bsl`);
- в манифест добавляются дочерние узлы:
  - `module` / `form_module` в секции **modules**
  - payload содержит `module: { asset_key: "onec/<path>.bsl" }`, что напрямую открывается `CodeEditorWidget`.

### Файлы
- `src/mpdb/mpdb.py`
- `src/tools/onec_import.py`
- `src/infra/onec/importer.py`
- `src/configurator/configurator_window.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/ui_qt/i18n.py`
- `src/docs/O_PRODELANNOI_RABOTE.md`


## 12) 2026-02-02 — MPDB: совместимость со старыми ID сжатия ("Unknown compression type: 50")

Исправлена проблема при открытии существующей mpdb, созданной более ранней сборкой,
где в заголовках страниц/файла использовались другие числовые ID алгоритмов сжатия.

Что сделано:
- добавлены legacy-константы `CT_ZSTD_LEGACY = 50` и `CT_ZLIB_LEGACY = 51`;
- добавлена функция `_normalize_comp_type(...)` и применена при чтении:
  - заголовка файла (`_read_header`)
  - заголовков page-slot v1/v0 (`unpack_page_slot`)
  - при упаковке новых страниц (`pack_page_slot`)

Результат: база с `comp_type=50` открывается корректно (как ZSTD), а новые страницы
пишутся с текущими ID (`CT_ZSTD=1`, `CT_ZLIB=2`).

### Файлы
- `src/mpdb/mpdb.py`


## 13) 2026-03-01 — UI: восстановление локализации + корректные правила создания подузлов + открытие редакторов

### 13.1. Восстановление словаря локализации (uk/en)
Проблема: часть пунктов меню/контекстных действий отображалась как «сырой ключ» (`win_cascade`, `admin_users`, ...),
потому что ключи использовались в коде, но отсутствовали в таблице переводов.

Что сделано:
- добавлен модуль `src/ui_qt/i18n_extra.py` с автодополнением словаря (покрывает все ключи, используемые через `t(...)`);
- `src/ui_qt/i18n.py` теперь подхватывает и мержит `EXTRA_TR` при старте;
- проверка: для текущего кода отсутствующих ключей в `en/uk` больше нет.

### 13.2. Запрет создания подчинённых объектов в системной папке «modules»
Проблема: системные подпапки объекта (`forms/commands/layouts/modules`) хранятся в manifest с типом владельца,
и при правом клике на «modules» можно было создавать *не тот тип* (например, создавать `form` внутри «modules»).

Что сделано:
- для auto-папок разрешено создание **только** для секций `forms/commands/layouts`;
- для `modules` (и любых будущих системных секций без явного маппинга) создание отключено;
- в `create_options_for_node(...)` добавлен guard: системные/auto папки не получают общий пункт «Create…»,
чтобы не появлялись ложные варианты создания.

### 13.3. Исправлено открытие формы/редактора объекта метаданных (MDI)
Проблема: окна редакторов не появлялись из-за ошибки отступов в `open_object_tab(...)`
(логика `addSubWindow/show` была внутри локальной функции обработчика destroyed).

Что сделано:
- исправлена структура `open_object_tab(...)`: создание/показ `QMdiSubWindow` выполняется сразу,
а обработчик `destroyed` только чистит `_open_windows`.

### Файлы
- `src/ui_qt/i18n.py`
- `src/ui_qt/i18n_extra.py`
- `src/ui_qt/viewmodels/configurator_vm.py`
- `src/configurator/configurator_window.py`
- `src/docs/O_PRODELANNOI_RABOTE.md`


## 14) 2026-03-01 — Client: устранён падёж при запуске (отсутствовал `_manifest_rows`)

Проблема: `ClientWindow` падал при создании `DashboardView`, потому что вызывался метод
`self._manifest_rows()`, но в классе его не было (`AttributeError: 'ClientWindow' object has no attribute '_manifest_rows'`).

Что сделано:
- добавлен `ClientWindow._manifest_rows()` (защитный метод, возвращает `list_objects(db)` или пустой список);
- `DashboardView` сделан совместимым с разными версиями окна: принимает `db/manifest_rows` через параметры и игнорирует лишние `**kwargs`;
- на дашборде выводятся базовые счетчики по manifest (плейсхолдер-метрики), чтобы было видно, что manifest читается.

### Файлы
- `src/client/client_window.py`
- `src/client/views/dashboard_view.py`
- `src/docs/O_PRODELANNOI_RABOTE.md`

- 2026-03-07: Исправлен server-side импорт 1C/BAS через Runtime RPC: унифицирован _require_db(payload/session_id), возвращено подробное логирование onec.import, run_import_on_db переведён на физический reset manifest (удаление manifest из meta + повторное создание), добавлен best-effort recovery страницы из committed WAL в mpdb._try_recover_page_from_wal.


## 2026-03-07 — Безопасный staged import 1C + диагностика allocator mpdb

### Что сделано
1) Импорт 1С через Runtime переведён в безопасный режим `safe_mode=True` по умолчанию:
   - создаётся backup живой mpdb,
   - создаётся staging-копия,
   - импорт выполняется в staging,
   - staging перечитывается и валидируется,
   - только после успешной валидации staging подменяет основную БД в `DbPool`.

2) Для Runtime добавлена подмена открытого файла БД под тем же `db_uid`:
   - `DbPool.replace_with_file(...)`.

3) В `mpdb` добавлена принудительная физическая инициализация каждой freshly allocated page:
   - `_initialize_allocated_page(page_id)`
   - вызывается из `_alloc_page_id()` и `_alloc_page_id_extend_only()`
   - цель: исключить чтение нулевого/мусорного page slot на новых page id, особенно на границе бывшей WAL-области.

### Зачем
Проблема импорта воспроизводилась даже на чистой БД: новый `manifest` дорастал до page `89`, после чего чтение страницы падало с `Page id mismatch 0 != 89`. Это указывает не на XML/importer, а на проблему уровня allocator/page initialization в mpdb.

### Инвариант
Тяжёлые операции обновления конфигурации должны выполняться не в active DB, а по схеме:
`backup -> staging -> validate -> swap`.


## 2026-03-07 — Быстрый старт конфигуратора через structure cache

### Что сделано
- Добавлен кэш структуры конфигурации рядом с файлом базы: `*.structure_cache.json`.
- Добавлен RPC `manifest.info`, который возвращает:
  - `db_uid`
  - `db_path`
  - `structure_hash`
  - `object_count`
  - `generated_at`
- `ConfiguratorService.open_db()` теперь сначала пытается загрузить дерево из cache, если `structure_hash` совпадает.
- При отсутствии/устаревании cache выполняется обычный `manifest.open`, после чего cache пересохраняется.

### Инвариант
- Cache структуры не является источником истины. Источник истины — manifest в mpdb.
- Если cache отсутствует или устарел, конфигуратор обязан корректно перечитать структуру из Runtime RPC и пересоздать cache.
- В cache сохраняются только данные, достаточные для быстрого построения дерева (список manifest-объектов), без изменения бизнес-логики импорта.

## 2026-03-08 — Синхронизация документации проекта

### Что проверено
- `AGENTS.md`
- `ARCHITECTURE.md`
- `src/docs/O_PRODELANNOI_RABOTE.md`

### Что уточнено
1) Документация приведена к фактической структуре проекта:
   - есть отдельные подсистемы `client`, `ui_qt`, `runtime`, `configurator`, `mpdb`, `dsl`, `infra/onec`, `mp_platform`.
2) Зафиксировано, что штатный путь Configurator в текущей архитектуре идёт через `RuntimeGateway`/`GatewayDb`, а не через прямое открытие live-БД.
3) Зафиксировано, что `O_PRODELANNOI_RABOTE.md` является журналом инвариантов и исторических решений, а не общей архитектурной схемой.
4) Зафиксировано, что structure cache не является источником истины.
5) Добавлено явное различие между launcher/configurator/client/runtime admin как разными точками входа.

### Инвариант по документации
- `AGENTS.md` — краткий operational guide по репозиторию.
- `ARCHITECTURE.md` — актуальная архитектурная карта и принципы.
- `src/docs/O_PRODELANNOI_RABOTE.md` — decision log / changelog / инварианты.
- При расхождении между текстом и кодом первичным считается фактический код, а инварианты должны быть либо подтверждены кодом, либо отдельно пересмотрены.

## 2026-03-10 — WAL intent-record для атомарной релокации

### Что сделано
- В WAL добавлен служебный record `WAL_RELOCATE_INTENT` с payload:
  - `old_start`
  - `old_end`
  - `new_start`
  - `new_end`
- `_ensure_wal_after_pages()` переведён на crash-safe порядок:
  1. append intent в старый WAL;
  2. `fsync` intent;
  3. копирование полного WAL в новый диапазон;
  4. `fsync` нового диапазона;
  5. только после этого затирание старого префикса, который уже попадает в pages region;
  6. обновление in-memory WAL pointers.
- Recovery теперь умеет подхватывать relocated WAL после `end_of_pages`, если `META_WAL` ещё указывает на старый диапазон, но в новом потоке найден `WAL_RELOCATE_INTENT`.

### Инвариант
- При релокации WAL старый overlapping-префикс нельзя затирать до тех пор, пока новый WAL не стал durability-safe.
- Recovery обязан уметь найти новый WAL stream даже если crash произошёл между копированием WAL и последующей перезаписью META.

## 2026-03-10 — Вынесены minor-format миграции mpdb в migrations.py

### Что сделано
- Добавлен [src/mpdb/migrations.py](F:\MetaPlatform\src\mpdb\migrations.py) как канонический слой для `FORMAT_REV`.
- Поддерживаемый migration-path зафиксирован явно:
  - `format_rev=0 -> format_rev=1`
- При открытии существующей БД `mpdb` теперь:
  - читает `format_rev` из header,
  - валидирует его через migration-layer,
  - при необходимости поднимает legacy META до текущего minor-format,
  - переписывает header уже с актуальным `FORMAT_REV`.
- `doctor.py` переведён на тот же guard, чтобы проверка и runtime открытие принимали одинаковое множество minor revisions.

### Инвариант
- Любое изменение on-disk minor-format должно оформляться через `src/mpdb/migrations.py`, а не через неявные `setdefault()` в случайных местах `mpdb.py`.
- `FORMAT_REV` в header не должен только “разрешать открыть” старый файл; открытие должно либо прогнать явную миграцию, либо отказать при отсутствии migration-path.
## DSL language contract

- Public project DSL/UI languages are only `uk` and `en`.
- Russian source keywords stay supported only inside the internal import-compatibility pipeline for imported 1C/BAS modules.
- The editor UI must not expose Russian or `mixed` as a user-selectable working language.
- Module normalization must use the canonical keyword registry from `src/dsl/languages.py`, not a duplicate local map.

## 2026-03-13 — Контекстная нормализация импортированных 1C/BAS модулей

### Что сделано
- В `src/dsl/languages.py` добавлен канонический реестр контекстной нормализации идентификаторов:
  - builtin-функции в call-position,
  - методы коллекций после `.`,
  - конструкторы типов после `Новый/New`.
- `src/infra/onec/module_transform.py` переведён с простой keyword-only замены на контекстную нормализацию:
  - строки и комментарии по-прежнему не трогаются,
  - пользовательские идентификаторы не переводятся,
  - переводятся только встроенные функции/методы/конструкторы, когда синтаксический контекст однозначен.
- `src/dsl/vm.py` расширен украинскими алиасами builtin-функций и коллекций, чтобы нормализованный импортированный код исполнялся без отдельного русского runtime-режима.
- Добавлены регрессии на:
  - `ru -> uk` и `ru -> en` нормализацию builtin-функций,
  - перевод методов после точки,
  - перевод конструкторов после `Новый`,
  - parse/compile длинного импортированного BSL-фрагмента с `НСтр`, пропущенными аргументами и русскими логическими операторами.

### Инвариант
- Русский язык остаётся только языком входного импорта и внутренней совместимости; он не должен становиться каноническим runtime/UI языком проекта.
- Нормализатор не должен переводить произвольные имена переменных/параметров/реквизитов; допустим только контекстный перевод встроенных идентификаторов языка и платформенных builtin-ов.

## 2026-03-14 — Sparse-layout import и контракт правой панели свойств

### Что сделано
- В `src/infra/onec/layout_parser.py` spreadsheet parser научен учитывать sparse cell indexes (`<i>` внутри row cell), чтобы импортированные 1C-макеты не смещали ячейки по колонкам.
- В `src/ui_qt/widgets/layout_preview_build.py` preview ширин колонок больше не зависит только от первого `columns`-блока; используется максимальная пригодная ширина по всем наборам колонок макета.
- В `src/ui_qt/widgets/layout_preview_properties.py` и `src/ui_qt/widgets/form_designer.py` правая панель свойств переведена на единый контракт:
  - scrollable body для длинного списка полей,
  - pinned footer help-box внизу,
  - footer не прокручивается вместе с телом свойств.
- В `src/ui_qt/widgets/manifest_properties_panel.py` dynamic property rows теперь умеют показывать не только scalar payload, но и complex list/dict payload в readonly-виде, чтобы правая панель не теряла часть данных manifest.
- В `src/ui_qt/widgets/code_editor_widget.py` `Tab`/`Shift+Tab` для выделенного блока больше не затирают выделение и работают как indent/outdent строк.

### Инвариант
- Импортированный spreadsheet layout из 1C нельзя парсить как плотный массив ячеек; sparse column indices являются частью on-disk структуры и должны сохраняться.
- Правая панель свойств в configurator не должна собираться как один длинный статический layout без прокрутки; для длинных наборов свойств scroll-body и закреплённый footer help считаются обязательным UI-контрактом.

## 2026-03-14 — Безопасный rollback META и строгий seed manifest

### Что сделано
- В `src/mpdb/mpdb.py` `Transaction.abort()` теперь восстанавливает in-memory `db._meta` из снимка, взятого на `BEGIN`, чтобы упавшая транзакция не оставляла после себя частично изменённый manifest/table state.
- В `src/mpdb/mpdb.py` allocator перестал принимать невалидные page ids (`<= 1`) из legacy `free_pages` и on-disk freelist.
- В `src/configurator/persistence/manifest_io.py` `_insert_raw_if_missing()` больше не глотает любые storage-ошибки:
  - сначала проверяет наличие строки по `guid`,
  - после исключения перепроверяет, появился ли объект,
  - реальные ошибки вставки пробрасывает наружу как `manifest seed insert failed`.
- Добавлены регрессии на rollback in-memory META и пропуск `page_id=0` в allocator.

### Инвариант
- Aborted transaction в `mpdb` не должна оставлять `db._meta` в полуизменённом состоянии.
- Системный seed manifest не должен скрывать реальные ошибки storage-слоя под видом "объект уже существует".

## 2026-03-14 — Полнота phase 2/3 для 1C import и отказ от O(N*M) scans

### Что сделано
- В `src/infra/onec/importer.py` import plan больше не выбирается по схеме `dump-info OR base-plan`.
  Теперь canonical path такой:
  - строится полный `build_import_plan(paths)`,
  - поверх него накладывается `build_import_plan_from_dump_info(...)`,
  - `ConfigDumpInfo` может уточнять known objects/profiles, но не имеет права выкидывать типы, которых нет в `_DUMPINFO_ROOT_MAP`.
- В `src/infra/onec/importer.py` fallback-поиск child `Forms/Commands/Templates/Layouts` больше не сканирует весь `paths` для каждого объекта.
  Вместо этого строятся owner-prefix индексы один раз, а exact membership переведён на `path_set`.
- В `src/infra/onec/onec_requisites_source.py` parser теперь знает папку `Constants` и умеет отдавать progress callback при `parse_all(...)`.
- В `src/infra/onec/onec_requisites_xml.py` parser теперь распознаёт root tag `Constant -> constants`.
- В `src/runtime/server_handlers_import.py` phase 3 разделена на:
  - `parse`,
  - `enrich`,
  и enrich scope ограничен только теми manifest object types, которые реально поддерживаются requisites-parser'ом.
- Import manifest перестал автоматически раздувать import пустыми системными folders/stubs на phase 2; importer пишет только реально импортированные объекты и их непустые секции.

### Инвариант
- `ConfigDumpInfo` в import path является уточняющим индексом, а не источником права урезать импорт до подмножества типов.
- Phase 2 importer не должен выполнять повторный линейный scan всех `paths` для каждого metadata object; любые fallback lookup'ы для child forms/commands/layouts должны работать через предварительно построенные индексы.
- Phase 3 enrich не должен считать `module/form/layout/command` "no_match", если parser в принципе не возвращает эти типы как top-level requisites-objects.

## 2026-05-22 — Прямой semantic import из 1Cv8.1CD без обязательного XMLConf

### Что сделано
- `src/infra/onec/onecd_source.py` добавляет in-memory `OneCDConfigSource`: он читает живую `1Cv8.1CD` через Parse1CD backend, берёт `Params/DBNames` и `Config/<uuid>`, строит XMLConf-подобный источник `list_files()/read_bytes()`.
- `resolve_onec_source(...)` теперь допускает standalone `.1CD` как `semantic_kind="1cd"`. В режиме `auto` соседний XMLConf всё ещё предпочтителен как более полный источник; явный `source_kind="1cd"` принудительно использует прямой путь.
- Runtime/CLI import path принимает `semantic_kind="1cd"` и передаёт в существующий importer синтетический источник, поэтому phase 2/3 не получают отдельный legacy-путь.
- Configurator dialog теперь позволяет выбрать файл `1Cv8.1CD` напрямую; для `1Cv8.dt` без XMLConf прямой semantic import всё ещё не заявлен.
- Physical mapping при отсутствии XMLConf строит object catalog из DBNames/Config, чтобы `metadata_structure` и `storage_profile` не оставались пустыми.

### Проверено
- На `WorkedData/1Cv8.1CD` synthetic source построил 1376 metadata objects.
- Локальный smoke import во временную mpdb: `imported_files=1377`, `enriched=1376`, `structural_metadata_enriched=1376`, `semantic_source_kind=1cd`.

### Инвариант
- `.1CD` больше не должен требовать соседний XMLConf для базового semantic import в configurator.
- XMLConf остаётся richer-path для форм, модулей, макетов и полного vendor XML; direct `.1CD` path должен быть совместимым fallback поверх DBNames/Config, а не заменой XMLConf.

## 2026-05-26 — 1CD data migration: one batch, one transaction

### Что сделано
- В `src/infra/onec/data_migration.py` packed batch asset и packed rows теперь пишутся в одном внешнем `mpdb` transaction.
- Batch flush больше не делает отдельный `put_assets_bulk()` commit для `onec_data_rows/*`; используется локальный `_put_asset_tx(...)` и один `tx.set_meta(...)` на flush.
- Это убирает один полный commit/fsync на batch и сокращает общее число транзакций на этапе data migration.

### Проверено
- `python -m py_compile` для изменённых файлов прошёл.
- Smoke с fake backend подтвердил, что packed batch assets не идут через `put_assets_bulk()`, а финальный manifest asset остаётся на своём месте.

### Инвариант
- Packed-row offload для `.1CD` import не должен возвращаться к отдельному `put_assets_bulk()` commit per batch.
- Asset locator и row writes в flush должны жить в одном transaction.

## 2026-05-26 — Configurator tree: subsystem objects should render flat

### Что сделано
- В `src/ui_qt/services/tree_builder.py` subsystem-объекты проецируются в общую папку `Загальні -> Підсистеми`.
- Nested subsystem relations остаются в payload (`child_subsystems`) и используются direct `.1CD` import для восстановления иерархии.

### Проверено
- `python -m py_compile` для изменённых файлов прошёл.
- Smoke через file-loader с stub `PySide6` подтвердил, что и parent subsystem, и nested subsystem получают один и тот же parent GUID папки `subsystems`.

### Инвариант
- Дерево configurator для subsystem-объектов должно соответствовать 1C-like flat list в `Підсистеми`.
- Иерархия `child_subsystems` сохраняется как метаданные и, для direct `.1CD`, должна попадать в tree nesting через `parent_guid`.

## 2026-06-08 — Direct .1CD: subsystem hierarchy restored from Config

### Что сделано
- `src/infra/onec/onecd_source.py` теперь строит дерево подсистем из ссылок в `Config` и выдаёт nested XML paths вида `Subsystems/Parent/Subsystems/Child.xml`.
- Root subsystem XML теперь включает `<ChildObjects><Subsystem>...</Subsystem></ChildObjects>` для прямых дочерних узлов.
- Nested subsystem nodes больше не теряются на direct `.1CD` import и доходят до importer как реальная иерархия.

### Проверено
- `python -m compileall -q src/infra/onec/onecd_source.py` прошёл.
- Smoke на `WorkedData/1Cv8.1CD` показал вложенные пути для subsystem-узлов, включая ветки `Администрирование`, `ЗапасыИЗакупки`, `Маркетинг`, `Органайзер`, `ПодключаемоеОборудование`.

### Инвариант
- Для direct `.1CD` source subsystem hierarchy должна быть материализована в файловой структуре, а не только храниться в payload.

## 2026-05-26 — 1CD source: standard subsystems and scheduled jobs

### Что сделано
- `src/infra/onec/onecd_source.py` теперь берёт список подсистем из `Config/СтандартныеПодсистемы`, а не из устаревшего `Подсистема*`-префикса.
- В source добавлена поддержка `ScheduledJobs` как отдельного metadata kind/folder.
- `src/infra/onec/importer.py` получил поддержку `ScheduledJobs` в build plan и dump-info root map.

### Проверено
- `python -m py_compile` для изменённых файлов прошёл.
- Live smoke на `WorkedData/1Cv8.1CD` показал `subsystem=47` и `scheduled_job=57` вместо прежних 9 subsystem rows.

### Инвариант
- Standard subsystems должны быть определены через `СтандартныеПодсистемы`-row, а не через имя, начинающееся на `Подсистема`.
- `ScheduledJobs` должен проходить через synthetic XMLConf/import plan так же, как остальные common folders.

## 2026-05-31 — 1CD data completeness audit через optional COM

### Что сделано
- Прямой `.1CD` import остаётся основным production path; COM используется только как диагностический audit-layer по флагам CLI/RPC/env.
- Добавлен `src/infra/onec/com_data_audit.py`: строит отчёт `onec_com_data_audit/report.json`, считает row-backed объекты через 1C COM Query и сравнивает их с manifest прямой `.1CD` миграции.
- Исправлен COM query reader в `src/infra/onec/com_source.py`: значения выборки 1C через pywin32 читаются как dynamic properties, а не через string indexer.
- `src/infra/onec/data_migration.py` теперь обогащает физические таблицы через DBNames order: `logical_name`, `metadata_uuid`, `dbname_kind`, `table_role`.
- Физические таблицы `_INFORG*`, `_DOCUMENTJOURNAL*`, `_ACCUMRGT*`, `_BPRPOINTS*`, `_SCHEDULEDJOBS*`, `_REFSINF*`, `v8users` и related system tables больше не остаются ложным `unknown`.
- `mpdb` asset backend стал устойчив к asset rows, записанным в migration fast-mode: `get_asset/list_assets` видят такие записи, а `__assets` больше не теряет свои индексы в fast-mode.

### Проверено
- Полный импорт `WorkedData/1Cv8.1CD` в `com_audit_full.mpdb`: `.1CD` data migration импортировала 1493 таблицы и 195351 строку.
- COM audit по той же базе: 4395 metadata objects, 963 counted row-backed objects, 63929 rows visible via COM, 0 query errors.
- По `direct_primary_imported_rows` прямой `.1CD` импорт совпал с COM для основных row-backed объектов: catalogs, documents, enumerations, information/accumulation registers, business processes, tasks, exchange plans.
- `python -m compileall -q src`, `python -m src.scripts.selfcheck`, `pytest -q src/tests` прошли.

### Инвариант
- COM не должен становиться обязательной runtime/release dependency для импорта; он нужен для диагностики полноты и должен быть optional/non-fatal.
- Сравнение COM с `.1CD` должно учитывать `table_role`: object/register_data rows сравниваются с COM, а tabular_part/totals/slice/journal/system rows считаются физическим дополнением прямого импорта.
- `onec_data_migration/manifest.json` должен сохранять не только физическую таблицу, но и DBNames-derived привязку к объекту метаданных, когда она доступна.

## 2026-06-01 — Direct 1CD semantic import: формы, команды, общие объекты

### Что сделано
- `src/infra/onec/onecd_source.py` перестал ограничиваться `Params/DBNames`: теперь он читает корневые группы metadata из `Config` и строит полный XMLConf-like источник для общих объектов, отчётов, обработок, ролей, командных групп, картинок и шаблонов.
- Типы групп определяются универсально: сначала через DBNames-пересечение, затем через platform collection class-id 1C, а для неизвестных групп остаётся структурная эвристика по суффиксам, BSL и дочерним GUID. GUID конкретных объектов конфигурации не фиксируются.
- Дочерние `Forms`, `Commands` и `Templates` восстанавливаются из GUID-ссылок владельца; команды без базового `Config/<guid>` получают имя из named-object блока владельца и модуль из `Config/<guid>.2`.
- Суффиксы `Config/<uuid>.<n>` мапятся в XMLConf-like пути (`Ext/ObjectModule.bsl`, `Ext/ManagerModule.bsl`, `Ext/Form/Module.bsl`, `Ext/CommandModule.bsl`, `Ext/Template.xml`, `Ext/Help.xml`).
- Декодер Config BLOB теперь корректно обрабатывает raw-deflate payload с бинарным прологом и UTF-8 BSL-текстом, не проваливаясь в mojibake через cp1251.
- `src/infra/onec/importer.py` расширил dump-info root map для common объектов и поддержал `CommandModule` как модуль верхнего уровня.

### Проверено
- Synthetic source на `WorkedData/1Cv8.1CD`: 15812 файлов, 4480 BSL, 1853 form modules, 596 command modules, 522 object modules, 731 manager modules.
- Сравнение с `WorkedData/XMLConf`: отсутствующих модулей осталось точечно (`CommandModule`: 13, `FormModule`: 18, `ObjectModule`: 17, `ManagerModule`: 14) вместо тысяч пропусков и пустых форм.
- Structural smoke import в `structure_smoke_direct_1cd.mpdb`: `plan specs=4395`, `skipped=0`, `Assets imported=15812`, `Objects enriched with requisites/tabular-parts=2176`, `structural metadata=11551`.
- В smoke import каталог `Номенклатура` получил 4 реквизита, 3 табличные части, 17 форм, 13 команд; `ФормаЭлемента` получила module asset и child `form_module`.
- `pytest -q src/tests/test_onecd_source.py src/tests/test_onec_importer.py` и `python -m compileall -q ...` прошли.

### Инвариант
- Direct `.1CD` semantic import не должен привязываться к GUID конкретной конфигурации; допустимы только platform-level class-id 1C для определения типа коллекции, если тип не выводится из DBNames/структуры.
- XMLConf остаётся эталоном для сравнения полноты, но не обязательным источником при прямом `.1CD` semantic import.
- Дочерние формы/команды/шаблоны должны импортироваться под владельцем, а не попадать в `CommonForms/CommonModules` по эвристике имени.

## 2026-06-01 — 1C import: украинский синтаксис модулей

### Что сделано
- `src/infra/onec/importer.py` теперь сохраняет импортируемые BSL-модули через `normalize_module_text(..., language="uk")`, поэтому исполняемый код попадает в `mpdb` в украинском DSL-синтаксисе.
- CLI post-step `_create_localized_module_variants(...)` больше не копирует один и тот же текст в `uk/en`: украинская строка нормализуется в `uk`, английская строка нормализуется в `en`.
- `src/infra/onec/module_transform.py` теперь считает `//` строчным комментарием так же, как `'`, поэтому нормализация не переводит кодовые слова внутри комментариев.

### Проверено
- Structural smoke import в `structure_smoke_direct_1cd_uk.mpdb`: `plan specs=4395`, `skipped=0`, `Assets imported=15812`, `Objects enriched with requisites/tabular-parts=2176`, `structural metadata=11551`.
- Сравнение с `WorkedData/XMLConf`: direct `.1CD` synthetic source содержит `15812` файлов и `4480` BSL против `20483` файлов и `4552` BSL в XMLConf; по модулям осталось точечно отсутствующих `FormModule=18`, `CommandModule=13`, `ObjectModule=17`, `ManagerModule=14`.
- Audit импортированных модулей после повторной `uk`-нормализации: `renormalize_changed=0`, английских code-token'ов не найдено; `По` остаётся каноническим keyword target из `src/dsl/languages.py`.
- `python -m compileall -q src`, `pytest -q src/tests`, `python -m src.scripts.selfcheck` прошли.

### Инвариант
- Импортируемый исполняемый код из 1C должен по умолчанию храниться и редактироваться в украинском DSL-синтаксисе.
- Нормализация синтаксиса переводит ключевые слова и известные builtin/method aliases; произвольные идентификаторы, имена обработчиков, строки и комментарии не переводятся до появления отдельного semantic symbol translation layer.
- Raw source assets могут оставаться в исходном виде для диагностики, но `cfg_modules` и runtime/configurator read-path должны отдавать нормализованный код.

## 2026-06-02 — Parse1CD 8.3: восстановление привязки таблиц данных

### Что сделано
- Добавлен `src/infra/onec/parse1cd_compat.py`: patch-layer для Parse1CD, который восстанавливает `Files` у 8.3 table descriptors, если старый parser нашёл таблицу и поля, но оборвал descriptor до секции `{"Files", data, blob, index}`.
- `src/infra/onec/physical_schema.py` и `src/infra/onec/data_migration.py` подключают этот patch-layer при загрузке Parse1CD backend.
- `OneCDMetadataObject` теперь хранит отдельный `dbname_order`: semantic `order` остаётся для стабильного XMLConf-like дерева, а физическая привязка таблиц 8.3 строится по DBNames suffix.
- `src/infra/onec/data_migration.py` использует `dbname_order` для `metadata_uuid/logical_name`, чтобы физические `_REFERENCE/_DOCUMENT/_INFORG/...` таблицы не матчились по semantic order.
- `ConfiguratorViewModel._payload_for_guid()` теперь определяет тип объекта не только из object snapshot, но и из `_meta_by_guid`: common module с пустым snapshot payload снова гидратит полный `module` payload через manifest service.
- `src/runtime/server_handlers_manifest.py` больше не гидратирует весь manifest ради `manifest.get_payload`: один GUID читается через `list_object_rows()` и точечную hydration одного payload.

### Проверено
- Live check на `WorkedData/1Cv8.1CD`: Parse1CD output изменился с `Привязано: 1404/1409` до `Привязано: 1409/1409`; непривязанных таблиц не осталось.
- Проблемные таблицы до фикса: `_ACCUMRGTN9803`, `_DOCUMENT12256_VT14835`, `_INFORG11571`, `_INFORG11741`, `ConfigCASSave`.
- `python -m compileall -q src`, `pytest -q src/tests` и `python -m src.scripts.selfcheck` прошли.

### Инвариант
- Для формата 8.3 отсутствие `data_object_id` у найденной таблицы не должно молча считаться нормой: сначала нужно попытаться восстановить `Files` из descriptor pages, затем из совместимого read-only Parse1CD backend.
- Физическая привязка таблиц данных должна использовать DBNames suffix (`dbname_order`), а не semantic order synthetic metadata tree.
- Tree meta может хранить облегченный payload; editors/read-path должны гидратить полный payload из object snapshot или manifest service перед открытием импортированных модулей.

## 2026-06-07 — Фільтр дерева конфігурації по підсистемі

### Що зроблено
- В `src/ui_qt/services/tree_builder.py` додано `_apply_subsystem_filter(objs, subsystem_guid)`:
  - залишає тільки об'єкти, у яких `payload.subsystems` містить `subsystem_guid`;
  - автоматично зберігає всіх предків таких об'єктів (групи, папки), щоб дерево не "обривалося".
- `prepare_tree_objects()` отримав новий параметр `subsystem_filter_guid: str = ""`;
  фільтр застосовується після search (пусто — без фільтру).
- У `ConfiguratorVmTreeMixin._populate_tree()` передається `subsystem_filter_guid=self._subsystem_filter_guid`.
- У `ConfiguratorViewmodel` додано поле `_subsystem_filter_guid: str = ""`.
- `on_subsystem_filter(guid)` в `ConfiguratorVmEditorActionsMixin` встановлює фільтр і перебудовує дерево.
- У `ConfiguratorWindow` додано `QComboBox cb_subsystem_filter` у ліву панель (під полем пошуку);
  combo прихована, якщо підсистем нема.
- `refresh_subsystem_filter_combo()` викликається з `end_tree_rebuild()` — оновлює список підсистем після кожного перебудови дерева.
- Сигнал `subsystemFilterChanged` з'єднаний з `vm.on_subsystem_filter`.

### Інваріант
- Фільтр підсистем у дереві базується виключно на `payload.subsystems` кожного manifest-об'єкта.
- При порожньому `subsystem_filter_guid` фільтр не застосовується — дерево показує всі об'єкти.
- Combo підсистем відображається лише якщо в конфігурації є хоча б одна підсистема.

## 2026-07-18 — Єдиний обчислювач виразів і параметризовані точки зупину

### Що зроблено
- Додано Qt-незалежний `src/dsl/expression_eval.py`: швидкий безпечний Python-subset і fallback у внутрішній `mixed`-профіль MetaScript тепер спільні для `Shift+F9` та умов точок зупину.
- Вирази підтримують українські/імпортні логічні оператори, стандартні літерали та читабельні alias для CP1251-mojibake ідентифікаторів.
- `BreakpointSpec` розширено параметрами викликаючого методу, кількості потраплянь, журналювання опису/виразу/стека, автоматичного продовження та поточного runtime-лічильника.
- Debug runtime зберігає лічильник потраплянь у спільному `BreakpointStore`, тому configurator бачить фактичне значення debug-клієнта.
- Підрахунок виконується один раз на досягнення вихідного рядка, а не на кожну VM-інструкцію. Точне повторне досягнення рядка в циклі знову активує точку; fallback `±1` залишається лише для звичайної непараметризованої точки.
- Діалог `Ctrl+F9` отримав редагування всіх runtime-параметрів і скидання поточного лічильника.
- Додано offscreen Qt-регресію на позиціонування паузи, фактичну стрілку в gutter, очищення паузи через `F5` та команди `F10/F11/Shift+F11`.

### Інваріант
- Усі IDE/runtime-поверхні повинні обчислювати debug-вирази через єдиний DSL-сервіс; окремі карти операторів або літералів у UI і debugger заборонені.
- Hit count означає кількість досягнень вихідного рядка, а не кількість виконаних байткод-інструкцій.
- Параметризована точка зупину прив'язана до точного рядка; сусідній fallback не повинен змінювати семантику умови або лічильника.

## 2026-07-18 — Виконуваний модульний рівень і сумісність імпортованого коду

### Що зроблено
- AST/parser приймають виконувані оператори на рівні модуля, compiler збирає їх в окремий `__module_init__`, а VM виконує ініціалізатор до стартової процедури.
- Ініціалізація виконується рівно один раз для пари module/context; оголошені та обчислені глобальні значення залишаються доступними процедурам модуля і debugger expression evaluator.
- Debugger може зупинятися всередині `__module_init__`, але службові `__mp_*` значення runtime не потрапляють у користувацький список змінних.
- AST зберігає контекстні анотації 1C/BAS (`&НаКлиенте`, `&НаСервере` та параметризовані варіанти), включно з їх передачею у compiled module.
- Parser дозволяє keyword-подібні імена змінних циклу та унарний `+` без втрати вихідної семантики.
- Додано динамічний конструктор `Новий(Тип, ...)` / імпортний `Новый(Тип, ...)`: compiler використовує `NEW_DYNAMIC`, VM приймає ім'я типу, type descriptor або callable constructor.
- String lexer дотримується BSL-семантики: зворотний слеш є звичайним символом, а подвоєний обмежувач усередині літерала утворює одну лапку; одинарні літерали збережено лише як import-compatibility розширення MetaScript.

### Перевірено
- Виконання модульного ініціалізатора, повторне використання context, runtime builtin і debug-пауза покриті окремими parser/VM/debugger тестами.
- Профільні parser/VM/debugger/Qt тести пройшли: `47 passed`.
- Після підтримки динамічного конструктора corpus-аудит імпортованих XMLConf-модулів покращився з `4437/4552` до `4449/4552`; compiler-помилок після успішного parse немає.
- Після завершення BSL compatibility-проходу весь еталонний корпус `WorkedData/XMLConf` проходить lexer/parser/compiler: `4552/4552`, помилок `0`.

### Інваріант
- Код рівня модуля є частиною runtime-семантики, а не лише текстом редактора; стартова процедура не може виконуватися раніше завершення ініціалізатора цього модуля.
- Позначка одноразової ініціалізації належить runtime context і не повинна відображатися як користувацька глобальна змінна.
- Синтаксична сумісність 1C/BAS реалізується через загальні мовні конструкції, а не через винятки для GUID або тексту конкретної конфігурації.
- Lexer не повинен інтерпретувати C/Python escape-послідовності у BSL-рядках; значення `Literal` має без додаткових перетворень проходити через AST, compiler і VM.

## 2026-07-18 — Повна parser-сумісність XMLConf і startup-контекст клієнта

### Що зроблено
- BSL number lexer підтримує десяткові літерали без дробової частини (`0.`), не змішуючи їх з member access (`1.Property`).
- Слова preprocessor (`Область`, `Region`, `Використати` та import aliases) є звичайними ідентифікаторами без `#`; директиви розпізнаються тільки окремою PP-таблицею після `#`.
- Multiline BSL strings обробляють continuation-prefix `|`, зберігають перенос між сегментами та пропускають вихідні `//`-коментарі між continuation-рядками.
- Додано окремий `ExecuteStmt` і bytecode `EXECUTE`: оператор `Выполнить`/`Виконати`/`Do` компілює динамічний MetaScript через штатний parser/compiler і виконує його у поточному VM scope без Python `eval`.
- Compile-directives всередині продовженого виразу більше не обривають expression parser; compatibility-marker `&КонецОбласти` не створює фальшиву declaration annotation.
- Startup клієнта точково гідрує root configuration payload і `module://GUID` через runtime-backed `GatewayDb`, не завантажуючи повний manifest.
- Managed/session/ordinary startup modules використовують спільний persistent context у pre/post фазах; module initializer виконується один раз, а globals доступні наступним модулям.
- `ПередНачаломРаботыСистемы(Отказ)` може скасувати запуск, phase fingerprint встановлюється тільки після виконання, debug line mapping зберігає вихідні номери рядків.

### Перевірено
- Повний corpus-аудит `WorkedData/XMLConf`: `4552` BSL-модулі, `4552` parse+compile success, `0` failures.
- Повний аудит закріплено CLI-командою `python -m src.scripts.audit_dsl_corpus [root] [--json]`; будь-яка parse/compiler помилка завершує gate ненульовим кодом.
- Startup/client + VM + debugger: `57 passed`.
- Language focused tests після фінального compatibility-проходу: `64 passed`; `selfcheck` і `py_compile` пройшли.

### Інваріант
- Release-gate мовної сумісності повинен перевіряти всі `4552` еталонні XMLConf-модулі; точкова вибірка не замінює повний corpus-аудит.
- Dynamic execute використовує тільки MetaScript parser/compiler/VM і поточний frame scope; передача тексту в Python `eval/exec` заборонена.
- Startup-модулі однієї конфігурації мають спільний контекст і стабільні `module://GUID`; pre-фаза завершується до показу UI, post-фаза запускається після bootstrap.
- Startup read-path не повинен викликати повний `manifest.list`, якщо root payload і module GUID можна отримати точково через runtime.

## 2026-07-18 — Узгодження form designer і клієнтського runtime

### Що зроблено
- Виправлено синхронізацію вкладок центральної області form designer і координати drop-target для вкладених контейнерів.
- Legacy command panel нормалізується в горизонтальний `CommandBar` лише коли wrapper/table справді утворюють одну панель; одиночна звичайна кнопка більше не змінює тип автоматично.
- Role editor будує сторінку прав одразу та показує права і шаблони обмежень у вкладках замість вертикального splitter.
- Клієнтська форма використовує єдиний `QTabWidget` для структури і форми, тому відкриття вкладок не розходиться між actions і runtime.
- Навігація клієнта використовує lightweight nav cache і лише як сумісний fallback вже завантажений manifest cache; повторного RPC по кожному рядку немає.
- Runtime manifest warmup скасовується без traceback, якщо БД закрита до старту worker.

### Інваріант
- Командна панель форми повинна зберігати горизонтальне компонування в designer і client runtime; звичайні окремі кнопки не є командною панеллю.
- Клієнт будує навігацію зі структурного індексу та гідрує payload об'єкта на вимогу; повний manifest не повинен повторно читатися для кожного відкриття.
- Фоновий warmup не має працювати з уже закритою БД і не повинен друкувати необроблений traceback під час штатного teardown.

## 2026-07-18 — Повна ревізія Configurator: цілісність збереження, RPC і реактивний form designer

### Що зроблено
- Збереження payload тепер перечитує авторитетний об'єкт через Runtime перед patch; помилка read/write не замінює повний payload частковим UI snapshot і не запускає reload.
- Externalized form asset після успішного запису залишається гідратованим у локальному override; при відмові RPC form designer і profile editor зберігають dirty/pending state та не закривають вкладку.
- Глобальне `Save` і запуск клієнта перевіряють результат усіх відкритих редакторів та стану manifest; Qt signal більше не маскує помилку збереження.
- `manifest.get_payload` читає один рядок за GUID і не викликає повний scan або mutating migration у read-path.
- Старт Configurator приймає structure cache лише після звірки live `structure_hash` і стану файлу; при timeout `manifest.info` використовується read-only recovery без `manifest.open`.
- Фонові refresh отримали epoch guard: відповідь від старої/закритої БД не може перезаписати дерево після reopen/import.
- Читання та запис модулів, а також schema deployment переведені на спеціалізовані Runtime RPC-команди.
- Debug orchestration має єдиного власника `F5/Shift+F5`, реальний threaded control API, abort paused VM під час stop/close та коректне очищення debug pause marker.
- `DbPool.open_by_path` дедуплікує повторне відкриття live-файлу; `session.close` звільняє RPC-сесію Configurator, залишаючи спільну базу прогрітою у Runtime-службі.
- `db.open` більше не переміщує файл і не створює порожню БД при довільній помилці відкриття; repair/replacement дозволені лише як явна backup/staging операція.
- `CommandBar` серіалізує дочірні кнопки у плоский runtime-формат; звичайна горизонтальна група кнопок більше не класифікується як command bar без семантичного маркера.
- Реактивний preview зберігає активну сторінку `Tabs`; новий `Tabs` одразу має першу сторінку, наступні сторінки додаються з дерева.
- Internal drag/drop дерева форми відхиляє цикли та вкладення у leaf-control; буфер форми більше не передає custom MIME у системний Windows clipboard, що усунуло native crash після Qt-тестів.

### Перевірено
- Повний regression gate: `637 passed`.
- `python -m src.scripts.selfcheck`: усі перевірки пройдені, включно з `Debug smoke` і Qt SVG render.
- Окремі процесні перевірки Qt завершуються з кодом `0`, без прихованого access violation після успішних assertions.

### Наступна черга
1. Перенести legacy `repo_bridge` checkout/submit/force-unlock на атомарні Runtime RPC-команди; UI не має відкривати main live `mpdb` напряму.
2. Додати optimistic concurrency для manifest payload/assets: revision/CAS, conflict response і merge/reload dialog замість last-write-wins.
3. Перевести module browser/global search з DAO-over-Gateway на server-side index/search RPC.
4. Завершити debugger як IDE-протокол: locked cross-process breakpoint store, hot refresh активної сесії, expression evaluation у живому paused VM та module-aware call stack navigation.
5. Додати dirty/close contract до всіх допоміжних profile/dialog editor і повний редактор сторінок/команд `Tabs`/`CommandBar`, а не лише структурні операції.

### Інваріант
- Жодна команда UI не може очищати dirty state, закривати редактор або запускати клієнт, доки Runtime не підтвердив persisted save.
- Read-only RPC не виконує міграції та не сканує повний manifest, якщо запит адресований одному GUID.
- Runtime-сесія належить одному UI-підключенню; live `mpdb` належить Runtime-службі та може безпечно повторно використовуватися наступними сесіями.
- Помилка відкриття БД не є дозволом на автоматичну заміну файла; будь-яке відновлення потребує явної команди та резервної копії.
- Реактивний render не змінює активну сторінку або структуру форми; модель, designer і client runtime використовують один JSON-контракт.

## 2026-07-18 — Атомарне завантаження тексту модулів

### Що зроблено
- Помилка Runtime RPC під час відкриття або повторного завантаження модуля більше не очищає редактор і не створює хибний dirty-стан.
- Успішний remote read застосовується до редактора однією операцією із заблокованим `textChanged`; стан завантаження та остання помилка зберігаються окремо від користувацьких змін.
- `Save` повертає реальний результат, перечитує збережений текст через Runtime та не дозволяє закрити dirty-вкладку, якщо запис не підтверджено.

### Інваріант
- Транспортна помилка не є зміною документа: останній відомий буфер, dirty-стан і debug-позиція мають залишатися недоторканими до успішної відповіді Runtime.

## 2026-07-18 — Єдиний покажчик поточної debug-позиції

### Що зроблено
- Нова debug-пауза очищає banner, context panel і стрілку в усіх інших редакторах модулів того самого вікна Configurator.
- `Continue`, `Step into`, `Step over` і `Step out` одразу прибирають старий instruction pointer; наступна стрілка з'являється лише після наступної фактичної паузи VM.
- Control API повертає стан debug-маркерів відкритих редакторів і підтримує MDI-розкладку для фонової перевірки міжмодульних переходів.
- Windows restart спочатку перериває активну debug-паузу та звільняє control socket, потім запускає новий Configurator і завершує старий Qt event loop.

### Інваріант
- Одна debug-сесія має рівно один видимий instruction pointer незалежно від переходів між модулями.

## 2026-07-18 — Повний scope для обчислення debug-виразів

### Що зроблено
- Debug snapshot фільтрує процедури та функції до застосування ліміту globals, тому оголошені модульні змінні не витісняються службовими `CodeObject`.
- Через міжпроцесний control API передається до 250 безпечних data-globals; змінна, яка ще не отримала значення, обчислюється як `Невизначено`, а не як невідоме ім'я.
- Після `Continue` або кроку застарілий pause snapshot видаляється і не може використовуватися наступним `Shift+F9`.
- Локальний control API вміє обчислити вираз у поточній активній паузі без продовження VM, що дає відтворювану фонову перевірку того самого scope, який використовує діалог `Вираз`.

### Інваріант
- Вираз обчислюється тільки у scope поточної активної паузи; завершена пауза не є допустимим джерелом locals/globals.

## 2026-07-18 — Міжмодульний startup-debug і повернення значення загального модуля

### Що зроблено
- Виклик `ЗагальнийМодуль.ЕкспортнаФункція()` виконується через lazy `CommonModuleRegistry` у тій самій `DebugSession`, що й стартовий модуль; debugger переходить у `module://GUID` загального модуля та повертається у caller без окремого debug-вікна.
- Runtime resolution загальних модулів використовує прогрітий manifest index і process-local descriptor cache; повторний startup не сканує повний manifest для кожного dotted-виклику.
- BSL scope розділяє оголошені модульні змінні та локальні присвоєння процедур; повернене значення зберігається у спільному startup context і доступне через `Shift+F9` після завершення виклику.
- Debugger дедуплікує source line окремо для кожного VM frame: повернення з вкладеного загального модуля більше не викликає повторну хибну паузу на тій самій caller-стрічці.
- Control API отримав команди `launch_debug_client`, `stop_debug_client`, `debug_client_status`, `debug_command`, `breakpoints_list` і `breakpoint_set`; breakpoint update зберігає інші модулі та підтримує фоновий end-to-end цикл без ручної взаємодії.
- Відкриття debug-редактора очікує асинхронну гідратацію модуля до 30 секунд і повторно застосовує pause marker перед підключенням команд, тому повільне перше відкриття не втрачає instruction pointer.
- `manifest.nav` на cache-hit фільтрує прогрітий `STATE_MANIFEST_LIST_CACHE`, а не перечитує всі manifest rows з БД повторно.

### Перевірено
- На live-базі `F:\TestBD\MetaDB\metabase.mpdb` виклик `ОткрытиеФормПриНачалеРаботыСистемыВызовСервера.ФормаНачальнойНастройкиПрограммы()` зупинився у загальному модулі на рядках `19` і `41`.
- На рядку повернення локальна `ИмяФормы` дорівнює `ОбщаяФорма.ВыборВариантаНастройкиПрограммы`.
- Після повернення caller пройшов `87 -> 90`; глобальна `глФормаНачальнойНастройкиПрограммы` має те саме значення, тип `str`, список помилок порожній.
- Профільні debugger/control API/Qt тести: `43 passed`.
- Повний regression gate: `678 passed`; `selfcheck`, `py_compile` та Qt debug smoke пройшли.
- Повний corpus-gate `WorkedData/XMLConf`: `4552/4552`, помилок lexer/parser/compiler немає.
- На live-базі `manifest.list(slim)` повертає `19607` рядків за `0.1514 с`, а два послідовні `manifest.nav` повертають `1006` рядків за `0.0408 с` і `0.1095 с` замість попередніх `11–25 с`.

### Наступний фактичний бар'єр startup
- Після успішного міжмодульного виклику імпортована БСП-логіка доходить до перевірки `СтандартныеПодсистемыПовтИсп.ПараметрыПрограммныхСобытий`, де допоміжні дані `ПараметрыСлужебныхСобытий` ще не містять `ОбработчикиСобытий`. Це окрема задача гідратації конфігураційних service parameters, а не помилка resolver, compiler, VM або повернення функції.

### Інваріант
- Breakpoint caller-рядка спрацьовує один раз на фактичне виконання цієї рядки; вкладений VM загального модуля не скидає frame-local дедуплікацію caller.
- Усі стартові та загальні модулі одного запуску використовують одну `DebugSession`; `Step Into`, call stack, locals/globals і instruction pointer не можуть розходитись між окремими debug-вікнами.
- Control API не має очищати або замінювати breakpoint-и інших модулів під час точкового upsert/remove.

## 2026-07-18 — IDE-компоновка редакторів форм і коду

### Що зроблено
- Редактор форм приведено до адаптивної трипанельної схеми `структура / робоча область / властивості`; центральна панель більше не вимагає 720 px і не витісняє інспектор у вузькому MDI-вікні.
- Режими `Макет / Перегляд / Модуль` отримали фактичний стиль `QTabBar`; попередній stylesheet мовчки падав через некоректні дужки f-string і не застосовував chrome взагалі.
- Панель форми використовує справжні локалізовані icon-команди замість `+ / Dup / Up / Down`, короткі назви вкладок та перемикачі видимості структури й властивостей.
- Виправлено корінь каталогу IDE-іконок і додано SVG fallback з кольоровим render; icon-only команди редактора коду більше не є порожніми кнопками.
- Редактор коду отримав вертикальний splitter `код / debug context / diagnostics`, компактний primary-toolbar та overflow для розширених breakpoint-команд.
- Реально підключено заявлені shortcuts `Ctrl+S`, `Ctrl+F` і `Ctrl+F7`; перенесення editor surface у splitter не ламає `F5/F9/Shift+F9` завдяки пошуку IDE-host по ланцюжку Qt-батьків.
- Dirty-стан коду і форми змінює заголовок MDI та блокує закриття дочірнього або головного вікна до `Save / Discard / Cancel`; помилка save не дозволяє втратити буфер.

### Перевірено
- Профільний Qt gate редакторів і MDI lifecycle: `102 passed`.
- Live Configurator після self-restart показує робочі іконки, компактний toolbar, локалізовані вкладки, resizable debug panel та панельні перемикачі форми.

### Інваріант
- Жоден MDI або головний close не може обійти `confirm_close()` dirty-редактора.
- Основна панель редактора коду має вміщатися у стандартне MDI-вікно 740 px; розширені breakpoint-операції доступні через overflow, але не роздувають primary-toolbar.
- UI редактора форм не містить hardcoded англійських підказок і оновлює вкладки, команди та accessible names при зміні `uk/en`.

## 2026-07-19 — 1C-подібне IDE-робоче місце форми, autocomplete і `Метадані`

### Що зроблено
- Form designer перебудовано у T-подібне робоче місце: зверху ліворуч `Елементи / Командний інтерфейс`, зверху праворуч `Реквізити / Команди / Параметри`, знизу реактивна форма.
- Головні вкладки перенесено на нижню межу та перейменовано на `Форма / Модуль`; режим `Модуль` приховує обидві верхні панелі й віддає редактору коду всю внутрішню сторінку, а повернення на `Форма` відновлює попередні пропорції splitter.
- Панелі команд розділено на команди форми, стандартні та глобальні; подвійний клік додає командну кнопку у модель форми. Панель реквізитів показує ім'я та тип, а форма-модуль отримує реквізити, команди й параметри у власний completion scope.
- Автодоповнення редактора коду стало контекстним: розбирає незавершені dotted-ланцюжки, замінює лише поточний сегмент і враховує module vars, процедури, функції, локальні змінні лише активного scope та індекс метаданих конфігурації.
- Додано канонічний платформний об'єкт `Метадані / Метаданные / Metadata` з колекціями типів та стабільними властивостями metadata object; form module і startup runtime використовують спільний lazy-контекст без повного читання manifest на кожне звернення.
- IDE-індекс і runtime resolver відновлюють CP1251-mojibake з імпортованого `title`, тому поруч із внутрішнім `Kontrahenty` доступне вихідне звернення `Метадані.Довідники.Контрагенты`.
- Control API отримав `form_editor_state`, `form_editor_tab` і `form_editor_completion`: геометрію, вкладки й semantic completion тепер можна перевіряти у фоновому Configurator без керування мишею або активним екраном.

### Перевірено
- На live-базі `F:\TestBD\MetaDB\metabase.mpdb` редактор форми відкрито за GUID `1565c0aa-b558-4544-a796-2c16bfca21a0`; control API підтвердив дві нижні вкладки `Форма / Модуль`, дві структурні та три object-data вкладки.
- У live-режимі вкладка `Модуль` розгортає код на всю внутрішню сторінку; повернення до `Форма` відновлює T-компоновку.
- Live completion для `Метадані.Довідники.Контр` повертає `Контрагенты`; кириличне ім'я також знаходиться runtime metadata collection.
- Профільний Qt/DSL/runtime/control API gate: `111 passed`.
- Повний regression gate: `690 passed`; `python -m src.scripts.selfcheck` повністю пройдено, включно з Qt SVG render і Debug smoke.

### Інваріант
- Вкладки `Форма / Модуль` знаходяться знизу; `Модуль` не може ділити внутрішню робочу сторінку з деревом форми, реквізитами або toolbar макета.
- Autocomplete не виконує повний manifest RPC під час набору: імена беруться з уже завантаженого structure cache, а runtime гідрує metadata collection ліниво через індексований lookup.
- Внутрішня транслітерація імпорту не є публічним API мови: вихідне кириличне ім'я 1C має працювати у completion, `Find` і dotted-доступі `Метадані`.

## 2026-07-19 — Каталог типів елементів форми

### Що зроблено
- Команда `Додати` у дереві елементів і на toolbar форми більше не залежить від прихованого combo: вона відкриває модальне локалізоване вікно `Тип елемента`.
- Каталог повторює звичну модель 1C: окремо доступні звичайна група, група без відображення, сторінки, командна панель, поле, кнопка, таблиця, напис та розширені типи MetaPlatform.
- Вибраний пункт повертає тип моделі разом із початковими властивостями. Звичайна група створюється із заголовком і representation `usual`, а група без відображення з `representation=none` і прихованим заголовком.
- Діалог підтримує подвійний клік, `Enter`, `OK / Скасувати / Довідка`, локалі `uk/en` і штатну темну тему без нечитабельних alternating rows.

### Інваріант
- UI-каталог не створює фіктивних типів: кожний доступний пункт має відповідати control type, який реально підтримують form model, designer і client runtime.
- Прихований toolbox залишається тільки compatibility-шаром для drag-and-drop; публічна команда `Додати` завжди дає користувачу явний вибір типу.

## 2026-07-19 — Компактні дерева редактора форми

### Що зроблено
- Рядки структури форми, реквізитів, команд, параметрів і командного інтерфейсу ущільнено: прибрано подвійні відступи global/local QSS, висота структурного рядка становить `22px`, indentation — `18px`.
- Стандартне Qt-виділення decoration lane замінено власним малюванням: selected-фон покриває тільки прямокутник елемента з текстом і не заливає весь лівий коридор вкладеності.
- Розкриття вузла виконує окрема кнопка `14x14` із шевроном. Клік у порожній області відступу не змінює selection і не розгортає вузол; клік у межах кнопки перемикає стан.

### Інваріант
- Глибина вкладеності не може збільшувати площу selected-фону; branch lane завжди залишається фоном панелі.
- Mouse hit-area розкриття дорівнює видимій кнопці, а keyboard та double-click навігація дерева залишаються штатними.

## 2026-07-19 — Клієнтська видимість елементів форми

### Що зроблено
- Властивість 1C `<Visible>` проходить єдиним контрактом `FormNode.props.visible`; відсутнє значення означає `true`, а legacy-ключі `is_visible`, `user_visible` і `visibility` нормалізуються під час завантаження моделі.
- У властивості елемента додано локалізований прапорець `Видимий у клієнті / Visible in client`. Значення залишається draft до явного збереження форми та записується у зовнішній `form_model` asset у `mpdb`.
- Client runtime виключає приховані вузли з layout разом з їх зовнішніми підписами, вкладеними сторінками та прихованими кнопками командної панелі.
- Designer runtime працює з `show_hidden_controls=true`: прихований для клієнта елемент не зникає з IDE, залишається доступним для selection, drag-and-drop і редагування та позначається пунктирною рамкою і текстом у дереві.
- Початкова selection дерева після відкриття форми тепер одразу синхронізує панель властивостей; властивості дочірнього вузла більше не показують неініціалізовані значення кореня.

### Перевірено
- Профільний importer/model/runtime/designer gate: `128 passed`.
- Повний regression gate: `700 passed`; `selfcheck` пройдено повністю, включно з manifest policies, Qt SVG render і Debug smoke.
- На live-базі `F:\TestBD\MetaDB\metabase.mpdb` форма `1565c0aa-b558-4544-a796-2c16bfca21a0` містить збережений вузол `label_316` (`Без ПДВ`) з `visible=false`.
- Фоновий Qt smoke підтвердив: у client runtime для `label_316` немає render-вузла, а Designer створює його wrapper з ознакою `form_hidden_in_client=true`.

### Інваріант
- Configurator завжди повинен дозволяти розробнику побачити й відредагувати вузол незалежно від його клієнтської видимості; `visible=false` застосовується лише до preview/client runtime.
- Прихований вузол не займає місця у клієнтському layout і не залишає видимий title-label.

## 2026-07-19 — Межі форми без зовнішньої горизонтальної прокрутки

### Що зроблено
- Client runtime забороняє горизонтальну прокрутку зовнішньої поверхні форми; `width_chars` задає бажану максимальну ширину поля, але більше не перетворюється на жорстку ширину, яка розсуває форму.
- Заголовки полів і спільна колонка підписів можуть стискатися у вузькому viewport. Командні кнопки також мають нульову мінімальну ширину й не змушують контейнер виходити за межі форми.
- Абсолютна runtime-компоновка масштабує координати й ширину елементів до доступної ширини, зберігаючи їх відносне положення; імпортована геометрія спочатку обмежується design-boundary.
- Canvas редактора обмежує початкову та збережену геометрію абсолютного елемента розмірами батьківської групи або кореневої форми. Внутрішні та зовнішні form-preview scroll area не показують горизонтальну смугу; IDE-frame займає доступну ширину до design-максимуму.
- Абсолютний IDE-canvas застосовує лише горизонтальний view-transform, тому широке design-полотно повністю видно у вузькому редакторі, а координати й розміри у моделі не змінюються.
- Власна горизонтальна прокрутка таблиці залишається допустимою: вона прокручує колонки всередині табличного елемента, а не всю форму.

### Перевірено
- Вузькі runtime-форми `320px` з полем `width_chars=200` та абсолютним елементом за правою design-межею мають `horizontalScrollBar().maximum() == 0`; правий край поля залишається всередині viewport.
- Профільний runtime/designer gate: `84 passed`.
- Повний regression gate: `705 passed`; `selfcheck` і `py_compile` пройдено.

### Інваріант
- Жоден елемент форми не може збільшувати зовнішню ширину client form surface або вимагати горизонтальної прокрутки всієї форми.
- Після завершення drag/resize абсолютний елемент повністю знаходиться всередині геометрії свого батьківського контейнера; вихідна некоректна геометрія не відтворюється за межами canvas.

## 2026-07-19 — Робоча область і окремі вікна форм

### Що зроблено
- Корінь `form_model` отримав незалежні властивості `open_mode` (`auto / workspace / window`) та `window_lock_mode` (`none / owner / interface`). Вони редагуються у властивостях форми, локалізовані для `uk/en` і зберігаються разом з моделлю форми у `mpdb`.
- `auto` залишає звичайні форми у вкладках робочої області клієнта, а форми обробок і загальні форми відкриває як окремі вікна. Явний режим завжди має пріоритет над типовою політикою об'єкта.
- Обробка відкриває основну `object_form`, а не каталожний список записів; коректна форма лише з командами або декораціями не замінюється автогенерованою через відсутність полів введення.
- Окрема форма має системні кнопки згортання, розгортання та закриття, змінюваний розмір і підтримує немодальний режим, блокування вікна-власника та блокування всього інтерфейсу.
- XML-властивість 1C `WindowOpeningMode` імпортується без втрати семантики: `LockOwnerWindow` стає `window + owner`, `LockWholeInterface` — `window + interface`; вихідне значення зберігається у `source_window_opening_mode`.
- Команди runtime, запис, проведення, копіювання, оновлення та закриття працюють через єдиний form-widget незалежно від способу показу. Окреме вікно має dirty-маркер, не закривається мовчки з незбереженими даними та враховується під час завершення клієнта.

### Перевірено
- У `WorkedData/XMLConf` знайдено `753` форми з `WindowOpeningMode`; імпорт обох режимів блокування покрито тестами.
- Фокусний importer/model/designer/client gate: `142 passed`; `selfcheck` і `py_compile` пройдено.
- Повний regression gate: `713 passed`.
- Live Configurator після self-restart показує у властивостях кореня `Відкривати форму у` та `Блокування вікна`.

### Інваріант
- Форма робочої області є частиною клієнтської вкладки та не може довільно перетворюватися на системне вікно. Окреме вікно не реєструється у вкладках і завжди має власний window lifecycle.
- Розміщення та модальність є різними властивостями: режим блокування не може заміняти або неявно змінювати збережений `open_mode`.

## 2026-07-19 — Очищення робочої поверхні редактора форми

### Що зроблено
- Із центральної робочої області прибрано дубльовану текстову підказку та панель сітки, додавання, видалення, переміщення і вирівнювання.
- Основні структурні команди залишаються на toolbar дерева елементів, а точне редагування виконується через drag-and-drop, властивості та контекстне меню.
- Внутрішні grid/alignment actions збережено як compatibility-шар для чинної логіки canvas, але вони не займають місце над формою.

### Інваріант
- Над form surface не повинно бути окремого дубльованого toolbar: після нижніх вкладок робоча область одразу починається з рамки форми.

## 2026-07-22 — Гідратація форм безпосередньо з `.1CD`

### Що зроблено
- Імпортер форм тепер читає не лише XML-вивантаження, а й вкладений brace-потік, який `OneCDConfigSource` відновлює з `Config` у `1Cv8.1CD`. Парсер підтримує багаторядкові `#base64:`-атоми й більше не обриває форму на бінарних властивостях.
- Із серіалізованої форми відновлюються групи, сторінки, командні панелі, кнопки, поля, таблиці та їх колонки. Для дерева IDE зберігається технічне ім'я 1C у `designer_name`, а підпис клієнтського елемента залишається локалізованим. Нормалізація `CommandBar -> TablePanel` окремо зберігає технічні імена панелі та команд, тому IDE не підміняє їх клієнтськими title.
- Ієрархія реквізитів редактора містить корінь `Об'єкт`, системні поля, звичайні реквізити та табличні частини з вкладеними колонками. Таблиці у дереві елементів показують віртуальну командну панель, команди й колонки без зміни збереженої form model.
- Помилки читання тіла форми більше не ковтаються: у `imported.form_body_origin` зберігається джерело, а у `imported.form_body_error` — точний тип і текст помилки. Старі `MOXCEL` та інші бінарні форми розпізнаються окремо й не маскуються під XML-помилку.
- Runtime RPC отримав пакетне оновлення payload для справних БД. Для поточної live-бази, де повний scan виявив пошкоджені сторінки, виконано безпечну точкову гідратацію за GUID без прямого паралельного доступу до `mpdb`.

### Перевірено
- На `F:\TestBD\MetaDB\metabase.mpdb` оброблено `1840` form-об'єктів: `1710` form model записано, `49` вже були заповнені, `46` не мають тіла форми у джерелі, `34` належать до старих `MOXCEL` і `1` до іншого бінарного формату; помилок читання й запису немає. Для всіх `35` непідтриманих тіл точну діагностику записано у live-manifest.
- `Документ.АвансовыйОтчет.ФормаДокумента` (`2b8ebb9e-a52d-4fa4-b5de-242198f87a6c`) відтворює технічне дерево груп і сторінок, чотири табличні частини з командами та колонками, а також повну ієрархію реквізитів об'єкта.
- Повний regression gate: `751 passed`; `python -m src.scripts.selfcheck` пройдено повністю.

### Інваріант
- Якщо у формі є доступний `Ext/Form.xml`, звичайна XML або brace-серіалізована форма не може потрапити у manifest без `form_model`; будь-який непідтриманий формат повинен залишити явний `form_body_error`.
- Технічне ім'я елемента 1C є ідентифікатором IDE, локалізований title використовується для preview/client і не може підміняти структуру дерева розробника.

## 2026-07-22 — Відновлення компоновки груп серіалізованих форм

### Що зроблено
- Виправлено декодування звичайних груп у brace-потоці `.1CD`: значення mode `5` описує тип групи, але не її напрямок. Горизонтальна або вертикальна компоновка тепер читається з вкладеного запису властивостей групи.
- Із того самого запису відновлюються `representation` (`None`, `Usual`, `WeakSeparation`, `NormalSeparation`, `StrongSeparation`) і `show_title`. Контейнери більше не втрачають оформлення та заголовки під час прямого імпорту з `.1CD`.
- Для чинної live-бази точково оновлено `Документ.АвансовыйОтчет.ФормаДокумента`; масове оновлення лише властивостей контейнерів було зупинено storage-перевіркою на вже пошкодженій сторінці `Page id mismatch 0 != 22004`, без прямого доступу UI до `mpdb`.

### Перевірено
- На live-формі `2b8ebb9e-a52d-4fa4-b5de-242198f87a6c` групи `ГруппаШапка`, `ГруппаНомерДата`, `ГруппаПодвал` і `ГруппаИтого` мають `layout=horizontal`, а вкладені ліві/праві групи залишаються вертикальними.
- Профільний importer gate: `47 passed`; окремий regression-тест перевіряє напрямок, оформлення, заголовок і вкладений елемент серіалізованої групи.

### Інваріант
- Напрямок звичайної групи серіалізованої форми не можна визначати за mode елемента. Джерелом істини є вкладений запис властивостей групи; його оформлення й `show_title` повинні зберігатися разом із layout.

## 2026-07-22 — Контекстні дії всередині полів форми

### Що зроблено
- Поле та його стандартні дії тепер рендеряться як єдиний inline-контрол зі спільною рамкою без проміжків. Кнопки вибору, очищення й відкриття не створюють окремих вузлів `form_model` і не з'являються у дереві елементів IDE.
- Для посилального реквізиту за схемою автоматично додаються `вибрати / очистити / відкрити`; явні властивості 1C `ChoiceButton`, `ClearButton` і `OpenButton` мають пріоритет над автоматичним режимом. Read-only поле не отримує дії, що змінюють значення.
- Вибір відкриває наявний reference picker, очищення прибирає видиме значення та збережений GUID, відкриття передає клієнту тип метаданих і GUID та відкриває object form відповідного запису.
- Поля дати отримали nullable-стан: календар залишається штатною вбудованою кнопкою `QDateEdit`, поруч у тому самому контролі доступне очищення, а порожня дата більше не підміняється поточною датою або технічним мінімумом.
- Для `uk/en` додано окремі tooltip-підказки стандартних дій.

### Перевірено
- Runtime/client gate: `41 passed`; перевірено автоматичний склад кнопок посилання, спільну рамку, очищення значення й GUID, сигнал відкриття поточного запису та очищення дати.
- Live-preview `Документ.АвансовыйОтчет.ФормаДокумента` показує посилальні поля як єдині контроли з трьома контекстними діями, а дату — з календарем та очищенням.
- Повний regression gate: `754 passed`; `python -m src.scripts.selfcheck` пройдено повністю.

### Інваріант
- Стандартна дія поля є поведінкою самого поля, а не самостійним елементом форми. Її наявність визначається явною властивістю 1C або типом прив'язаного реквізиту; у manifest не можна синтезувати окремі кнопки для цих дій.

## 2026-07-22 — Декорації форми та безпечна активація імпорту

### Що зроблено
- `LabelDecoration` із порожнім заголовком імпортується як розпірка компонування: технічне ім'я залишається у `name/designer_name`, але не підміняє порожній клієнтський текст. У `form_model` явно зберігаються `is_decoration`, `decoration_kind` і `layout_spacer`.
- Runtime показує непорожню декорацію як напис, а порожню — як невидимий просторовий елемент із заданими шириною, висотою та розтягуванням. Горизонтальний контейнер не обнуляє мінімальну ширину такої розпірки.
- Редактор властивостей отримав окремі параметри декорації: вид, доступність, підказку, горизонтальне й вертикальне вирівнювання, розміри та розтягування. Зміна заголовка реактивно перемикає семантику розпірки.
- Відкриття імпортної сесії після restart runtime використовує канонічний шлях бази з view model, а не покладається на застарілий process-local GUID.
- Читання сторінки `Mpdb` синхронізовано з `close()`: старий handle після `backup -> staging -> validate -> swap` більше не може повертати сторінки зі свого LRU-кешу. Виправлено також формування page slot під час аварійного відновлення сторінки з WAL.

### Перевірено
- Після повного safe-import із `WorkedData/1Cv8.1CD` live-manifest містить `19705` об'єктів. У `Документ.АвансовыйОтчет.ФормаДокумента` декорації `Декорация1` і `ДекорацияИтоги` мають порожній `title`, `is_decoration=true` та `layout_spacer=true`.
- Runtime-preview не показує технічні назви порожніх декорацій; обидві розпірки присутні у layout.
- Регресійні тести перевіряють XML/brace-імпорт, реактивні властивості IDE, runtime-відображення порожніх і текстових декорацій та заборону читання кешу через закритий DB-handle.

### Інваріант
- Порожній заголовок декорації типу `label` означає просторовий елемент компонування. Технічне ім'я не можна використовувати як fallback для її клієнтського тексту.
- Після закриття `Mpdb` жоден reader не може отримати дані навіть із локального cache-hit; safe swap завжди відсікає старий handle від активного файлу.

## 2026-07-27 — Перехід до визначення в редакторі коду

### Що зроблено
- Редактор модулів отримав навігацію `F12` і `Ctrl+Click`. Вона розпізнає локальні процедури, функції та змінні, виклики експортних методів загальних модулів і ланцюжки `Метадані / Metadata`.
- Локальне визначення відкривається в поточному редакторі. Загальний модуль відкривається або активується в MDI на точному рядку процедури чи функції. Посилання на об'єкт метаданих відкриває відповідний редактор об'єкта.
- Та сама навігація підключена до модуля форми. Відкриття зовнішнього модуля використовує спільний механізм Configurator, тому повторний перехід не створює дубльованих вікон.
- Позиція звичайної навігації відокремлена від поточної інструкції debugger: `F12` переміщує курсор, але не створює жовту стрілку і не змінює справжній рядок паузи.
- Control API отримав дію `code_editor_go_to_definition` для автономної наскрізної перевірки навігації на live-базі.

### Перевірено
- На live-базі перехід зі стартового модуля, рядок `83`, за викликом `ОткрытиеФормПриНачалеРаботыСистемыВызовСервера.ФормаНачальнойНастройкиПрограммы()` відкрив модуль `b1ea1574-1b1a-5a03-88ec-f855fe7ef4e1` на рядку `24`.
- Профільний gate редактора коду, редактора форм і control API: `127 passed`.
- Повний regression gate: `761 passed`; `python -m src.scripts.selfcheck` пройдено повністю.

### Інваріант
- Перехід до визначення не є кроком debugger і не може встановлювати або переносити маркер поточної інструкції.
- Зовнішня навігація повинна використовувати фактичний GUID module asset, а не GUID власника загального модуля.

## 2026-07-27 — Пошук використань та runtime-індекс модулів

### Що зроблено
- Редактор модулів і модуль форми отримали команду `Shift+F12`. Кваліфікований виклик шукається у всіх модулях, а локальний ідентифікатор обмежується поточним модулем або областю процедури.
- Результати відкриваються у немодальному вікні глобального пошуку. Пошук виконується у фоновому потоці, тому Configurator залишається доступним під час сканування; подвійний клік активує наявне вікно модуля на точному рядку.
- Читання текстів модулів винесено з UI у Runtime RPC `modules.search_text`. Runtime одноразово гідратує `cfg_modules`, зберігає нормалізовані тексти у пам'яті та скидає індекс після зміни модуля, нормалізації мови або заміни файлу БД.
- Регістронезалежний пошук не запускає `re.IGNORECASE` і не будує карту рядків для кожного модуля. Він використовує попередньо нормалізований literal-індекс, перевіряє межі ідентифікатора та обчислює рядок і колонку лише для знайдених модулів.
- Control API отримав дії `code_editor_find_usages`, `code_editor_show_usages` і `code_editor_usages_state` для перевірки даних, відкриття реального UI та читання його результату без ручної взаємодії.

### Перевірено
- На live-базі пошук виклику `ОткрытиеФормПриНачалеРаботыСистемыВызовСервера.ФормаНачальнойНастройкиПрограммы()` повертає один результат: стартовий модуль, рядок `83`, колонка `39`.
- Холодне побудування індексу на `19705` об'єктах займає `4.75 с`; повторні пошуки того самого символу виконуються за `39–43 мс`.
- Через Control API відкрито фактичне немодальне вікно: `visible=true`, статус `Знайдено: 1`, результат містить правильний рядок вихідного коду.
- Повний regression gate: `767 passed`; `python -m src.scripts.selfcheck` пройдено повністю.

### Інваріант
- Configurator не сканує таблицю модулів і не гідратує module assets напряму. Глобальний текстовий пошук виконує Runtime, а UI отримує лише компактні координати та preview.
- Індекс є прискорювачем, а не джерелом істини: будь-яка зміна модуля або заміна live-БД повинна інвалідовувати його до наступного запиту.

## 2026-07-27 — Семантичне перейменування символів модуля

### Що зроблено
- Редактор модуля та модуль форми отримали стандартну IDE-команду `Shift+F6`. Перед зміною відкривається локалізоване вікно з поточним і новим ім'ям, областю символу та точним переліком входжень.
- Semantic planner працює на токенах DSL та module introspection. Він розрізняє параметри, локальні й модульні змінні, процедури та функції; рядки, коментарі й однойменні властивості після крапки не змінюються.
- Для локальних символів враховується область процедури. Для модульних символів враховується shadowing параметрами й локальними змінними; конфлікт з наявним ім'ям блокує застосування до зміни тексту.
- Усі заміни застосовуються до реактивного буфера одним edit block і повністю скасовуються одним `Undo`. Запис у СУБД виконується лише штатною командою збереження редактора.
- Control API отримав `code_editor_rename_preview` для автономної перевірки плану та `code_editor_rename_apply` для застосування до активного буфера без прихованого збереження.
- Помилки, типи символів і колонки preview локалізовано для `uk/en`; mixed DSL підтримує український синтаксис і сумісний імпортований синтаксис 1C.

### Перевірено
- Профільний gate semantic planner, Qt-діалогу, редактора коду та Control API: `69 passed`.
- Перевірено виключення рядків, коментарів і member access, shadowing, конфлікти, український і сумісний синтаксис, `Shift+F6`, preview endpoint та повне скасування одним `Undo`.
- Повний regression gate: `779 passed`; `python -m src.scripts.selfcheck` пройдено повністю.

### Інваріант
- Семантичне перейменування не може бути звичайною текстовою заміною: кожне входження повинно належати тому самому символу та допустимій області видимості.
- Поточна команда змінює лише один module asset. Перейменування експортного API між модулями не можна вмикати до появи runtime-плану залежностей, перевірки конфліктів у всьому workspace та атомарного збереження всіх змінених модулів.

## 2026-07-27 — Workspace-preview перейменування експортного API

### Що зроблено
- Runtime RPC отримав `modules.rename_symbol_plan`. Він працює над прогрітим індексом вихідних текстів, повторно перевіряє declaration module через lexer/module introspection і дозволяє план лише для експортної процедури або функції.
- План змінює оголошення та локальні виклики у вихідному модулі, а в інших модулях — лише точні кваліфіковані токени `Ім'яМодуля.Метод`. Рядки, коментарі, вкладені member chains та випадкові текстові збіги виключаються.
- Кожен module plan містить GUID, читабельне ім'я власника, координати входжень, hash поточного тексту та hash очікуваного результату. Повні змінені тексти не передаються з Runtime до UI у preview-відповіді.
- Configurator отримав `Ctrl+Shift+F6` і read-only таблицю входжень по всій конфігурації. `Shift+F6` залишається локальною командою з одним `Undo`; workspace-preview не змінює буфер або СУБД.
- Control API отримав `code_editor_rename_workspace_preview` для автономної перевірки того самого Runtime-плану.
- Кореневий `README.md` перероблено як GitHub-опис фактичного продукту: можливості, архітектура, запуск, перевірки, структура репозиторію, зрілість і відомі обмеження.

### Перевірено
- Профільний gate semantic rename, Runtime modules, gateway, Qt editor/dialog і Control API: `97 passed`.
- Повний regression gate: `786 passed`; `python -m src.scripts.selfcheck` пройдено повністю.
- Перевірено український і сумісний синтаксис, export guard, виключення рядків/коментарів/member chains, module owner labels, source hashes і `Ctrl+Shift+F6`.
- На live-базі план для експортної функції `ОткрытиеФормПриНачалеРаботыСистемыВызовСервера.ФормаНачальнойНастройкиПрограммы()` знайшов рівно два входження: declaration module, рядок `24`, і `МодульПрограми`, рядок `83`. Холодний запит із побудовою source cache виконався за `4.7 с`, теплий — за `178 мс`; `is_dirty=false`.
- Після live-перевірки координату курсора вилучено з RPC-контракту UI -> Runtime: локалізований editor buffer передає ім'я вибраного символу, а канонічну позицію визначає Runtime у власному source-of-truth.

### Інваріант
- Workspace-preview є планом, а не дозволом на запис. Майбутній apply повинен перед транзакцією повторно звірити `source_hash` кожного модуля, повторити конфлікт-аналіз і або зберегти всі модулі, або не зберегти жодного.
- UI не отримує повні тексти всіх модулів для глобального рефакторингу. Hydration, token validation і побудова плану залишаються у Runtime.
- Координата з editor buffer не є стабільним ідентифікатором символу для Runtime: нормалізація локалі може змінити зсуви. Через RPC передається ім'я символу, а позицію у канонічному тексті обчислює Runtime.

## 2026-07-27 — Атомарне застосування workspace-перейменування

### Що зроблено
- Runtime RPC отримав `modules.rename_symbol_apply`. UI передає лише GUID модулів та `source_hash/updated_hash` із підтвердженого preview; змінені тексти через RPC не приймаються.
- Перед записом Runtime повторно будує семантичний план на актуальному source cache, звіряє точний набір модулів і обидва hash кожного результату. Застарілий або змінений preview відхиляється без запису.
- `cfg_modules` перемикаються однією транзакцією. Великі тексти спочатку записуються у нові immutable hash-addressed assets; старі assets не перезаписуються, тому збій до commit не створює частково видимого refactoring.
- Діалог `Ctrl+Shift+F6` отримав явне застосування після перегляду входжень. Configurator блокує операцію, якщо активний або інший відкритий затронутий модуль має незбережений буфер, а після commit перезавантажує всі відкриті затронуті редактори.
- Control API отримав `code_editor_rename_workspace_apply` для автономної перевірки повного циклу. Виправлено звернення workspace-команди до неіснуючих `self.vm/self.title`, через які UI міг завершити preview до виклику Runtime.

### Перевірено
- Профільний gate DAO, Runtime handler, gateway, service, Configurator Control API, Qt-діалогу й редактора: `100 passed`.
- Перевірено успішний all-or-nothing commit, stale preview без змін, immutable asset storage, відсутність передачі повного тексту через RPC, UI apply та reload збереженого модуля.
- Повний regression gate: `794 passed`; `python -m src.scripts.selfcheck` пройдено повністю.
- Після restart Runtime і Configurator live-preview функції `ОткрытиеФормПриНачалеРаботыСистемыВызовСервера.ФормаНачальнойНастройкиПрограммы()` через обидва API знову знайшов `2` модулі й `2` входження. Навмисно пошкоджений preview hash відхилено як stale, а вихідний модуль залишився без змін.

### Інваріант
- Workspace apply ніколи не довіряє зміненому тексту від UI: канонічний результат повторно обчислює Runtime.
- Будь-яка невідповідність набору модулів, початкового hash або result hash скасовує всю операцію до видимого commit.
- Незбережені редакторські буфери затронутих модулів не можна мовчки перезаписувати або перезавантажувати.

## 2026-07-27 — Runtime completion експортного API загальних модулів

### Що зроблено
- Runtime RPC отримав `modules.completion_members`. За технічним ім'ям, title або `metadata_ref` загального модуля він повертає лише експортні процедури й функції: ім'я, тип, параметри та рядок декларації.
- Вихідний текст модуля не передається у completion-відповіді. Розбір виконує Runtime, а компактний результат кешується за live-БД та інвалідовується після збереження, нормалізації модулів або атомарного workspace rename.
- Completion context підтримує довільні namespace members поряд із `Метадані / Metadata`. Після `Ім'яЗагальногоМодуля.` редактор ліниво запитує Runtime один раз і повторно використовує результат у поточному editor session.
- Однаковий provider підключено до звичайного редактора модуля та модуля форми. Локальні символи й незбережений буфер залишаються editor-side, а збережений API інших модулів належить Runtime.
- Configurator Control API отримав `code_editor_completion`, тому фактичний список completion можна перевіряти без ручної взаємодії з popup. Якщо активного редактора немає, endpoint використовує явно переданий source та незалежний Runtime-backed semantic context.

### Перевірено
- Профільний gate DSL completion, Runtime handler/gateway, редактора коду та Control API: `98 passed`.
- Перевірено фільтрацію неекспортних методів, сигнатури параметрів, відсутність source text у RPC-відповіді, одноразове lazy-завантаження namespace та повторне використання editor cache.
- Live smoke на `F:\TestBD\MetaDB\metabase.mpdb`: модуль `ОткрытиеФормПриНачалеРаботыСистемыВызовСервера` знайдено, Runtime повернув 2 експортних методи без source text, `ФормаНачальнойНастройкиПрограммы` присутня у Runtime RPC та автономному `code_editor_completion`; повторний запит зайняв близько `1.4 ms`.
- Повний regression gate: `800 passed`.
- `python -m src.scripts.selfcheck`: усі перевірки `[OK]`.

### Інваріант
- UI не повинен завантажувати текст чужого модуля заради completion. Канонічний список експортного API формує Runtime.
- Completion чужого namespace показує лише члени, доступні зовнішньому виклику; приватні процедури й функції не можуть потрапляти до списку.
- Runtime cache є прискорювачем: будь-яка зміна module source повинна інвалідовувати completion разом з resolution/source cache.
- Фоновий Control API не повинен залежати від випадкового active MDI window, якщо запит містить достатній явний контекст.

## 2026-07-27 — Workspace Semantic Index v1

### Що зроблено
- Додано Qt-незалежний `src/dsl/workspace_symbols.py`: індекс зберігає identity модулів, експортні процедури/функції, координати декларацій та статично розв'язані кваліфіковані references.
- Declaration pass працює без compiler/parser кожного модуля: lexer витягує callable API, параметри, export, line/column. Reference pass спочатку виконує дешевий prefilter і лексить лише джерела з потенційно розв'язуваним `ЗагальнийМодуль.Метод`.
- Коментарі та строкові літерали не потрапляють до references. Неоднозначні alias різних модулів позначаються ambiguous і не розв'язуються за принципом «перший переміг».
- Runtime отримав `modules.semantic_index_info`, `modules.semantic_definition` та `modules.semantic_references`. Gateway, application service і Configurator Control API мають відповідні typed entry points.
- `F12` для зовнішнього API використовує точковий Runtime lookup і більше не завантажує source чужого модуля через ViewModel. `Shift+F12` та usages UI використовують semantic references для кваліфікованих символів; звичайний текстовий пошук збережено для довільних термінів і локальних символів.
- Module source cache порівнює `module_guid + sha256 + version + storage revision`: зміна бізнес-даних у тому ж `mpdb` більше не змушує повторно гідратувати всі тексти модулів.
- Повний індекс будується фоновою daemon-задачею після `db.open`. Warmup очікує актуальний manifest cache, не блокує відповідь відкриття БД та захищений від паралельного дублювання для одного `db_uid`.
- Індекс має monotonic generation у межах Runtime process та інвалідовується після module save, normalize і атомарного workspace rename.

### Перевірено
- Профільний gate Workspace Index, Runtime DB/modules handlers, gateway, definition/usages, Configurator actions і Control API: `113 passed`.
- На live-базі індекс розпізнав 4491 модуль, понад 11 тисяч callable symbols і понад 48 тисяч статичних references; definition `ОткрытиеФормПриНачалеРаботыСистемыВызовСервера.ФормаНачальнойНастройкиПрограммы` повернув module GUID та рядок 24, usages повернув декларацію і виклик.
- Початковий синхронний прототип показав неприйнятні 45-60 секунд cold build через гідратацію 4491 source assets. Тому blocking build вилучено зі шляху F12, а повний прогрів перенесено до Runtime background lifecycle.
- Фінальний startup smoke: Control API Configurator доступний приблизно за `7.3 s`; початковий status повернув `ready=false, building=true` за `68.7 ms`; F12-target під час warmup знайдено за `311.7 ms`; generation 1 опубліковано у фоні приблизно через `43.7 s`; status polling не блокувався builder mutex.
- Повний regression gate: `808 passed`.
- `python -m src.scripts.selfcheck`: усі перевірки `[OK]`.

### Інваріант
- Persisted source та Manifest залишаються джерелом істини; semantic index є Runtime cache і не записується до `cfg_modules`.
- Несохранений editor buffer накладає локальну introspection поверх persisted workspace index, але не змінює Runtime index до Save.
- Definition не повинен чекати повної індексації workspace.
- Dynamic/reflection-виклики не вважаються безпечними статичними references і не можуть автоматично брати участь у rename.

## 2026-07-30 — Semantic identity, diagnostics та index-backed workspace rename

### Що зроблено
- Експортні процедури й функції отримали детермінований `symbol_id`, сформований з GUID модуля, виду символу та канонічного імені. Declaration, definition і кожне статично розв'язане reference повертають один identity.
- Workspace index зберігає diagnostics для `unresolved_member`, `ambiguous_qualifier`, `lexer_partial` та `lexer_failed`. Невідомі qualifier звичайних об'єктів не вважаються помилкою; перевірка обмежена alias загальних модулів.
- Runtime отримав `modules.semantic_diagnostics`; Gateway, application service та Configurator Control API підтримують фільтри за module GUID, кодом і лімітом.
- Workspace rename використовує module candidates зі статичних references цільового `symbol_id`. Якщо актуальний індекс ще не готовий, збережено безпечний текстовий prefilter.
- Semantic candidate set не замінює перевірки: planner повторно лексить кожний кандидат, виключає коментарі/рядки, а apply повторно будує plan і звіряє `source_hash`/`updated_hash` перед атомарним commit.

### Інваріант
- `symbol_id` є identity persisted-версії символу в поточному індексі; rename створює новий identity після успішного збереження та інвалідації generation.
- Diagnostics та semantic candidates є похідним Runtime cache. Manifest і persisted module source залишаються джерелом істини.
- Наявність semantic index не дозволяє пропускати token verification або optimistic hash validation під час workspace rename.

### Перевірено
- Профільний gate Workspace Index, Runtime modules handler, Gateway і Configurator Control API: `73 passed`.
- Повний regression gate: `810 passed`; `python -m src.scripts.selfcheck` та `compileall` завершилися без помилок.
- Live Runtime на окремому порту відкрив `F:\TestBD\MetaDB\metabase.mpdb` і побудував generation 1: `4491` modules, `11059` symbols, `7739` exported symbols, `51307` references.
- Definition і declaration/call references для `ОткрытиеФормПриНачалеРаботыСистемыВызовСервера.ФормаНачальнойНастройкиПрограммы` повернули однаковий `symbol_id`; workspace rename preview знайшов `2` модулі та `2` входження.
- SHA-256 source до та після preview залишився однаковим; apply не виконувався. Configurator Control API повернув live index status і відфільтровані diagnostics для цільового module GUID.

## 2026-07-30 — Workspace Problems panel

### Що зроблено
- У Configurator додано нижній dock `Problems / Проблеми`, який за замовчуванням прихований і не виконує Runtime-запитів на startup path.
- Перше відкриття панелі запускає завантаження semantic diagnostics у `QThread`; UI thread не очікує побудову або оновлення Workspace Semantic Index.
- Loader спочатку опитує стан уже запущеного background warmup і читає diagnostics після публікації generation. Це виключає паралельну cold-побудову того самого індексу з UI.
- Панель показує severity, повідомлення, модуль, рядок і diagnostic code; доступні severity-фільтр, текстовий фільтр, ручне оновлення та зведення errors/warnings.
- Подвійний клік відкриває відповідний module editor через канонічний `_open_module_by_guid` і позиціонує курсор на diagnostic line.
- `F8` і `Shift+F8` циклічно переходять до наступної/попередньої видимої diagnostics з урахуванням активних фільтрів. Якщо панель ще не завантажена, перший перехід ставиться в чергу, очікує background load і відкриває перший результат.
- Навігація використовує власний cursor, а не неявний current index `QTableView`; автоматичне виділення Qt більше не змушує перший `F8` пропускати перший рядок.
- Завантажений набір diagnostics передається всім відкритим code editors і новому editor під час wiring. Редактор фільтрує projection за власним `module://GUID`; додаткових Runtime-запитів для marker layer немає.
- Workspace diagnostics малюються окремим composable layer: wave underline у тексті та вузький severity marker у gutter. Поточний рядок, breakpoint і єдина debug-стрілка залишаються незалежними шарами й не стирають один одного.
- Gutter показує локалізоване diagnostic message у tooltip. Diagnostics без координати рядка залишаються у Problems panel і не створюють хибний marker на першому рядку.
- Після успішного збереження code editor випускає `saved(asset_key)`; відкрита Problems panel автоматично запитує нову generation. Прихована панель не створює фонової роботи.
- Configurator Control API отримав `workspace_problems_state` і `workspace_problems_refresh`, тому стан панелі, background loading і результати можна перевіряти без ручної взаємодії з вікном.
- Control API `workspace_problem_navigate` відтворює next/previous navigation для автономного live smoke.
- Control API `code_editor_diagnostics_state` повертає active asset key, marker lines, загальну кількість diagnostics і debug line без читання source text.
- Додано локалізацію всіх нових UI-елементів і diagnostic messages для `uk` та `en`; Runtime передає стабільний diagnostic code та структуровані параметри, а UI формує локалізований текст.

### Перевірено
- Профільний gate панелі, Configurator window/control API, code editor, Workspace Index, Runtime modules handler і локалізації: `96 passed`.
- Повний regression gate після додавання keyboard navigation і editor markers: `820 passed`; `python -m src.scripts.selfcheck` та `compileall` завершилися без помилок.
- Live Runtime/Configurator на ізольованих портах `8875/8876` показав generation `1` з `4077` diagnostics: `2792` errors і `1285` warnings.
- Control API підтвердив неблокуюче завантаження, а window screenshot підтвердив українські заголовки, severity та параметризовані повідомлення без англомовного Runtime-тексту.
- Live navigation відкрила закритий `SessionModule` на першій diagnostic і підтвердила циклічний cursor `0 -> 1 -> 0` для next/previous.
- Live marker smoke для `SessionModule` підтвердив `13` diagnostics на реальних рядках (`228`, `275`, ..., `3408`) і одночасну debug-позицію на рядку `228`; marker layer зберігся після відкриття debug location.

### Інваріант
- Problems panel є projection semantic diagnostics, а не окремим джерелом істини.
- Повільна перебудова індексу ніколи не виконується у Qt main thread.
- Configurator не повинен запускати дублюючу cold-побудову, поки Runtime вже прогріває той самий Workspace Semantic Index.
- Навігація з diagnostics використовує module GUID, а title є лише display value.
- Перший next/previous після відкриття або зміни фільтра повинен починатися з першого/останнього видимого рядка, незалежно від selection state таблиці.
- Diagnostic, current-line, breakpoint і debugger selections повинні формуватися одним compositor і не можуть викликати `setExtraSelections()` незалежно один від одного.
- Editor marker projection ніколи не запускає власну workspace index build: джерелом є generation, уже отримана Problems panel.

## 2026-07-30 — Зменшення semantic diagnostics noise

### Що зроблено
- Declaration pass загальних модулів більше не залежить тільки від повної успішності lexer. Додано tolerant source scanner для anchored declarations `Procedure/Function`, `Процедура/Функция/Функція`, багаторядкових сигнатур, параметрів і `Export/Экспорт/Експорт`.
- Scanner відновлює callable API після пошкоджених legacy/import fragments у тілі модуля. Реальний приклад: `d/*A\x02PqWB\x02text` відкривав незавершений коментар, через що lexer втрачав приблизно 770 наступних рядків.
- Token declarations і recovered declarations зливаються за `kind + canonical name`; token coordinates зберігаються, а recovered export може виправити неповну token declaration.
- Semantic index містить лише callable symbols, тому qualified reference і `unresolved_member` тепер створюються тільки для синтаксису виклику `Qualifier.Member(...)`. Доступ `Qualifier.Property` не порівнюється зі списком експортних процедур/функцій.
- Глобальний suppress-list не додано. Нерозв'язані виклики залишаються видимими; collision між common-module alias та локальним/metadata object буде вирішуватися окремим context-aware shadowing pass.

### Перевірено
- Tolerant scanner відновив багаторядкову exported function після незавершеного `/*` fragment і коректно витягнув параметри.
- Live API `ОбновлениеИнформационнойБазы` зріс з `1` до `12` exported members, `ОбщегоНазначенияУТКлиент` — з `1` до `21`.
- Перший live rebuild зменшив `unresolved_member` з `2792` до `1085`; callable-only resolution зменшив їх до `504`.
- Загальна Problems projection змінилася з `4077` (`2792` errors, `1285` warnings) до `1789` (`504` errors, `1285` warnings). Зменшення errors: `2288`, приблизно `82%`.
- Повний regression gate: `821 passed`; `python -m src.scripts.selfcheck` та `compileall` завершилися без помилок.

### Інваріант
- Tolerant declaration recovery використовується тільки для workspace symbol API та не перетворює пошкоджений module source на виконуваний код.
- Property access не може бути reference на callable symbol без `LPAREN`.
- Diagnostics не можна приховувати списком імен конфігурації; suppression допускається лише з доведеного lexical/metadata context.

## 2026-07-30 — Scope-aware semantic diagnostics та live editor markers

### Що зроблено
- Workspace index тепер індексує процедури й функції всіх видів модулів, а не лише загальних. Для кожного модуля доступний локальний callable API, включно з неекспортними процедурами форми, об'єкта, сеансу та застосунку.
- Додано diagnostics `unresolved_callable`, `unresolved_module` і `unresolved_requisite` з координатами та кандидатами виправлення. Перевірка враховує параметри, локальні та модульні змінні, assignment targets і змінні циклів, тому shadowed alias загального модуля не аналізується як namespace.
- Канонічний `platform_symbols` використовується semantic index та editor introspection. Стандартні функції платформи на кшталт `РольДоступна`, `ЗаполнитьЗначенияСвойств` і `ПолучитьИзВременногоХранилища` не вважаються відсутніми локальними процедурами.
- Строга перевірка `Об'єкт/Объект/Object.<реквізит>` виконується тільки для повної owner schema. Форма проходить через `owner_guid` до бізнес-об'єкта; неповна або зовнішня schema не породжує хибну помилку.
- Невідомий qualifier та нерозв'язаний член загального модуля мають рівень warning до появи повної типізації виразів. Синтаксична помилка, доведена відсутня локальна callable та відсутній реквізит при повній schema мають рівень error.
- Code editor виконує parser diagnostics реактивно через debounce після зміни несохраненого тексту. Локальні parser diagnostics і Runtime workspace diagnostics зливаються в один marker layer: хвилясте підкреслення, severity marker у gutter та tooltip.
- Повний workspace scan більше не лексить тисячі source-файлів. Маскування коментарів/рядків і source scanner зберігають координати, а строгий parser викликається лише для невеликої кількості потенційних проблем.
- Runtime semantic cache враховує manifest/schema identity та використовує single-flight build: паралельні warmup, Problems panel і RPC-запит очікують одну побудову замість запуску дубльованих індексів.

### Перевірено
- Профільний gate редактора, Workspace Index, Problems panel і Runtime handlers: `62 passed`.
- Повний regression gate: `831 passed`; `python -m src.scripts.selfcheck` та `compileall` завершилися без помилок.
- Live Runtime на `F:\TestBD\MetaDB\metabase.mpdb`: `4491` модуль, `57591` callable symbols, `52978` references.
- Cold semantic build зайняв приблизно `25.7 s`, повторна видача diagnostics — приблизно `0.07 s`.
- Після доповнення platform catalog live projection не містить хибних errors стандартних функцій. Залишилося `65` warning (`58 unresolved_member`, `7 unresolved_module`), для яких потрібна майбутня типізація виразів; `unresolved_callable` для стандартного API — `0`.
- Live Configurator Control API відкрив модуль з Problems panel і після внесення синтаксичної помилки у несохранений буфер повернув одночасні marker lines `2` (локальний parser) та `88` (Runtime workspace warning).

### Інваріант
- Несохранений editor buffer перевіряється локальним parser і не змінює persisted Workspace Semantic Index до Save.
- Оновлення Runtime diagnostics не може стерти parser markers, а локальний reparse не може стерти workspace markers.
- Неповна schema не дає права позначати реквізит відсутнім.
- Метод довільного об'єкта або form attribute не можна позначати error лише через схожість qualifier з alias загального модуля; для цього потрібен доведений static type.
- Повний semantic build не повинен виконувати масову hydration зовнішніх schema payloads або блокувати Qt main thread.

## 2026-07-30 — Alias-aware callable resolution та form shadow filtering

### Що зроблено
- UK/EN normalization profiles тепер надають спільний транзитивний alias graph для callable identifiers. Workspace Index і Runtime module dispatch однаково розв'язують імпортовані варіанти на кшталт `Очистить/Очистити`, не змінюючи persisted source.
- Qualified-call scanner аналізує тільки кореневу пару `Qualifier.Member`. Внутрішні сегменти ланцюга `RecordSet.Filter.Users.Set()` більше не сприймаються як окремі module namespaces.
- Для form modules додано точкову hydration тільки owner payloads, що беруть участь у нерозв'язаних diagnostics. Slim manifest не вважається повною моделлю лише через наявність загального `metadata_ref`: адаптер читає raw `form_model_ref` і гідратує конкретний asset.
- Імена, bindings та table columns із `form_model` формують доведений form-member context. Collision form attribute з common-module alias видаляється тільки для власника конкретної форми.
- Статистика індексу повертає `form_shadow_diagnostics_filtered`, тому suppression є спостережуваним, а не прихованим.
- Якщо exported member відсутній у вказаному модулі, diagnostics додає точні повні імена збігів у інших модулях. Це дозволяє відрізнити відсутню функцію від виклику через неправильний namespace.
- API projection diagnostics відновлює читабельні CP1251-mojibake identifiers для qualifier, member і candidates так само, як code editor. Persisted source та symbol identity при цьому не змінюються.

### Перевірено
- Фінальний профільний gate Workspace Index, Problems panel, Runtime handlers і module dispatch: `38 passed`.
- Повний regression gate: `840 passed`; `python -m src.scripts.selfcheck` та `compileall` завершилися без помилок.
- Live generation 1 на `F:\TestBD\MetaDB\metabase.mpdb`: `4491` modules, `57591` symbols, `52983` references.
- Projection зменшено з `65` до `44` warning; `unresolved_module`, `unresolved_callable` і `unresolved_requisite` дорівнюють нулю.
- Три хибні виклики через form attribute `Пользователи` видалені; live stats повернув `form_shadow_diagnostics_filtered=3`.
- Для реальних namespace mismatch live diagnostics повертає точні declaration candidates, зокрема реалізації викликів у `ЗакупкиСервер`, `ДенежныеСредстваСервер` та `ПрефиксацияОбъектовКлиентСервер`.

### Інваріант
- Alias resolution не переписує source text і не змінює identity declaration.
- Form shadow suppression допускається тільки після успішної hydration конкретної form model.
- Пошук declaration в іншому модулі є підказкою виправлення, а не автоматичним перенаправленням Runtime-виклику.

## 2026-08-02 — Повнота BSL-модулів прямого джерела `.1CD`

### Що зроблено
- Публікація `Module.bsl` із `OneCDConfigSource` проходить через єдиний parser-validating gate. Незбалансований або невідновлюваний fragment не потрапляє до імпорту як виконуваний модуль.
- Вилучення table-file source оцінює всі незалежні текстові потоки та варіант із видаленими binary marker lines. Marker може відокремлювати пошкоджений preview від повної копії або розривати один повний модуль на дві послідовні частини.
- Рядок `",` більше не вважається кінцем звичайного BSL-модуля: це легальний елемент багаторядкового тексту запиту. Обрізання quoted serialization tail застосовується тільки до відомого serialized form container.
- `#КонецОбласти/#EndRegion` не вважається безумовним кінцем модуля. Процедури та функції після області зберігаються; евристичне очищення дозволене лише для хвоста без нових declarations.
- Контрольні символи та службові table-file tails видаляються до збереження source. Для прямої `.1CD` додано відтворюваний corpus gate через `python -m src.scripts.audit_dsl_corpus <path.1CD>`.

### Перевірено
- Повний прямий corpus: `4336/4336` модулів успішно parse та compile, `0` failures. До виправлення gate бачив `4326` модулів, тобто відновлено ще `10` раніше відкинутих source assets.
- `ОтборыСписковКлиентСервер` відновлено з `7` до `23` унікальних declarations; `ОбработкаТабличнойЧастиСервер` — з `38` до `44`.
- Workspace projection прямої `.1CD`: `4336` modules, `57370` symbols, `56101` references. Загальна кількість semantic diagnostics зменшилася з `280` до `79`, `unresolved_member` — з `259` до `58`.
- Фінальний профільний gate direct source/import/audit: `91 passed`; повний regression gate проєкту: `858 passed`.
- Штатний Runtime import виконав `backup -> staging -> validate -> swap`: створено `metabase.backup-20260802-055912-564.mpdb`, імпортовано `16396` assets, збагачено `2487` об'єктів реквізитами/табличними частинами та `11819` структурних об'єктів.
- Live manifest після swap містить `19678` objects. Runtime semantic index готовий: `4491` modules, `57591` symbols, `0` unresolved modules і `0` unresolved callables.
- Live completion API підтвердив відновлені `ОтборыСписковКлиентСервер.НеобходимОтборПоСостояниюПриСозданииНаСервере` та `ОбработкаТабличнойЧастиСервер.ПолучитьСтруктуруДополнительнойИнформации`.

### Інваріант
- Синтаксично збалансований короткий preview не може перемагати повний parser-valid stream з більшою кількістю унікальних declarations.
- Евристика container serialization не може застосовуватися до звичайного common/object/manager module.
- Код після region closure є частиною модуля, доки parser або доведений table-file boundary не показує протилежне.
- Green unit test не є доказом повноти `.1CD`: обов'язкові direct corpus audit та workspace semantic delta на реальному файлі.

## 2026-08-02 — Offline import integrity gate та локалізація назв модулів

### Що зроблено
- Safe import завжди виконує повну перевірку referenced pages у staging, закриває staging handle і повторно сканує фізичні page slots через read-only `mpdb.doctor` до swap.
- `DbPool.replace_with_file` має незалежний offline integrity gate до закриття live handle. Пошкоджений replacement не може замінити live-базу навіть при помилці або пропуску перевірки в import handler.
- Відновлено live page `23675`, у якої був затертий перший байт magic. Перед ремонтом збережено окремий corrupt snapshot; після точкової заміни байта повний doctor перевірив усі `24606` сторінок без помилок.
- Додано єдину UI-проєкцію назв канонічних модулів. `ObjectModule`, `FormModule`, `CommandModule`, стартові та інші системні види показуються українською або англійською відповідно до поточної мови UI, але їх persisted identity, GUID та executable references не змінюються.
- Проєкцію підключено до дерева конфігурації, контекстного меню, редактора коду, браузера модулів і панелі Problems.

### Перевірено
- Offline doctor до ремонту: одна пошкоджена сторінка `23675`; backup `metabase.backup-20260802-055912-564.mpdb` повністю справний.
- Offline doctor після ремонту: `24606/24606` сторінок справні, `pages_bad=0`.
- Live Runtime на `8875` читає повний manifest без rowid recovery: `19705` objects. Раніше fallback повертав `19678` rows і втрачав `27` rows із пошкодженої сторінки.
- На live manifest українська UI-проєкція локалізує `713` канонічних module titles із `2891` module nodes.

### Інваріант
- Перевірка staging через його активний cache не є достатньою: перед swap обов'язковий offline scan після закриття handle.
- `DbPool` не закриває live DB і не виконує `os.replace`, доки replacement не пройшов незалежну фізичну перевірку.
- Локалізація назви модуля є лише presentation-layer операцією; runtime lookup та persisted identifiers завжди використовують внутрішні значення.

## 2026-08-02 — Стабільна повторна `.1CD`-загрузка та атомарна активація БД

### Що зроблено
- `mpdb.Transaction` утримує reentrant lock бази від `BEGIN` до `COMMIT/ABORT`. Виділення page id, зміна `_meta`, запис data/index pages і публікація нового META більше не можуть перемішуватися між паралельними транзакціями.
- Перед записом META commit перевіряє кожну нову сторінку. Сторінка має бути присутня в transaction page map або вже містити фізично валідний page slot із очікуваним id; нульова чи незаписана сторінка зупиняє commit.
- Після `os.replace` Runtime повторно запускає physical doctor вже для активованого live-файлу. Лише після успішної перевірки handle публікується у `DbPool`; будь-який збій запускає наявний rollback із backup.
- Після імпорту синхронізація membership підсистем відправляє один `manifest.bulk_update_payloads` замість сотень послідовних `manifest.update_payload`. Qt main thread більше не виглядає завислим після фактичного завершення імпорту.
- Пошкоджений результат повторної загрузки збережено як `F:\TestBD\MetaDB\metabase.corrupt-repeat-20260802-174213-706.mpdb`, а live DB відновлено з перевіреного backup.

### Перевірено
- Конкурентний storage smoke: `6` потоків, `720` транзакцій, `0` помилок; physical doctor перевірив усі сторінки тестової бази.
- Активна `F:\TestBD\MetaDB\metabase.mpdb`: `24606/24606` сторінок справні, `pages_bad=0`, WAL порожній.
- Live Runtime на `8875` відкриває БД та повертає повний manifest із `19705` об'єктів без rowid recovery.
- Профільний gate: `45 passed`; повний regression gate: `868 passed`; `compileall` і `python -m src.scripts.selfcheck` завершилися без помилок.

### Інваріант
- Виділення сторінок і commit metadata однієї транзакції не можуть бути видимі іншій транзакції до завершення commit.
- Успішний doctor replacement-файлу до swap не скасовує обов'язкову перевірку фактично активованого live-файлу після WAL recovery.
- Post-import repair не повинен виконувати O(N) синхронних RPC із GUI thread, якщо Runtime підтримує bulk mutation.

## 2026-08-12 — GUID-ідентичність `.1CD` та локалізовані посилання модулів

### Що зроблено
- Пряме джерело `.1CD` читає індекс метаданих із `Params/*.si`. Записи `child GUID -> parent GUID -> kind -> internal name` використовуються для відновлення форм, команд та інших дочірніх об'єктів, навіть якщо евристичний аналіз `Config` не знаходить власника.
- UUID із XML/Config зберігається як GUID manifest-об'єкта. Повторний імпорт оновлює об'єкт і його assets за GUID, а не створює новий рядок за локалізованою назвою.
- Модуль має одну фізичну identity (`module_guid`), стабільне `source_ref` і `canonical_ref`, а також незалежні executable aliases `ref_uk` та `ref_en`.
- Кириличне значення, помилково підставлене експортом як English synonym, більше не вважається англійським alias. Англійська назва будується з української через детермінований словник і transliteration fallback.
- Посилання вкладеного модуля містить повний шлях власника: тип метаданих, кореневий об'єкт, форму або команду та вид модуля. Однакові назви `ФормаСписка` у різних документах більше не створюють однаковий executable reference.
- Панель властивостей common module показує code name активної локалі, а не внутрішній ASCII/transliteration identifier.
- Safe repeat import бере стабільний pool/session UID. Внутрішній `db_uid` staging-файлу може відрізнятися після swap і не використовується для пошуку live path.

### Перевірено
- XML-еталон містить `4552` BSL-файли. Пряме `.1CD` джерело відновлює всі `4270` непорожніх виконуваних модулів; чотири відсутні XML-файли є BOM/whitespace placeholders без коду.
- Цільова identity `CommonModule.СтандартныеПодсистемыПовтИсп.Module` має українське посилання `ЗагальнийМодуль.СтандартніПідсистемиПовтВик.Модуль` та англійське `CommonModule.StandardSubsystemsReuse.Module`.
- Повторний live import через Runtime завершився штатним `backup -> staging -> validate -> swap`: `19455` manifest rows, `24878` перевірених physical pages, backup `metabase.backup-20260812-040420-809.mpdb`.
- Live `cfg_modules` містить `4548` унікальних source paths. Порівняння з XML: `missing_nonempty=0`, `extra=0`; усі `4270` непорожніх модулів присутні, пропущено лише чотири порожні placeholders.
- Обидва короткі й повні aliases `СтандартніПідсистемиПовтВик` / `StandardSubsystemsReuse` та `ЗагальнийМодуль.СтандартніПідсистемиПовтВик.Модуль` / `CommonModule.StandardSubsystemsReuse.Module` розв'язуються в `fb0c3c90-7171-54db-9cd4-472aab5db2c6`.
- Після міграції live aliases кількість колізій `canonical_ref`, `ref_uk`, `ref_en` дорівнює нулю; UI-проєкція повертає українське та англійське code name відповідно до локалі.
- Профільний regression gate для `.1CD`, manifest, локалізації, module resolver та Runtime pool: `146 passed`; `compileall` і `python -m src.scripts.selfcheck` завершилися без помилок.

### Інваріант
- Локалізована назва не є storage identity: перемикання UK/EN не змінює GUID, source text або зв'язок із manifest.
- Дочірній об'єкт не може визначатися лише за назвою: авторитетними є GUID та parent GUID із фізичного індексу.
- Усі непорожні виконувані модулі XML-еталона мають бути присутні у прямій `.1CD` проєкції; порожній placeholder не створює фальшивий executable module.
- Повторний `backup -> staging -> validate -> swap` зберігає UID запису `DbPool`, навіть якщо активований файл має інший внутрішній `db_uid`.

## 2026-08-16 — Source Name як identity common modules

### Що зроблено
- Для common modules поле `manifest.name` і технічна назва в Configurator беруться з `Properties/Name` (`Source Name`), а `title` залишається користувацьким синонімом.
- `ref_uk` та `ref_en` будуються з технічного імені, а не з повторюваного синоніма. Англійська гілка використовує детермінований переклад/транслітерацію CamelCase-компонентів.
- Старі адреси збережені в `legacy_code_refs` і використовуються як compatibility aliases, але не визначають нову identity.
- Resolver більше не вибирає перший модуль за неоднозначним синонімом: для повторюваних назв потрібен `Source Name` або локалізоване code reference.
- Автодоповнення та навігація до визначення враховують `source_name`, локалізовані code refs і legacy aliases.

### Перевірено
- Live Runtime `8875`: `601` common modules, `601` мають `Source Name`, `0` identity violations, `0` payload/code-ref mismatches.
- Live `cfg_modules`: `4548` module rows, дублікати `ref_uk` та `ref_en` — `0`.
- Українське та англійське посилання одного common module успішно розв'язуються в один `module_guid`.
- Профільні тести: `50 passed`.

### Інваріант
- `Source Name` є стабільною технічною identity; `Синоним` ніколи не використовується як єдиний executable address.

## 2026-08-16 — IDE language-service baseline

### Що зроблено
- Completion редактора використовує поточний semantic snapshot документа: процедури, функції, параметри та локальні змінні доступні до збереження модуля.
- Додано навігацію по процедурах і функціях через список символів у панелі редактора.
- Додано `Ctrl+G` для переходу до рядка, автозакриття `()`, `[]`, `{}` та блокову автоіндентацію для UK/EN конструкцій.
- Збережені існуючі runtime/workspace completion, діагностика, definition/usages/rename і debugger shortcuts.

### Перевірено
- `148 passed` для DSL completion, introspection, workspace symbols, code editor, debugger pause, control API та OneC import regression tests.
- `python -m compileall -q src` завершився без помилок.

### Інваріант
- Підказки та навігація працюють з незбереженим текстом редактора; відсутність доступу до Runtime не повинна ламати локальне парсування або введення коду.

## 2026-08-16 — первопричины проблем импорта и semantic diagnostics

### Что исправлено
- Встроенные API 1С (`ЗаписьЖурналаРегистрации`, `ПоказатьОповещениеПользователя`, `ОткрытьЗначение` и другие) добавлены в каталог глобальных символов DSL. Они больше не ошибочно считаются отсутствующими локальными процедурами.
- Для фасадных имен common modules добавлено строгое compatibility-разрешение: ссылка переходит в другой модуль только при единственном точном экспортированном совпадении. Неоднозначные и действительно отсутствующие API остаются предупреждениями.
- Устранена гонка в `AdaptiveCompressor`: общий `ZstdDecompressor` заменен новым контекстом на каждое распаковывание страницы. При параллельной индексации Runtime больше не получает ложные ошибки повреждения страниц.

### Проверено
- До исправления live semantic index показывал `19` ошибок и `58` предупреждений; после добавления platform API — `0` ошибок и `57` диагностик; после compatibility-разрешения — `0` ошибок и `38` диагностик (`36` unresolved member, `2` unresolved module).
- Оставшиеся 38 диагностик подтверждены как отсутствующие или несовместимые экспортированные API первоисточника, а не потерянные страницы mpdb. Они не скрываются автоматически.
- Полная проверка многопоточного чтения ZSTD-страниц и профильные тесты прошли; `35 passed` для workspace symbols, mpdb pages/data slots и Runtime DB pool.
- `mpdb_doctor` для `F:\TestBD\MetaDB\metabase.mpdb`: `OK`, `26587/26587` страниц, `0` поврежденных страниц.

### Инвариант
- Диагностический анализ не маскирует неизвестные ссылки: compatibility alias допускается только для явных фасадных имен 1С и уникального экспортированного назначения.
- Доступ к странице mpdb должен быть безопасен при параллельных Runtime readers; компрессор не хранит разделяемое состояние декомпрессии.

## 2026-09-13 - Технічні імена, ієрархія підсистем і конструктор проведення

### Що зроблено
- Редактор об'єкта використовує лише бічну навігацію по сторінках. Програмний перехід також виконує lazy initialization і синхронізує кнопки переходу.
- Configurator показує технічне `source_name`, а не `title`/синонім, у дереві, заголовках редакторів, властивостях та списках вибору об'єктів. Для slim snapshot без `source_name` використовується ім'я з `metadata_ref`; фізичний ASCII alias більше не підміняє відоме ім'я джерела. Це уточнює попередню presentation-поведінку common modules: технічне ім'я та локалізовані code refs є окремими значеннями. GUID, executable aliases і клієнтські синоніми не змінюються від відображення.
- Спільний компонент підсистем для довідників і документів будує дерево за `parent_guid`, не за перекладеним шляхом. Однакові підписи, відсутні батьки та цикли не спричиняють втрату вибору або рекурсивне зависання. Незбережений вибір зберігається після перебудови.
- На сторінці рухів верхнє дерево є єдиним джерелом вибору регістрів; нижня таблиця показує вибрані регістри та дозволяє видалити їх із вибору. Пошуковий фільтр не змінює membership. Збережені canonical refs зіставляються з технічними іменами без дублювання.
- Конструктор генерує UK/EN заготовку процедури з прапорцями запису вибраних регістрів. Перевіряються ідентифікатори, неоднозначні назви та відповідність заготовки поточному вибору. Перегенерація зміненого вручну тексту потребує підтвердження.
- Вставка знаходить саме `ObjectModule` за manifest/module metadata через Runtime, а не перший модуль власника. Використовується поточний буфер редактора, включно з незбереженими змінами; вставка скасовується одним Undo і не виконує автоматичного Save.
- Наявний UK/EN або імпортований обробник проведення не перезаписується: редактор переходить до нього. Неоднозначний модуль, пошкоджені лексеми, незавершені процедури та некоректна заготовка блокують вставку. Строгий режим Lexer застосовується явно; звичайне толерантне редагування не змінене.
- Додано read-only інструмент `src/scripts/check_posting_editor.py`: він читає metadata через Runtime, перевіряє відновлений вибір та ObjectModule і зберігає offscreen-зображення редактора без запису в live DB.

### Перевірено
- Профільний набір Configurator, редакторів, DSL і проведення: `362 passed`. `compileall` для змінених підсистем завершився успішно. Повний набір усіх тестів проєкту в цьому проході не запускався.
- Через активний Runtime для `Document.РеализацияТоваровУслуг`: `37` збережених регістрів, `37` вибраних і `37` рядків нижньої таблиці; вибір збережено без дублікатів.
- Реальний ObjectModule містить `102771` символ; наявний обробник знайдено на рядку `943`. Модуль і бізнес-дані під час перевірки не змінювалися.
- Offscreen-рендер перевірено в `.artifacts/configurator-movements.png`: бічна навігація, технічний заголовок, обидва списки рухів і підсвічена UK-заготовка.
- Тести редактора покривають незбережений буфер, вставку, Undo/Redo, стандартне збереження через тестовий VM і повторне читання; це не є перевіркою виконання проведення на live даних.

### Інваріанти та межі
- Runtime залишається єдиним власником live DB; жодного прямого доступу UI до `mpdb` не додано.
- `Ім'я`/`Source Name` не визначається з синоніма. Зміна способу показу не повинна перезаписувати користувацький `title` або persisted identity.
- Ієрархія підсистем визначається GUID-зв'язками, а не локалізованими підписами чи роздільниками у назвах.
- Згенерований текст є заготовкою, не готовими бізнес-правилами. Заповнення полів і створення записів рухів потребують явного алгоритму; генератор не вигадує фінансових даних.
- Поточний runtime використовує hooks `BeforePost`/`AfterPost`; автоматичний виклик ObjectModule `ОбробкаПроведення`/`Posting` і конструктор зіставлення полів ще не реалізовані. Наявність заготовки або її збереження не означають, що runtime виконує її під час проведення.

## 2026-09-14 - Атомарне виконання ObjectModule під час проведення

### Що зроблено
- Додано RPC `document.post` і `document.unpost`. Client викликає їх через `GatewayDb`/`RuntimeGateway`; локальний запуск PostingEngine поверх незалежних RPC до таблиць прибрано. Старий Runtime без цих RPC не отримує небезпечного fallback.
- PostingEngine читає збережений ObjectModule за owner GUID і module kind; ManagerModule, неоднозначні модулі та чернетка `posting_handler` не підміняють його. Inline source та source assets читаються всередині Runtime.
- Обробники UK/EN виконуються на знімку реквізитів і табличних частин конкретного документа та буфері вибраних регістрів. Автоматичне копіювання однойменної табличної частини в регістр прибрано: рухи створює лише явний алгоритм.
- Підтримано базові записи регістрів відомостей і накопичення, прапорець Write, Add/Count, напрямок накопичення, типи полів та Boolean-параметр відмови. Невідомі поля, нерозв'язані виклики, порожня flags-only заготовка та некоректний код не можуть давати успішне проведення.
- Перед/після hooks виконуються до commit із знімком очікуваного стану. Помилки й відмова більше не ігноруються. Відмітка документа та всі записи рухів використовують одну транзакцію `mpdb`; повторне одночасне проведення не дублює записи.
- Додано `Table.update_tx` для оновлення committed rows у зовнішній транзакції зі стабільним rowid. Оновлення після pending-записів у цій самій таблиці явно заборонене, бо locator reads поки не мають загального transaction overlay. Існуючий `Table.update` зберігає свій API.
- Заголовок зберігає `_posting_registers` із GUID фактично записаних регістрів. Скасування враховує цей перелік після зміни вибору в конфігурації; legacy-проведення без переліку потребує окремої перевірки/міграції.
- Client просить зберегти незбережену форму перед проведенням; неатомарного прихованого autosave в цьому шляху більше немає. Невдалий SaveAndClose/PostAndClose не закриває форму; помилка збереження табличної частини більше не маскується успішним результатом.
- Звичайні RPC запису таблиці документа не дозволяють підміняти `_posted`/`_posting_registers`, змінювати GUID або редагувати/видаляти проведений документ без скасування проведення. Перевірка та запис виконуються під блокуванням БД. Після commit проведення/скасування інвалідується кеш native rows для наступних клієнтських читань.
- Додано опис контракту й приклади в `src/docs/RUNTIME_POSTING.md`. Виправлено сторонню залежність логера стилів клієнта від PostingEngine та застаріле очікування semantic-index тесту для вже наявного поля `source_gaps`.

### Перевірено
- Розширений профільний набір Configurator, Client, Runtime, DSL і storage: `535 passed, 1 skipped`. Пропущено тест паралельного ZSTD-читання, оскільки `zstandard` відсутній у поточній `.venv`. JUnit-звіт: `.artifacts/runtime-posting-tests.xml`. `compileall` і `git diff --check` успішні.
- Реальний HTTP round trip через RuntimeHandler і GatewayDb на тимчасовій файловій `mpdb`: збереження, проведення, блокування редагування проведеного документа і скасування. Окремі engine-тести перевіряють UK/EN ObjectModule, запис рухів і повторне проведення.
- Ін'єкція помилки на другому insert повертає заголовок і всі рухи до початкового стану, включно з перевіркою після закриття/відкриття файлу. Перевірено помилку delete під час скасування, відмову before/after hooks, відмову ObjectModule, паралельні запити та ізоляцію табличних рядків за GUID документа.
- Перевірки не запускали проведення на робочій базі користувача; live Runtime і Client не перезапускалися. Це не повний regression suite проєкту й не доказ сумісності всіх імпортованих процедур 1С.

### Інваріанти та межі
- Цей запис уточнює межу від 2026-09-13: базовий виклик ObjectModule тепер реалізований, але візуального конструктора зіставлення полів ще немає.
- Поки не підтримуються повний dispatch загальних модулів, запити, live API довідників, вкладена передача параметрів за посиланням, бухгалтерські/розрахункові регістри та автоматична матеріалізація virtual import data. Ці випадки завершуються помилкою без часткового проведення.
- `VM.call_with_outputs` повертає host-коду кінцеві параметри entry; це не загальна реалізація передачі параметрів за посиланням. Вкладені by-reference виклики блокуються, щоб не загубити зміну відмови в допоміжній процедурі.
- Збереження форми залишається окремою операцією; атомарний SaveAndPost не заявляється. Нульові рухи потребуватимуть окремої явної політики, а не автоматичного дозволу flags-only заготовки.
- Скрипт не отримує DB handle, а VM має обмеження інструкцій, глибини викликів і числа рядків. RPC-відповідь про успіх надсилається після commit. Втрачена мережева відповідь не доводить rollback: перед повторними діями слід перечитати стан документа.

## 2026-09-14 - Зіставлення полів рухів і параметри за посиланням

### Що зроблено
- На сторінці рухів додано діалог явного зіставлення полів: вибір регістру, джерела рядків (реквізити документа або таблична частина), напрямку та сумісних полів. Автоматичного вгадування бізнес-правил немає.
- Конструктор генерує UK/EN код із додаванням записів, присвоєннями й циклом за потреби. План `posting_mappings` має версію та зберігається в metadata разом із заготовкою; підтвердження не записує модуль. Зміна заготовки потребує підтвердження, наявний обробник не перезаписується.
- Обов'язкові, видалені, неоднозначні та несумісні поля перевіряються перед генерацією та вставленням. Джерела визначаються технічними іменами; Runtime зіставляє їх із фізичними полями за manifest, не за синонімами.
- Додано script-to-script параметри за посиланням у DSL: змінні, властивості та індексовані елементи. Вкладені виклики, спільне посилання двох параметрів, рекурсія та output-параметр відмови зберігають зміни. `Val` ізолює переназначення параметра, але не копіює змінюваний об'єкт.
- Debugger бачить значення параметрів, не внутрішні обгортки посилань. Host/Python виклики отримують значення; об'єкт та індекс аргументу обчислюються один раз.
- Виявлено та виправлено неправильний адресний перехід `Try/Except`: компілятор тепер зберігає адресу handler, VM зберігає зовнішній стек ітератора при обробці винятку. Динамічний код використовує поточні зв'язки параметрів без відкладеного copy-out.
- Знято попередню заборону вкладених reference-викликів у PostingVM після тестів скасування та захисту read-only знімка. Значення `forbid`/`not_supported` з UI тепер забороняють проведення в Runtime.

### Перевірка та межі
- Перевірено Qt-діалог, відновлення заготовки, блокування застарілого зіставлення, UK/EN генерацію, фізичні aliases полів і вибір рядків конкретного документа.
- На тимчасовій файловій БД пройдено ланцюжок: вибір у діалозі -> HTTP збереження metadata та ObjectModule -> HTTP проведення -> читання очікуваного руху -> скасування.
- Offscreen-рендер діалогу перевірено в `.artifacts/posting-mapping.png`. Робоча БД і запущені застосунки користувача не змінювалися.
- Попередні обмеження щодо вкладених script reference-викликів і відсутності конструктора зіставлення полів більше не актуальні. Повний dispatch загальних модулів, query/catalog API в контексті проведення, бухгалтерські/розрахункові регістри, атомарний SaveAndPost і міграція legacy-проведень залишаються окремими незавершеними етапами.

## 2026-09-19 - Серверні загальні модулі у транзакції проведення

### Що зроблено
- Додано окремий strict PostingModuleRegistry: точні технічні імена, Source Name, UK/EN aliases і code refs; синоніми й fuzzy-підстановки не використовуються. Підтримано прямі виклики та префікси `CommonModule` / `ЗагальнийМодуль`.
- Джерела завантажуються за owner GUID лише при зверненні, з inline text або asset. Потрібні явний прапорець `server: true`, єдиний збережений `Module` і експортована процедура/функція. Відсутні/неоднозначні модулі не підміняються ManagerModule чи порожнім результатом.
- UK/EN aliases використовують один екземпляр у межах операції, включно з before/after hooks. Наступна операція створює новий реєстр і читає актуальний збережений код. Циклічна ініціалізація завершується помилкою.
- Параметри за посиланням збережені через межу модулів, включно зі скалярними полями й відмовою. Загальні модулі не отримують неявні реквізити документа або DB handle; знімки залишаються read-only.
- ObjectModule, hooks, загальні модулі та динамічний код мають спільний бюджет інструкцій/глибини/джерел. Помилки metadata й вичерпання бюджету не перехоплюються DSL Try/Except, звичайні бізнес-винятки перехоплюються.
- У DSL виправлено вихід Break/Continue із Try, очищення внутрішнього ітератора ForEach і перехід Continue до інкремента лічильника. Це усуває зависання та помилкові переходи у вкладених циклах.

### Межі
- Цей запис уточнює попереднє обмеження: qualified dispatch серверних загальних модулів тепер працює; неявний імпорт глобальних функцій, query/catalog API, бухгалтерські/розрахункові регістри, SaveAndPost і матеріалізація імпортованих даних ще не реалізовані тут.
- Parser поки не вибирає гілки умовної компіляції. Проведення відхиляє такі директиви й `#Use`, замість виконання обох гілок. Region дозволено; клієнтські/невідомі анотації виконуваних процедур відхиляються. Типовий client registry не змінено.
- Неповні імпортні metadata без підтвердженого Server не виправляються припущенням. Виправлення імпорту та реалізація compile-time context потребують окремого етапу.

### Перевірка
- Тимчасова файлова БД: вкладена відмова, aliases, фізичні поля, missing/private/duplicate modules, source assets, latest-source reload, rollback і ізоляція стану.
- Реальний HTTP: збережено дві редакції загального модуля, проведено/скасовано тестовий документ і перевірено результат кожної редакції. Live DB не відкривалася, Runtime/Client користувача не перезапускалися.
- Профільний regression-набір Configurator/Client/Runtime/DSL/mpdb: `696 passed, 1 skipped` за 67.09 с; пропущено лише перевірку конкурентного zstd-декодування через відсутність `zstandard` у `.venv`. Це не повний suite репозиторію. Звіт: `.artifacts/posting-mapping-tests.xml`.
- `compileall` змінених модулів пройдено; offscreen-зображення конструктора оновлено та переглянуто: `.artifacts/posting-mapping.png`. `git diff --check` не виявив whitespace-помилок; незареєстровані змінені Python-файли перевірено окремо.

## 2026-09-19 - Умовна компіляція серверного контексту

### Що зроблено
- Додано окремий `src/dsl/preprocessor.py`. Перед компіляцією проведення вибирається лише відповідна гілка `#If/#ElsIf/#Else/#EndIf`; підтримано вкладення, дужки, Not/And/Or, UK/EN та внутрішні RU import aliases. Невідомі symbols/directives не вважаються false і не перетворюються на коментарі.
- Контекст проведення визначає Runtime, не змінні скрипту і не наявність файлової mpdb: Server/AtServer true, клієнтські/external/mobile contexts false. Загальний parser та client registry автоматично не перемикаються на серверний контекст.
- Неактивні declarations/exports не компілюються. Директиви всередині рядків і коментарів не виконуються. Робочий текст маскується в пам'яті зі збереженням позицій та CRLF; збережені модулі/asset не змінюються.
- Динамічний Do/Виконати виконує підготовлений module, а не повторно компілює сирий source з обома гілками. Live reference bindings і спільні ліміти збережені. Frame зберігає ідентичність джерела; dynamic `:execute` й викликані звичайні процедури мають різні diagnostic locations.
- Lexer повертає точні source offsets, обробляє BOM і пропускає довгі серії коментарів ітеративно. Прибрано копіювання всього залишку source на кожній директиві.
- Lexer/parser розпізнають #ElsIf/#ElseIf/#ІнакшеЯкщо. У Qt highlighter виправлено пріоритет правил (директиви раніше перекривалися коментарями) й Unicode-межі для українських директив.

### Перевірено
- Профільний набір Configurator/Client/Runtime/DSL/mpdb/Qt highlighter: `779 passed, 1 skipped` за 78.28 с. Пропущено тест zstandard через відсутню залежність; це не весь suite репозиторію. Звіт: `.artifacts/posting-preprocessor-tests.xml`.
- Окремо import/source compatibility: `54 passed` за 1.22 с. `compileall` пройдено.
- На тимчасовій файловій БД перевірено HTTP-збереження двох редакцій conditional common module, проведення/скасування, незмінність source після виконання, nested cancellation і rollback. Перевірено відсутність завантаження модуля з клієнтської гілки.
- Перевірено початкові рядки помилок після неактивної гілки, dynamic reference output і відмінність `:execute` від звичайного frame. Offscreen-підсвітку переглянуто: `.artifacts/preprocessor-highlighting.png`.
- Синтетична перевірка 160670 символів / 2000 умов вибрала всі серверні гілки за 0.114 с на поточному середовищі. Це не вимірювання швидкості повного імпорту або live проведення.
- Live DB і запущені застосунки користувача не змінювалися та не перезапускалися.

### Межі
- Уточнено попередню заборону conditional compilation: базовий server-context preprocessing працює. #Use, extension directives, невідомі контексти та malformed blocks відхиляються, включно з неактивними гілками. Рядки/коментарі повинні бути лексично завершені в усьому source; nesting limit 128.
- Не реалізовано conditional compilation для всіх інших точок виконання, автоматичне приглушення неактивного коду в IDE, повний compile-context аналіз, Query/catalog API, неявні global modules, бухгалтерські/розрахункові регістри та SaveAndPost. Ці можливості не заявляються як завершені.

## 2026-09-20 - IDE: lexical context, відступи та клавіатурний completion

### Що зроблено
- Інвентаризовано вже реалізовані можливості; додано `src/docs/IDE_STATUS.md` з окремими переліками завершеного, межами та наступною чергою. Posting/runtime можливості не реалізовувалися повторно.
- Відтворено й виправлено п'ять помилок highlighter: лапки в коментарях, comment markers у рядках, протікання multiline-comment state, multiline strings і перекриття keywords CamelCase-правилом.
- Додано Qt-free `editor_syntax.py`: tolerant per-line scanner використовує словники compiler languages. BSL doubled quotes, literal backslashes і коментарі між continuation lines відповідають lexer. Qt highlighter переносить lexical state між блоками та переводить source offsets у UTF-16.
- Додано whitespace-only reindent (`Ctrl+Alt+L`, контекстне меню). Виділення враховує зовнішню вкладеність; Undo єдиний; рядки breakpoints, caret/selection/scroll збережені. Вміст рядкових літералів та внутрішні рядки block comments не переписуються.
- Enter використовує syntax tokens замість startswith/endswith. Виправлено пропущений відступ procedure/function, тіло Else/Except, повторне зменшення вже правильного відступу EndIf, false positives EndDate/ElseValue і trailing comments.
- QTest підтвердив дефект completion: Enter/Tab вставляли newline/spaces замість приймання вибору. Тепер popup має пріоритет; стрілки, Enter/Tab, повторний Ctrl+Space та Esc працюють із клавіатури. У literals/comments completion не відкривається й не запитує Runtime provider.
- Парні дужки вставляються лише в коді, не дублюють closer, видаляються парою через Backspace. Read-only захищено від programmatic edits без вимкнення definition navigation.

### Перевірено
- Профільний regression-набір: `842 passed, 1 skipped` за 77.86 с. Skip: відсутній zstandard; це не весь suite репозиторію. Звіт: `.artifacts/ide-editing-tests.xml`.
- Qt keyboard events, Undo/Redo, reversed selection, multiline state updates, non-BMP offsets; compiler tokens і string values незмінні після форматування.
- Offscreen UK/EN render переглянуто: `.artifacts/ide-editing-uk-en.png`; шрифти додано лише до перевірочного Qt-процесу. Синтетично 155999 символів / 9000 рядків відформатовано за 0.050 с, повторний результат ідентичний.
- Live DB та запущені застосунки користувача не змінювалися/не перезапускалися.

### Інваріанти та межі
- Вирівнювання не змінює бізнес-код, імена, literals чи кількість рядків і не є AST pretty-printer. Tolerant scanner не підміняє validating parser.
- Inline signature help, precise-span diagnostics, IDE compile-context, інкрементальний semantic completion і повноцінні snippet tab stops залишаються наступними кроками, а не оголошуються завершеними.

## 2026-09-21 - Runtime: закриття, точкові metadata та packed business data

### Першопричини та зміни
- На окремій копії `F:/TestBD/MetaDB/metabase.mpdb` підтверджено, що packed-рядки
  містили дані, але поля `fldNNN` не були зв'язані з реквізитами. Додано точне
  зіставлення `src_uuid -> DBNames Fld/VT -> field_map`; порядок імен і синоніми
  не використовуються. Прив'язано всі 75 реквізитів документа реалізації та
  колонки його табличної частини. Ідентичність посилань збережена поряд із текстом.
- Нові міграції зберігають `storage_bindings` у migration manifest. Legacy-reader
  читає DBNames лише раз, якщо карта відсутня; source `.1CD` відкривається read-only.
  Відсутність карти показується окремою помилкою прив'язки, не вгадується.
- Перша обмежена сторінка більше не потрапляє в кеш як повний набір. Перевірено
  наступну сторінку, повне читання імпортованого набору та GUID останнього документа.
  Пошкоджений/відсутній offloaded asset повертає помилку, не порожні реквізити.
- У наявній БД migration manifest містить `limit_per_table=20`: для `_DOCUMENT174`
  імпортовано 20 записів, `source_rows=39` (фізичні записи, не доказ 39 активних
  документів). CLI більше не переносить preview `--limit=20` на реальний імпорт;
  вибірковий імпорт вимагає явного позитивного `--data-limit`. Клієнт показує
  попередження про sample-міграцію. Стару production-базу не переімпортовано.
- Повний та slim manifest snapshots розділено. Точкові payload-запити читають
  лише потрібні asset; subtree використовує кешований parent index. Службові
  папки `type=form, kind=folder` більше не вважаються формами. Саме порожні
  запити їхніх модулів запускали повторні table scans. Inline module text не
  передається в `object_context`, вихідний код залишається лінивим.
- `session.close` обмежено 1 с замість 30; gateway від'єднується перед RPC.
  Пізня відповідь `session.create` не відновлює закриту сесію. Service від'єднує
  свій стан навіть при помилці cleanup. Фонова діагностика більше не використовує
  активний parent-owned QThread, який міг видалятися разом із вікном.
- Importer не визначає numeric type за словом Number/Номер. Renderer враховує
  `number_type` для вже імпортованих форм. DateBox читає ISO datetime та зберігає
  часову частину при зборі значень; Number не перетворюється на `0,00`.
  TablePanel реєструє binding для команд табличної частини; Ref/LineNumber
  використовують системні ключі. Порожнє посилання не показує нульовий UUID.

### Перевірка
- `1038 passed, 1 skipped`, 121.77 с; профільний, не повний suite. Звіт
  `.artifacts/runtime-client-ide-tests.xml`; skip конкурентного zstd-тесту
  через відсутність пакета у `.venv`.
- Реальний HTTP RuntimeHandler -> RuntimeGateway -> FormRuntimeWidget на
  ізольованій копії з Python 3.13 і zstandard. Джерело та live-БД не змінювалися,
  застосунки користувача не перезапускалися, form modules не виконувалися.
- `manifest.object_context` скоротився з 1,7-2,3 с до приблизно 0,04 с.
  Перший запит бізнес-даних ще потребує 1,5-1,8 с на ініціалізацію legacy-карти;
  повторне читання імпортованого набору близько 0,01 с, GUID lookup близько 0,002 с.
  Це вимірювання діагностичної копії, не SLA production.
- Рендер списку й картки перевірено: сума, контрагент, організація, валюта, склад,
  номер/дата та три рядки товарів першого документа. Артефакти
  `.artifacts/client-imported-data.png`, `client-imported-data-object.png`,
  `client-imported-data.json`; повторюваний скрипт `src/scripts/check_imported_client_data.py`.
- Закриття Configurator перевірене із HTTP-сервером, що не відповідає; окремий
  subprocess закриває вікно з незавершеним diagnostics loader без аварії Qt.

### Межі та наступні дії
- Повна безпечна міграція бізнес-даних і перевірка overlay-змін ще потрібні:
  backup -> staging -> validate -> swap. Жодного live swap у цій ітерації.
- Частина enum refs поки показує UUID; query-derived колонки на зразок ВидЦен
  не є реквізитами документа й не заповнюються цим зіставленням. Multi-storage
  variants без discriminator не вгадуються. Повна сумісність форм/модулів,
  редагування та проведення імпортованих даних не заявляються як перевірені.

## 2026-09-21 - IDE: inline signature help

- Попередній пункт про відсутність inline signature help більше не актуальний.
  Реалізовано automatic/manual Ctrl+Shift+Space, активний параметр, nested та
  multiline calls, локальні unsaved declarations, Val/defaults, UK/EN.
- SignatureDocument використовує compiler Lexer, кеш source offsets і lexical
  контекст. UTF-16 Qt переводиться явно. Неоднозначні declarations і затінення
  не підміняються builtin; невідомі methods не отримують вигадану сигнатуру.
- Runtime exports завантажуються поза UI thread з обмеженням паралельності й
  перевіркою застарілих відповідей. Великі source snapshots також фонові.
  Для remote exports доступні імена параметрів, не Val/default metadata.
- Qt-клавіші, фокус, Escape, late results і strings/comments перевірені тестами;
  UK/EN popup відрендерено та переглянуто. Precise diagnostics, IDE compile
  context, повна incremental analysis, snippets/tab stops залишаються в черзі
  `src/docs/IDE_STATUS.md`; їх не оголошено виконаними.


## 2026-09-27 - Parse1CD ядро включено в MetaPlatform

### Что изменено
- Актуальный read-only reader, schema reader, reference resolver и decoder находятся в `src/infra/onec/parser`; UI Parse1CD и запись обратно в `.1CD` не перенесены.
- `src/infra/onec/backend.py` является общей точкой загрузки. Проверка physical schema, semantic `OneCDConfigSource` и business-data migration обращаются к одному `OneCDatabase`; нет поиска `META_PARSE1CD_PARSER`, `WorkedData/Parse1CD`, `F:/Parse1CD` или загрузки одноимённых глобальных Python-модулей.
- Сохранены legacy consumer contracts для скрытой версии записей, индексов, файлов `Params/DBNames` и чтения BLOB. В physical-schema summary добавлено явное число ошибок table-descriptor parsing.
- Штатный импорт уже живёт в Configurator -> Runtime; самостоятельный запуск Parse1CD для импорта не требуется. Table-browser/export GUI Parse1CD не объявлен перенесённым.
- Реальный bounded smoke `src.scripts.check_onecd_backend` использует только указанный оператором `.1CD`, пишет не в источник, импортирует максимум выбранное число записей во временный `mpdb`, повторно открывает её и проверяет SHA-256 источника до и после.

### Проверка
- Полный `pytest -q src/tests`: `1351 passed, 1 skipped, 4 warnings`.
- Профильные backend/metadata/data migration и control API tests: `130 passed`; после добавления диагностики — `18 passed`.
- `compileall -q src`, `git diff --check` и `ci_private_data_check` прошли.
- Runtime -> Configurator -> Client process smoke завершился успешно: Configurator трижды стартовал/закрылся; три shutdown заняли 0.077, 0.096 и 0.082 с.
- Read-only smoke на приватном `WorkedData/1Cv8.1CD` (1,237,123,072 байта): общий backend нашёл 3,583 таблицы, 32,205 полей, 7,813 индексов, декодировал DBNames, построил 4,543 metadata objects и 15,229 files. Временный import сохранил строку после reopen; исходный SHA-256 совпал: `6d6146f7d344680c3dabe836e7b2d822e47e426e10e8e1c725d03411ad23bf0a`.

### Границы
- Reader поддерживает физический тип `VB` как поле с объявленной inline-шириной и сохраняет его содержимое как сырые bytes. На этой базе теперь открываются 3,583 table descriptors без ошибок (ранее пропускались четыре descriptors с типом `VB`); у этих четырёх таблиц потоки данных пустые, поэтому реальные непустые `VB`-значения этой базой не проверяются. Добавлен синтетический тест ширины 16 байт и raw decoding.
- Smoke импортировал одну строку (лимит 2) и не доказывает полноту бизнес-миграции, повторный production import, sample/document completeness или live swap. Это остаётся в [issue #2](https://github.com/EritikWoW/MetaPlatform/issues/2).
- Для объединённого backend CI прошёл на Windows: полный suite и Runtime + Configurator + Client process smoke зелёные; `pip-audit` также прошёл после обновления исправленных build tools. Текущие изменения `VB` повторно проверяются локально на полном suite; remote CI будет запущен после push.

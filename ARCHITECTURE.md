# MetaPlatform Architecture

MetaPlatform - платформа разработки бизнес-приложений с собственной файловой БД, runtime-сервером, configurator IDE и клиентским приложением. По факту это desktop-first система с разделением на storage, runtime, metadata/configurator, client UI и import/DSL tooling.

## 1. Основные подсистемы

### 1.1. Storage: `mpdb`
Пакет: `src/mpdb`

`mpdb` - встроенный файловый движок платформы.
Он отвечает за:

- хранение таблиц
- хранение ассетов
- WAL (write-ahead log)
- recovery
- allocator страниц
- CRC контроль
- сжатие страниц

`mpdb` является **основным storage-слоем платформы**, но не является API для UI.

### 1.2. Runtime server
Пакет: `src/runtime`

Runtime - HTTP/JSON-RPC сервер выполнения.
Он отвечает за:

- открытие и удержание баз (`DbPool`)
- управление сессиями
- операции над manifest
- операции над таблицами
- операции над ассетами
- импорт 1C/BAS
- runtime-сервисы (печать, отчеты, проведение)

Runtime является **единственным компонентом, владеющим live-доступом к mpdb** во время работы UI.

Точка входа для запуска сервера:
- `src/scripts/run_runtime_server_cmd.py`

### 1.3. Gateway / RPC transport
Файл: `src/runtime/gateway.py`

`RuntimeGateway` - клиентский RPC-транспорт для UI и сервисов.
`GatewayDb` и `GatewayTable` - адаптеры, позволяющие Configurator работать с Runtime как с drop-in DB API без прямого доступа к живой `mpdb`.

### 1.4. Configurator
Пакет: `src/configurator`

Configurator - среда редактирования конфигурации. Подсистема разделена на:
- `application` - сервисы и orchestration;
- `domain` - модели, шаблоны и defaults;
- `persistence` - manifest/system tables/config storage/schema deployment;
- корневые Qt-окна и контроллеры.

Штатный путь работы Configurator:
Configurator UI -> `ConfiguratorService` -> `RuntimeGateway` -> Runtime RPC -> `mpdb`

Важно: в текущем коде есть модули persistence, которые знают о структуре `mpdb`, но рабочий UI-контур конфигуратора ориентирован на Runtime RPC, а не на прямое открытие live-БД.

### 1.5. Shared Qt UI layer
Пакет: `src/ui_qt`

Это общий UI-слой платформы, в котором находятся:
- launcher;
- runtime admin UI;
- темы и иконки;
- i18n;
- viewmodels;
- reusable widgets/services.

Отдельно важно понимать, что `ui_qt` - это не только configurator: он содержит общие desktop-элементы всей платформы.

### 1.6. Client application
Пакет: `src/client`

Client - отдельное приложение для пользовательской работы с конфигурацией через runtime. Он использует runtime context и UI/forms слой, а не configurator-контур.

### 1.7. DSL
Пакет: `src/dsl`

В проекте есть собственный DSL и инструменты вокруг него:
- lexer;
- parser;
- diagnostics;
- validator;
- VM/API.

DSL применяется прежде всего для модулей/скриптов и связанной runtime-логики.

### 1.8. 1C/BAS import
Пакеты: `src/infra/onec`, `src/tools/onec_import.py`

Импорт 1C/BAS - отдельная подсистема трансформации внешней конфигурации в структуру MetaPlatform. Импорт сейчас завязан на Runtime RPC и безопасный staged workflow.

Read-only парсер `.1CD` поставляется внутри `src/infra/onec/parser` и имеет один
адаптер `backend.py`. Проверка физической схемы, чтение semantic metadata и
миграция бизнес-данных используют один класс `OneCDatabase`; поиск установки
Parse1CD в профиле пользователя, `WorkedData` или по абсолютному Windows-пути
не является частью рабочего контура. Отдельный GUI Parse1CD в MetaPlatform не
запускается: выбор источника, preview и импорт выполняются через Configurator/
Runtime; standalone table-browser/export UI не заявлен как перенесённый.

Physical-schema diagnostics expose descriptor-error counts; a successful file open alone does not prove that every physical field was decoded.

### 1.9. Platform API
Пакет: `src/mp_platform`

Это более высокий API поверх `mpdb`, дающий сущности уровня catalog/document/register. Он полезен для тестов, платформенного слоя и будущих сценариев, но не заменяет runtime/configurator контур.

## 1.10. Architecture Layers

MetaPlatform построена как многослойная платформа.
Ключевой принцип: UI не должен работать напрямую с live `mpdb`; штатный путь идёт через Runtime RPC. Это согласуется с текущей архитектурой проекта, где Configurator ориентирован на `RuntimeGateway`, а Manifest остаётся источником истины по структуре конфигурації.

### Layered view

┌────────────────────────────────────────────────────────────┐
│                        UI Layer                            │
│------------------------------------------------------------│
│ Configurator UI                                            │
│ Client UI                                                  │
│ Launcher                                                   │
│ Runtime Admin UI                                           │
│ Shared Qt widgets/themes/i18n                              │
│ Packages: src/configurator, src/client, src/ui_qt          │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                    Application Layer                       │
│------------------------------------------------------------│
│ ConfiguratorService                                        │
│ ViewModels / UI services                                   │
│ Import orchestration                                       │
│ Runtime startup / database selection                       │
│ Structure cache                                            │
│ Packages: src/configurator/application, src/ui_qt/...      │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                  Transport / Access Layer                  │
│------------------------------------------------------------│
│ RuntimeGateway                                             │
│ GatewayDb / GatewayTable                                   │
│ HTTP / JSON-RPC transport                                  │
│ Package: src/runtime/gateway.py                            │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                     Runtime Layer                          │
│------------------------------------------------------------│
│ Runtime Server                                             │
│ Session manager                                            │
│ DbPool / registry                                          │
│ Manifest operations                                        │
│ Table / asset operations                                   │
│ 1C import workflow                                         │
│ Reports / print / posting / admin services                 │
│ Package: src/runtime                                       │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                Platform / Domain Layer                     │
│------------------------------------------------------------│
│ Manifest model                                             │
│ Metadata object model                                      │
│ mp_platform API                                            │
│ DSL parser / validator / VM                                │
│ 1C canonical mapping / DSL bridge                          │
│ Packages: src/mp_platform, src/dsl,                        │
│           src/configurator/domain, src/infra/onec          │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                      Storage Layer                         │
│------------------------------------------------------------│
│ mpdb                                                       │
│ page storage                                               │
│ WAL / recovery                                             │
│ allocator / CRC / compression                              │
│ assets / tables / low-level metadata                       │
│ Package: src/mpdb                                          │
└────────────────────────────────────────────────────────────┘

## 1.11. Dependency direction

UI
  ↓
Application
  ↓
Transport / Access
  ↓
Runtime
  ↓
Platform / Domain
  ↓
Storage

## 2. Архитектурный поток

Основные сценарии выглядят так:

### 2.1. Запуск через launcher
Launcher (`src/ui_qt/app.py`, `src/ui_qt/launcher_window.py`)
-> выбор базы
-> проверка/подъем runtime
-> запуск Configurator или Client

### 2.2. Работа configurator
Configurator window/viewmodel
-> `ConfiguratorService`
-> `RuntimeGateway`
-> Runtime RPC
-> `GatewayDb` / server-side manifest operations
-> `mpdb`

Жизненный цикл соединения:
- Configurator создает отдельную Runtime RPC-сессию;
- повторное открытие одного пути переиспользует live-дескриптор из `DbPool`;
- закрытие `GatewayDb` завершает RPC-сессию, но не выгружает общую базу из Runtime;
- Runtime как служба сохраняет прогретый пул баз и manifest/cache индексы между подключениями UI.

### 2.3. Работа client
Client app/window
-> runtime context
-> Runtime RPC
-> чтение конфигурации и данных

### 2.4. Импорт 1C/BAS
UI/tooling
-> Runtime RPC `onec.import`
-> staging copy базы
-> import + validate
-> swap в live DB

## 3. Источники истины

В проекте несколько важных источников истины:
- Manifest в `mpdb` - источник истины по структуре конфигурации.
- `mpdb` - источник истины по persisted данным и ассетам.
- Structure cache (`*.structure_cache.json`) - только ускоряющий кэш, не источник истины.
- Документ `src/docs/O_PRODELANNOI_RABOTE.md` - источник принятых инвариантов и исторических решений, которые нельзя ломать без осознанного пересмотра.

## 4. Принципы

1. Live-доступ к базе должен централизоваться через Runtime.
2. Configurator и Client не должны расходиться по моделям доступа к данным.
3. Инварианты manifest/object policies/tree building должны задаваться централизованно, а не копироваться по UI.
4. Импорт и другие тяжелые операции должны быть безопасными и восстановимыми.
5. Архитектура должна оставаться независимой от внешних СУБД.

## 5. Актуальные ограничения и технический долг

На текущем этапе проекта есть важные особенности:
- репозиторий содержит большой объем незакоммиченных изменений и ассетов;
- встречаются исторические следы миграций и runtime-артефактов в дереве `src/`;
- корневой `pyproject.toml` пока не оформлен как реальный packaging/source-of-truth файл;
- часть модулей все еще несет следы перехода от direct DB access к Runtime RPC.

Эти ограничения нужно учитывать при любых архитектурных выводах.

## 6. Structure Cache

Для ускорения старта Configurator используется cache структуры конфигурации.

Файл:

<database>.structure_cache.json

Cache содержит:

- дерево объектов конфигурации
- типы объектов
- отображаемые имена
- GUID объектов

Этот cache создается runtime/import процессом и используется UI для быстрого построения дерева.

Важно:

Structure cache **не является источником истины**.
Source of truth — manifest внутри mpdb.


## 7. Import workflow

Импорт внешних конфигураций (например 1C/BAS) выполняется безопасным staged workflow:

1. Backup текущей базы
2. Создание staging copy базы
3. Импорт структуры
4. Импорт модулей
5. Валидация структуры
6. Swap staging → main database

Это позволяет:

- избежать повреждения рабочей базы
- безопасно отменять импорт
- гарантировать консистентность manifest


## 8. Runtime ownership rule

В платформе действует принцип:

Runtime владеет live mpdb.

Это означает:

- UI не должен напрямую открывать mpdb
- все операции должны идти через Runtime RPC
- Configurator и Client используют RuntimeGateway

Стандартный поток:

UI
 ↓
RuntimeGateway
 ↓
Runtime server
 ↓
mpdb

Это обеспечивает:

- централизованный доступ к базе
- единые политики безопасности
- единые транзакционные правила.

## 6. Structure Cache

Для ускорения запуска Configurator используется кеш структуры конфигурации.

Файл:
<database>.structure_cache.json

Structure cache содержит:

- дерево объектов конфигурации
- GUID объектов
- типы объектов
- отображаемые имена

Назначение кеша:

- ускорить построение дерева конфигурации
- сократить количество runtime RPC вызовов
- ускорить cold start Configurator

Важно:

Structure cache **не является источником истины**.

Source of truth:

- manifest внутри mpdb
- таблицы metadata


## 7. Import Pipeline

Импорт внешних конфигураций (например 1C/BAS) выполняется через безопасный staged workflow.

Стандартный pipeline:

1. Backup текущей базы
2. Создание staging copy базы
3. Импорт структуры
4. Импорт модулей
5. DSL трансформация
6. Валидация manifest
7. Swap staging → main database

Преимущества подхода:

- защита рабочей базы
- возможность rollback
- гарантированная консистентность структуры
- возможность прерывания импорта


## 8. DSL Transformation Layer

При импорте внешних конфигураций используется промежуточный слой трансформации.

Pipeline выглядит следующим образом:

External Source (1C/BAS)
        ↓
Canonical Metadata Model
        ↓
DSL Transformation
        ↓
MetaPlatform DSL
        ↓
Runtime Execution

Этот слой позволяет:

- нормализовать синтаксис
- поддерживать несколько языков (UA / EN)
- избежать привязки к синтаксису 1C


## 9. Runtime Ownership Rule

В платформе действует принцип:

**Runtime владеет live mpdb.**

Это означает:

- UI не должен напрямую открывать mpdb
- доступ к данным идет через Runtime RPC
- Configurator и Client используют RuntimeGateway

Стандартный поток доступа:

UI
 ↓
RuntimeGateway
 ↓
Runtime Server
 ↓
mpdb

Это обеспечивает:

- централизованное управление доступом
- единые политики транзакций
- контроль жизненного цикла базы


## 10. Architectural Principles

Document posting follows this ownership rule as well: the client sends one
`document.post` / `document.unpost` RPC. Runtime executes the saved ObjectModule
against snapshots and movement buffers, then commits the header flag and register
rows in one `mpdb` transaction. See `src/docs/RUNTIME_POSTING.md` for the supported
script surface, validation rules and remaining compatibility limits. Form saving
is separate and is not yet an atomic SaveAndPost operation.

The movement constructor persists an explicit, versioned field-mapping plan and
generates a UK/EN draft; only the separately saved ObjectModule is executable.
Posting resolves server common modules lazily by manifest technical identity and
owner GUID, never by synonym. Object handlers, hooks and common modules share one
transaction-scoped registry and execution budget. The tolerant client-side
registry is not used for posting. An explicit server-context preprocessor selects
conditional branches before compiling object/common modules, hooks and dynamic
code. It preserves source coordinates and never rewrites saved sources. Unknown
symbols/directives and malformed blocks fail closed; other execution paths do
not silently inherit the server context. See the posting contract for its subset
and the remaining query/API limitations.

Ключевые архитектурные принципы платформы:

1. Storage engine изолирован от UI.
2. Runtime является единственной точкой доступа к live базе.
3. Manifest является источником истины структуры конфигурации.
4. Импорт должен быть безопасным и воспроизводимым.
5. Платформа должна оставаться независимой от внешних СУБД.
6. UI слой должен быть максимально thin.


## 11. Future Architecture Directions

Планируемые направления развития:

- Query Engine
- DSL Compiler
- Form Runtime
- Business Logic Engine
- Distributed Runtime
- Plugin system

Главная цель — развитие платформы без нарушения слоистой архитектуры.

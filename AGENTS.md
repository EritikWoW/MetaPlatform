# MetaPlatform

## Назначение
MetaPlatform - настольная платформа разработки бизнес-приложений с собственным файловым хранилищем `mpdb`, runtime-сервером, configurator UI, клиентом и набором инструментов импорта/DSL.

## Актуальная карта проекта
Основной код находится в `src/`.

Ключевые подсистемы:
- `src/mpdb` - файловый движок хранения и WAL/recovery.
- `src/runtime` - HTTP/JSON-RPC runtime-сервер, реестр БД, gateway-совместимый API, движки отчетов/проведения/печати.
- `src/configurator` - configurator UI + application/domain/persistence слой для работы с manifest и метаданными.
- `src/client` - клиентское приложение и формы runtime.
- `src/ui_qt` - общий Qt UI-слой: launcher, runtime admin, темы, i18n, widgets, services, viewmodels.
- `src/dsl` - lexer/parser/validator/vm для внутреннего DSL.
- `src/infra/onec` и `src/tools/onec_import.py` - импорт и трансформация структуры 1C/BAS.
- `src/mp_platform` - высокоуровневый platform API поверх `mpdb`.
- `src/tests` - тесты.
- `src/docs/O_PRODELANNOI_RABOTE.md` - журнал решений, инвариантов и исторических фиксов.

## Документы и их роли
- `AGENTS.md` - краткие правила и ориентиры для работы в репозитории.
- `ARCHITECTURE.md` - целевая и фактическая архитектурная схема проекта.
- `src/docs/O_PRODELANNOI_RABOTE.md` - changelog/decision log: что уже сделано, какие инварианты нельзя ломать.

При конфликте:
1. Фактический код в `src/` важнее текста документа.
2. Инварианты из `src/docs/O_PRODELANNOI_RABOTE.md` нельзя нарушать без явного пересмотра документа.
3. `ARCHITECTURE.md` описывает целевую и текущую архитектуру, но не должен противоречить коду.

## Архитектурные правила
1. `mpdb` остается основным storage-слоем платформы.
2. Для Configurator основным способом доступа к данным считается Runtime RPC через `RuntimeGateway`/`GatewayDb`.
3. Runtime - единственный процесс, который должен владеть live-доступом к production/local DB во время штатной работы UI.
4. Manifest является источником истины по структуре конфигурации.
5. Structure cache ускоряет запуск, но не является источником истины.
6. Тяжелые импортные операции должны выполняться по безопасной схеме `backup -> staging -> validate -> swap`.

## Языки
Поддерживаемые UI/DSL локали:
- Ukrainian (`uk`)
- English (`en`)

Русская локаль как штатная локаль проекта не поддерживается.

## Практические замечания
- В проекте есть исторический пласт изменений; перед правкой нужно сверять код с `src/docs/O_PRODELANNOI_RABOTE.md`.
- В репозитории встречаются runtime-артефакты (`__pycache__`, `.pytest_cache`) и большие наборы ассетов; не принимать их за архитектурные модули.
- У проекта есть launcher, configurator, client и runtime admin - это разные точки входа, а не один UI.

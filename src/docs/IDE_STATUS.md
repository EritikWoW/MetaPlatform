# IDE: стан реалізації та наступні кроки

Стан звірено з кодом 2026-09-21. Це карта можливостей, а не заява про
production-ready IDE або повну сумісність із 1C/BAS.

Перед новою ітерацією перевіряти цей список та журнал
`O_PRODELANNOI_RABOTE.md`. Уже реалізовану можливість не робити повторно:
повертатися до неї лише з конкретним відтворенням дефекту або новою вимогою.

## Уже реалізовано

| Можливість | Реалізація / перевірка |
| --- | --- |
| UK/EN редактор; mixed лише для сумісності імпортованих модулів | `code_editor_widget.py`, `languages.py` |
| Підсвічування, номери рядків, локальна діагностика незбереженого тексту | `code_editor_widget.py`, `metascript_highlighter.py` |
| Workspace Problems і Runtime semantic index | `workspace_symbols`, тести Configurator і semantic index |
| F12 / Ctrl+Click, Shift+F12, локальне й workspace-перейменування | `resolve_definition_target`, `semantic_rename`; workspace preview перед застосуванням |
| Completion локальних змінних, параметрів, metadata та експортів загальних модулів | `completion.py`, `module_introspection.py`, Runtime provider |
| Inline signature help, активний аргумент, Ctrl+Shift+Space | `signature_help.py`, `SyntaxAssistantController`; UK/EN, локальні незбережені declarations та точні Runtime exports |
| Список процедур/функцій і Ctrl+G | `CodeEditorWidget` |
| Пошук/заміна, конструктори базових конструкцій | `CodeEditorWidget`, `code_templates.py`; це ще не snippet engine із tab stops |
| Breakpoints, step, call stack, locals/globals, debug expressions | `CodeEditorWidget`, debugger tests |

## Завершено в цій ітерації

- Спільний tolerant lexical context для редактора: BSL-подвоєння лапок,
  literal backslashes, багаторядкові рядки з `|`, коментарі між continuation
  lines. `/*` у рядку не перетворює решту модуля на коментар; лапки в коментарі
  не створюють рядковий літерал. Ключові слова мають пріоритет над CamelCase.
- `Ctrl+Alt+L` або контекстне меню вирівнює відступи виділених рядків, а без
  виділення - всього модуля. Зовнішні scopes враховуються навіть для виділення.
  Зберігаються напрямок виділення, позиція в коді, рядки breakpoints і scroll.
  Операція скасовується одним Undo; повторний запуск не змінює результат.
- Enter враховує процедури/функції, цикли, умови, Try/Except, переноси аргументів,
  trailing comments. `Else`/`Виняток` вирівнюються за блоком, наступний рядок
  отримує відступ тіла. `EndDate`/`ElseValue` не вважаються кінцем/гілкою блоку.
- Стрілки обирають completion; Enter/Tab приймають вибір, а не вставляють
  newline/пробіли. Ctrl+Space відкриває список з першим варіантом; повторне
  натискання приймає вибір. Esc закриває список. Повністю дописане слово не
  викликає автоматичну підказку.
- Completion і парні дужки не втручаються в рядки/коментарі. Вже вставлена
  закривальна дужка не дублюється; Backspace між парними дужками видаляє пару.
  Read-only блокує programmatic editing, але не перехід до визначення.
- Qt UTF-16 offsets враховано для lexical spans і completion після non-BMP
  символів. Це не означає аудит усіх координат semantic navigation.

### Межі форматування

Це **вирівнювання початкових відступів**, не AST pretty-printer: воно не змінює
оператори, регістр імен, пробіли всередині виразів чи мову коду. Рядки, які
почалися всередині string/block comment, залишаються незмінними. CRLF, BOM,
кількість рядків і значення рядкових літералів зберігаються. Неповний буфер
обробляється толерантно, без автоматичного виправлення синтаксису.

`editor_syntax.py` не замінює compiler lexer/parser. Діагностика синтаксису
залишається за парсером; formatter не приховує помилки.

## Наступна черга

1. Точні діапазони діагностик замість підкреслення цілого рядка; навігація
   і перевірені quick fixes без автоматичної fuzzy-підміни бізнес-API.
2. Явний compile context редактора, аналіз та приглушення неактивних гілок.
   Серверний preprocessor для проведення вже є; він не означає, що вся IDE
   повинна неявно вважати себе серверним модулем.
3. Інкрементальність completion/diagnostics на великих модулях. Лексичний
   highlighter працює по блоках, але semantic introspection completion ще
   перечитує буфер. Час formatter не є оцінкою затримки всього редактора.
4. Повноцінні snippets із переходом між placeholders та code folding.
   Базові шаблони, block indent і навігація вже є; розширювати їх, а не дублювати.

## Перевірка цієї ітерації

- Профільний regression-набір Configurator/Client/Runtime/DSL/mpdb/Qt:
  **842 passed, 1 skipped**, 77.86 с; це не весь suite репозиторію.
  Пропущено конкурентний zstd test через відсутній `zstandard`.
  Звіт: `.artifacts/ide-editing-tests.xml`.
- Нові регресії: `test_editor_syntax.py`, `test_code_editor_editing_qt.py`;
  розширено `test_metascript_highlighter.py`. Клавіші перевіряються через QTest,
  а незмінність DSL tokens і string values - через compiler Lexer.
- Offscreen Qt render UK/EN: `.artifacts/ide-editing-uk-en.png`.
  Для offscreen backend шрифти Consolas/Segoe UI завантажено явно лише в
  перевірочному процесі. Це не перевірка запущеного Configurator користувача.
- Синтетично: 155999 символів, 9000 рядків, вирівнювання за 0.050 с;
  ідемпотентність перевірено. Не є end-to-end latency benchmark.
- Робоча БД, Runtime та Client користувача не змінювалися/не перезапускалися.

## Сигнатури: перевірено 2026-09-21

- SignatureDocument використовує compiler Lexer та кеш контексту: nested/multiline
  arguments, strings/comments, BSL doubled quotes, UTF-16 позиції Qt.
- Локальні параметри, Val/Знач і defaults читаються з незбереженого буфера;
  затінення та неоднозначність блокують помилковий fallback на builtin.
- RPC виконується поза UI thread, максимум два одночасні запити; пізні відповіді
  не показуються в іншому контексті. Для великих буферів snapshot будується
  у фоновому потоці. Це не інкрементальна заміна всього semantic completion.
- Runtime зараз повертає імена параметрів експортів, але не їх defaults/Val;
  асистент не вигадує відсутню інформацію. Object methods без сигнатури не
  підміняються однойменною builtin-функцією.
- UK/EN popup відрендерено і переглянуто в `.artifacts/signature-help-uk.png`
  та `.artifacts/signature-help-en.png`; фокус залишається в редакторі.
- Розширений профільний regression-набір: **1038 passed, 1 skipped**,
  121.77 с, `.artifacts/runtime-client-ide-tests.xml`. Це не весь suite;
  zstandard відсутній у `.venv`, реальна копія БД перевірена іншим Python із zstd.

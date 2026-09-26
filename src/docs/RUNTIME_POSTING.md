# Runtime Posting

## Execution Contract

The client calls `document.post` or `document.unpost` through `RuntimeGateway`.
Only Runtime opens the transaction and accesses native `mpdb` tables. There is
no client-side fallback to independent table writes when the RPC is unavailable.

Posting operates on a **saved document**. The client asks the user to save dirty
forms first. Saving a form and its tabular parts is still a separate operation;
this implementation does not claim atomic SaveAndPost.

Runtime resolves the document from manifest metadata and reads exactly one
saved `cfg_modules` entry with matching `owner_guid` and `module_kind=ObjectModule`.
Source can be inline or in the referenced asset. A constructor draft in the
document payload is not executable source.

The operation:

1. Acquires the database transaction lock and reads the current native header.
2. Resolves the document's selected `register_records` to technical identities.
3. Runs the optional before hook, ObjectModule entry and optional after hook
   against snapshots and buffered movements, without giving scripts DB handles.
4. Validates all generated rows before applying writes.
5. Updates `_posted` and writes/deletes movements in the same transaction.
6. Returns success only after commit. Duplicate post requests cannot add duplicate
   movements; the second request finds the posted flag and fails.

The after hook sees the intended Posted value in its snapshot, but runs **before
commit**. It cannot query partially written movements. Hook failures abort the
operation rather than becoming ignored log messages.

Ordinary document-table RPCs cannot forge `_posted`/`_posting_registers`, change
an existing record's GUID, or edit/delete a posted document. Unpost it before
editing. These guards and their writes share the database lock to avoid a race
with posting. Successful posting/unposting also invalidates the native-row
projection cache, so subsequent client reads do not reuse the old posted state.

## Supported Script Surface

- UK `ОбробкаПроведення(Відмова, РежимПроведення)` or EN
  `Posting(Cancel, PostingMode)`. Imported `ОбработкаПроведения` is a compatibility
  entry, not a supported Russian UI locale.
- Optional `UndoPosting(Cancel)` / `ОбробкаСкасуванняПроведення(Відмова)`.
- Cancellation is a Boolean output parameter. Setting it to true aborts.
- `ThisObject`/`Object` and UK/import aliases expose a read-only header snapshot.
  Header fields and tabular parts also have direct technical names in context.
- Tabular rows are read for this document's GUID only. They support `For Each`
  iteration and named field reads.
- `Movements` / `Рухи` exposes selected registers by technical/source/localized
  names, never synonyms. Ambiguous aliases fail.
- Record sets support `Write` / `Записувати`, `Add()` / `Додати()` and `Count()`.
- Movement fields must exist in the native register schema. Common aliases are
  `Period` / `Період`, `RecordType` / `ВидРуху` and `Active` / `Активність`.
- Accumulation movements require an explicit Receipt/Expense direction. Values
  are checked against primitive schema types; numbers are not silently parsed
  from UI strings, and required fields cannot be missing.
- Native information and accumulation registers are supported. Each movement is
  stamped by Runtime with its recorder, line number and unique record GUID.
- Script helpers support reference parameters, including variables, properties
  and indexed elements. Nested cancellation propagates to the posting entry.
  Explicit `Val`/`Знач` isolates parameter reassignment; it does not deep-copy
  mutable objects. Expressions and host/Python calls receive evaluated values.
  Execution remains bounded by instruction, call-depth and movement-row limits.
- Source field names resolve to physical schema fields through explicit manifest
  metadata. Synonyms never determine bindings. Ambiguous aliases or missing
  native fields fail instead of silently writing to another field.

## Field Mapping Constructor

In Configurator, open a document's **Movements** page, select registers, then
choose **Movement field mappings** (`Зіставлення полів рухів`).

1. Select each register on the left.
2. Choose one movement from the header, or one movement per row of a tabular part.
3. Explicitly select Receipt/Expense for accumulation registers.
4. Map register fields to compatible document/row fields. Required fields have
   an asterisk; missing or incompatible bindings disable confirmation.
5. Review the UK/EN source preview and confirm the draft. Replacing a changed
   preview requires confirmation. Use the existing Insert into ObjectModule
   action, then save the module separately.

Plans are persisted as versioned `posting_mappings` metadata with selected
registers, sources, directions and field bindings. Changing/removing fields or
registers requires revalidation before generation/insertion. Cancel does not
change the original plan. An existing handler is not overwritten by insertion.

The constructor does not infer amounts, direction, filters, aggregation or tax
rules. It generates explicit assignments and loops, not a complete business
algorithm. Calculations and conditional logic can be added in the module editor.
An empty tabular source still follows the Runtime zero-movement restriction.

## Minimal Example

Prerequisites: document `Invoice` with numeric field `Amount`, selected register
`AccumulationRegister.Stock`, deployed native data tables, and register resource
`Amount`. This sample records an explicitly chosen expense, not an inferred
business rule. Save it in the document's **ObjectModule**, then save a document
record before invoking Post.

```text
Procedure Posting(Cancel, PostingMode)
    Movements.Stock.Write = True;
    Movement = Movements.Stock.Add();
    Movement.RecordType = AccumulationRecordType.Expense;
    Movement.Amount = ThisObject.Amount;
EndProcedure
```

Equivalent UK syntax, retaining the same technical register/resource names:

```text
Процедура ОбробкаПроведення(Відмова, РежимПроведення)
    Рухи.Stock.Записувати = Істина;
    Рух = Рухи.Stock.Додати();
    Рух.ВидРуху = ВидРухуНакопичення.Витрата;
    Рух.Amount = Amount;
КінецьПроцедури
```

The configurator's generated flags-only starter is deliberately rejected until
actual rows and field assignments are added. An enabled empty record set or a
document with selected registers but no generated movements cannot silently
become posted. Explicit zero-movement posting policies are not implemented yet.

## Limits And Safety

- This is not full 1C execution compatibility. Queries, live catalog APIs,
  implicit global-module calls and accounting/calculation register semantics
  remain unsupported in this posting context.
  They must be implemented explicitly, not replaced with guessed movements.
- Reference bindings never bypass snapshot protection. Attempting to mutate
  `ThisObject` through a helper parameter fails, while movement buffers remain
  writable. Built-in/host APIs with output parameters need their own explicit
  adapter; this change implements script-to-script reference passing.
- Imported virtual data is not materialized by Post. Native writable headers and
  register tables must exist; missing data produces an error without partial work.
- Successful posting saves `_posting_registers` GUIDs in the header. Unposting
  also cleans these registers if selection later changes. Legacy posted documents
  without this inventory require validation/migration before unposting.
- Existing handlers are never generated or overwritten by Runtime.
- UI actions do not close the form after a failed SaveAndClose/PostAndClose.
- Normal transaction failures are tested for rollback, including reopening the
  database. A transport failure is not proof of rollback: if a response is lost
  after commit, reload the saved document state before deciding what to do next.

## Common Modules

Posting and its before/after hooks can call exported functions/procedures of
saved common modules. The manifest owner must explicitly have `server: true`
and exactly one saved `Module` artifact. Client-only modules and missing server
metadata are rejected, not assumed safe. This can reveal incomplete imports;
correct their metadata instead of disabling the check.

Resolution uses technical identity only: manifest name, Source Name,
metadata reference, localized names and explicit current/legacy code references.
Synonyms, UI titles, transliteration guesses and fuzzy matches are not callable
identities. Both `Business.Fill(...)` and `CommonModule.Business.Fill(...)` work;
the UK namespace is `ЗагальнийМодуль`. Exports are matched case-insensitively.
Missing/ambiguous modules, missing exports and invalid argument counts fail the
operation. Defaults currently must be literals.

For example, replace the Amount assignment in the example above with
`Business.Fill(Movement, ThisObject, Cancel);` and save this server common module:

```text
Procedure Fill(Movement, Val Document, Cancel) Export
    Movement.Amount = Document.Amount;
    If Movement.Amount < 0 Then
        Cancel = True;
    EndIf;
EndProcedure
```

Reference arguments remain live across module boundaries; changing Cancel can
abort the document transaction. Document snapshots remain read-only, including
when one of their fields is passed as an output argument. Common modules have
no implicit document globals or live DB handles: pass snapshots and movement
buffers explicitly. Ordinary script exceptions can be handled with Try/Except;
metadata failures and execution limits cannot be caught to fake a successful post.

Sources load lazily by owner GUID. Aliases share one initialized module instance
across hooks and the object handler, but every post/unpost starts a fresh registry
and reads the latest saved source. Initializer cycles fail explicitly. The entire
operation shares 200,000 instructions, 64 call frames, 128 common modules and a
source budget of 2,000,000 characters per source / 8,000,000 total. Dynamic source
also consumes these budgets. These are execution bounds, not a general sandbox
or a wall-clock deadline for host functions.

`#Region` is supported; server/server-no-context annotations are supported on
executed procedures, but client-only and other annotations are rejected. Missing
platform APIs are not stubbed. The tolerant client module registry is unchanged.

## Conditional Compilation

ObjectModule, common modules, before/after hooks and dynamic `Do`/`Виконати`
source are preprocessed before posting compilation. Supported directives are
`#If`, `#ElsIf` (also `#ElseIf`), `#Else`, `#EndIf`, `#Region`, `#EndRegion`, with
UK equivalents and legacy RU spellings in the internal import profile. This
does not add a Russian UI locale. Conditions support parentheses, `Not`, `And`,
`Or` (in that precedence order), named context symbols and Boolean literals.

Runtime posting always selects the server context: `Server` and `AtServer`
(including UK/import aliases) are true. Client, thin/web/thick client, external
connection and mobile contexts are false. A local mpdb file does not turn Runtime
into a 1C thick client or enable both server and client branches. Script variables
named Server/Client cannot change compilation context. The server/client symbol
contract follows the [1C preprocessor documentation](https://1c-dn.com/library/preprocessor_instructions/);
UK aliases and Boolean literals are explicit MetaPlatform extensions.

```text
#If Client Then
    // Client-only declarations are not compiled for posting.
#ElsIf Server And Not ExternalConnection Then
Procedure Posting(Cancel, PostingMode)
    Movements.Stock.Write = True;
    Movement = Movements.Stock.Add();
    Movement.RecordType = AccumulationRecordType.Expense;
    Movement.Amount = ThisObject.Amount;
EndProcedure
#EndIf
```

Only the first matching branch is selected; an inactive outer branch cannot
activate an inner branch. Inactive declarations/exports and unsupported body
syntax are excluded before parsing. Strings and comments are recognized by the
shared lexer, so directive-like text inside them is data, not a directive.

Preprocessing masks inactive tokens, directives and comments in memory while
preserving source length and line/column offsets, including CRLF. Saved source
and assets are never rewritten. Dynamic execution uses the prepared module, not
the unprocessed original string; its frames have a distinct `:execute` identity
while retaining live output-parameter bindings and the shared posting budget.

Unknown symbols, unknown directives, `#Use`, extension directives and malformed
or unbalanced directive blocks fail the operation, even in excluded branches.
They are not treated as false or as harmless comments. Directives must start a
physical source line, with optional indentation. Conditions are single-line;
comments may span lines. Strings and block comments must be lexically complete
throughout the source, including inactive branches. Conditional/region nesting
is limited to 128 levels. This is a defined subset, not full 1C preprocessing.

The general parser still does not select a target automatically, and the client
module registry is not switched to this server-only context. The editor keeps
the complete source visible. `#ElsIf`/UK directives are highlighted as directives,
not comments; inactive-code dimming and context-aware IDE diagnostics are separate
future work.

## Verification

`src/tests/test_runtime_posting.py` uses disposable file-backed databases, not the
user's live database. It includes UK/EN execution, tabular-row isolation, actual
HTTP/gateway round trips, cancellation, incomplete metadata, source assets,
concurrent requests, injected insert/delete failures and reopen-time checks.
It also checks document-table mutation guards and native-row cache invalidation.

`test_posting_mapping*.py` covers metadata validation, Qt selection, cancellation,
draft restoration, source/storage aliases, and a dialog-to-HTTP round trip that
saves metadata/module text, posts and unposts a temporary native document.
`test_dsl_byref.py` covers reference aliasing, Val, recursion, single evaluation,
debugger snapshots and exception handling inside loops. The Try/Except compiler
stores the actual handler address; the VM preserves the surrounding stack when
unwinding a caught exception.
Break/Continue unwind exited Try handlers without removing surrounding ones;
counted-loop Continue reaches the increment and nested ForEach Break drops only
its own iterator.

`test_posting_modules.py` checks technical aliases, exports, server flags, nested
UK calls, output arguments, rollback, shared budgets, initializer cycles, lazy
source/asset loading and per-operation state. A real HTTP round trip saves a
common module twice and verifies that the next posting uses each saved revision.

`test_dsl_preprocessor.py` covers branch selection, Boolean precedence, nested
conditions, UK/EN/import spellings, strings/comments, exact offsets, malformed
directives and large non-recursive comment/expression runs.
`test_posting_preprocessor.py` checks saved sources over HTTP, inactive exports,
lazy module loading, hooks, unposting, dynamic reference cancellation, atomic
failure, shared limits and original/dynamic diagnostic locations.

`src/tests/test_mpdb_update.py` verifies `Table.update_tx`, stable rowids and index
rollback across multiple tables. Its current contract permits updating committed
rows before other writes to the same table; repeated pending-table updates are
rejected rather than using stale locators.

Restart Runtime and the client together to use the new RPCs. Do not restart a
session with unsaved work automatically.

---
keyflow_id: sys_kmp_node_room_kmp
status: review
type: ai-generated
use_when: Adding or changing a Room database, entity, DAO, migration, database file location or SQLite driver in a Kotlin Multiplatform module, including desktop JVM targets.
skip_when: The change uses another store (DataStore, files, a server) and touches no Room schema, DAO or database setup.
verified_by:
  - platforms/kmp/nodes/desktop-review.md
---

# KMP Room

Room runs in common code on Android, iOS and JVM desktop with a bundled
SQLite driver. Persistence stays a data-layer detail.

## Rules

- Database, entities and DAOs live in the data module and stay `internal` or
  otherwise unexported. Repositories map rows to domain models; feature code
  and `UiState` never see an entity or DAO.
- Build the database through a platform builder function in the data module:
  `Room.databaseBuilder<Db>(name = path)` with
  `setDriver(BundledSQLiteDriver())` and
  `setQueryCoroutineContext(Dispatchers.IO)`. Expose a factory, not the
  builder, to the composition root.
- Desktop database files go under the app's per-user data directory
  (for example `~/Library/Application Support/<App>` on macOS, `%APPDATA%` on
  Windows, `$XDG_DATA_HOME` on Linux), resolved by one platform adapter. Never
  write next to the executable or in the working directory.
- Declare the Room KSP compiler for each target that compiles the database
  (for example `kspDesktop`, `kspAndroid`, `kspIosArm64`) and set the Room
  Gradle `schemaDirectory`; commit exported schema JSON.
- Every schema change bumps the version and adds a migration or an
  `@AutoMigration` with a spec; destructive fallback is allowed only for
  caches the product can rebuild, and is named as such.
- DAO functions are `suspend` or return `Flow`. Transactions that span DAOs
  use `useWriterConnection { it.immediateTransaction { ... } }` or
  `@Transaction` methods, not ad-hoc locking.
- One database instance per file per process, owned by the app scope and
  closed on quit.

## Do Not

- Do not open the database on the Swing or main thread or in composition.
- Do not add `allowMainThreadQueries` or blocking DAO calls to make a
  desktop call site compile.
- Do not change an exported schema JSON by hand.

## Verification

- Migration test from each previous exported schema version to the new one
  (Room's migration test helper or an equivalent JVM test against real
  SQLite).
- Repository tests against an in-memory database with the bundled driver.
- Launch the app with an existing database from the previous release and
  confirm data survives the upgrade.

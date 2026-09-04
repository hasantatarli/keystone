# Deployment Model

## Objective

Keystone components must be deployable and upgradeable without manual object-by-object repository changes.

## Current Model

Keystone uses migration-driven installation for the shared repository and database providers.

Core migrations and provider migrations have independent version sequences. This allows the Keystone platform to evolve without requiring every provider to be installed, while each provider can evolve its own repository structures independently.

The installer discovers migrations and collector definitions from the project structure, applies pending migrations, and registers collector metadata in the central repository.

## Migration Execution

A migration is considered installed only when both its database changes and successful migration-history record are committed.

Each migration therefore executes as one transaction:

- Apply the migration.
- Record successful execution.
- Commit both together.

If migration execution fails, its database changes are rolled back before the failure is recorded.

This prevents partially applied migrations from being mistaken for valid installations and avoids relying on broad `IF NOT EXISTS` behavior to hide inconsistent state.

## Provider Installation

Provider installation is driven by the providers actually required by the Keystone deployment.

A provider owns its database-specific repository migrations and collector definitions. Shared platform structures remain owned by the Keystone core.

The current PostgreSQL provider installs its telemetry repository structures and registers PostgreSQL collectors through this model.

## Deployment Boundaries

The installer is responsible for repository evolution and collector registration. Runtime scheduling, collector execution, credential management, and operational recovery belong to the runtime platform rather than being embedded into migration scripts.

Additional deployment automation can be added as the product matures without changing migration ownership.

## Principles

- Repeatable installation and upgrade
- Migration history as the source of installed version state
- Atomic migration execution
- Separate core and provider evolution
- No silent partial installation
- Minimal customer-specific manual database changes
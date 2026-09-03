## Objective

Keystone components must be deployable to customer environments without manual object-by-object installation.

## Decision

Each Keystone provider will include an idempotent installer that creates, validates, upgrades, and optionally removes all required components.

For the PostgreSQL telemetry capability, the installer is responsible for:

- Repository schema and tables
- Collector functions
- Service account permissions
- Scheduling
- Retention configuration
- Initial execution
- Installation validation
- Upgrade handling
- Uninstallation

## Principles

- One-command deployment
- Idempotent execution
- Version-aware upgrades
- Minimal privileges
- Clear validation output
- Reversible installation
- No manual customer-specific steps unless explicitly required
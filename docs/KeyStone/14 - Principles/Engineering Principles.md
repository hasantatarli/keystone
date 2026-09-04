# Keystone Engineering Principles

These principles guide architecture and implementation decisions. They are intentionally short and should remain stable even as individual technologies change.

## 1. Facts Before Interpretation

Collectors gather observable facts. Findings, recommendations, and actions are separate layers built on top of that evidence.

## 2. Metadata Over Hardcoded Behavior

Execution behavior should be driven by stable metadata and declared scope rather than growing collector-specific branching inside the core.

## 3. Stable Identity Over Environment IDs

Portable identifiers such as collector keys define logical identity. Database-generated numeric IDs are implementation details of a particular repository.

## 4. Provider Knowledge Stays Provider-Specific

The core owns shared orchestration concepts. Database-engine knowledge, telemetry semantics, and provider repository structures remain isolated from generic platform logic.

## 5. Preserve Failure Visibility

Partial execution, failed collection, and recovery state must be represented explicitly. Keystone should not convert incomplete work into apparent success.

## 6. One Owner for a Transaction

A logical operation should have a clear transaction owner. Lower-level helpers should not independently commit work that belongs to a larger atomic operation.

## 7. Secure Secrets Separately from Data

Recoverable credentials must be protected independently from repository data. Possession of a repository backup alone should not be sufficient to recover stored secrets.

## 8. Build from Real Engineering Needs

Prefer simple implementations that solve proven use cases. Introduce new abstractions when repeated engineering needs justify them, not merely because they may be useful someday.
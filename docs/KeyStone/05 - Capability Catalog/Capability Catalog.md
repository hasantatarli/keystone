# Capability Catalog

**Status:** Draft  
**Last Updated:** 2026-09-19

## Capability Model

Customer-facing capabilities compose Keystone technical modules; they are not themselves execution-layer modules.

The same collectors, evidence repository, Engineering Intelligence, Keystone Dictionary, and Presentation capabilities may support multiple services such as Health Assessment, Performance Investigation, Upgrade Readiness, HA/DR Assessment, or Security Assessment.

---

# Assessment

## Health Assessment

### Purpose

Provide a standardized engineering assessment of a database environment and make both identified risks and verified healthy areas visible.

Health Assessment can operate as a one-off Snapshot Assessment, a bounded Temporary Observation, or as part of Continuous Engineering.

### Assessment Model

Each defined check results in:

- **HEALTHY**
- **ATTENTION_REQUIRED**
- **NOT_ASSESSED / INSUFFICIENT_EVIDENCE**

Attention-requiring results may produce Findings. Findings may then be evaluated through RCA using supporting, contradicting, and missing evidence.

Health Assessment may perform meaningful RCA when the required evidence is available, but a snapshot engagement does not guarantee root-cause identification for every condition. Evidence limitations must remain explicit.

### Typical Coverage

- Environment inventory
- Architecture and configuration
- Availability / HA
- Backup and recovery
- Security
- Capacity
- Maintenance
- Transactions
- Connections
- Locking and concurrency
- Table and index health
- Workload / performance indicators
- Historical change and trends when historical evidence is available

### Typical Outputs

- Assessment coverage
- Environment and architecture summary
- Healthy assessment areas
- Findings and risk summary
- RCA where evidence permits
- Missing evidence / assessment limitations
- Recommendations
- Engineering roadmap

### Continuous Engineering

Continuous Engineering applies the same assessment and intelligence model to recurring evidence.

Compared with a point-in-time Health Assessment, it can provide stronger trend analysis, change detection, historical correlation, recurring Finding history, and richer RCA evidence.

---

# Performance Engineering

## Performance Investigation

### Purpose

Investigate a specific performance problem and identify or narrow its root cause through detailed engineering analysis.

Performance Investigation is problem-driven. It may require deeper or more targeted evidence than a general Health Assessment.

### Typical Activities

- Problem scope and timeline identification
- Database configuration analysis
- Query and execution plan analysis
- Index analysis
- Lock, wait, and concurrency analysis
- WAL, checkpoint, and vacuum analysis
- CPU, memory, disk, and network analysis
- Application and database interaction analysis
- Historical metric and workload correlation
- Hypothesis evaluation and evidence-gap identification

### Delivery Model

The duration of a Performance Investigation cannot always be determined in advance. A problem may be identified quickly or may require extended observation and analysis.

The engagement may end with:

- Root cause identification and recommendations
- A narrowed set of supported hypotheses and explicit missing evidence
- A technical investigation report
- Remediation performed separately by DataWiser
- Evidence and guidance for another responsible team when the issue is outside the database layer

---

# Future Assessment Profiles

The shared Keystone assessment model can support additional customer-facing profiles without creating separate engineering engines.

Candidate profiles include:

- Upgrade Readiness Assessment
- HA/DR Assessment
- Security Assessment
- Performance Baseline
- Capacity Assessment

Their scope will be defined from engineering checks, Findings/RCA, and required evidence rather than from arbitrary collector bundles.

---

# Automation

Automate repeatable evidence collection, assessment execution, and engineering workflows.

# Operations

Standardize operational processes and runbooks. State-changing execution remains behind the Keystone human decision boundary.

# Knowledge

Capture and preserve engineering expertise through the Keystone Dictionary, provider-specific engineering knowledge, reusable assessment definitions, Findings, RCA models, Recommendations, and related definitions.

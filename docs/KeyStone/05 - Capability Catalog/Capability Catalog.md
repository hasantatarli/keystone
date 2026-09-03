**Status:** Draft

---

# Engineering Domains

## Assessment
Purpose:
Provide a fast, standardized engineering assessment of a database environment.

Assessment identifies engineering risks.

Assessment does NOT perform deep root cause analysis.

Typical outputs:
- Inventory
- Architecture Review
- Configuration Review
- Availability Review
- Backup Review
- Security Review
- Capacity Indicators
- Health Score
- Risk Summary
- Recommendations

## Health Assessment
### Purpose
Provide a standardized overview of the general health, risks, and improvement areas of a database environment.

Health Assessment may review high-level performance indicators such as long-running queries, index usage, bloat, resource utilization, locking, and configuration risks.

Its purpose is to identify potential issues and areas requiring attention.

It does not guarantee root cause identification for a specific performance problem.
### Typical Outputs
- Environment inventory
- Architecture and configuration review
- Health and risk findings
- High-level performance indicators
- Capacity and availability observations
- Backup and recovery observations
- Prioritized recommendations
- Areas requiring deeper investigation

---
# Performance Engineering

## Performance Investigation
### Purpose

Investigate a specific performance problem and identify its root cause through detailed engineering analysis.

Unlike a Health Assessment, Performance Investigation is problem-driven and may require deep analysis across database, infrastructure, and application layers.

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

### Delivery Model

The duration of a Performance Investigation cannot always be determined in advance. A problem may be identified quickly or may require several days of analysis.

The engagement may end with:

- Root cause identification and recommendations
- A technical investigation report
- Remediation performed by DataWiser
- Evidence and guidance for another responsible team when the issue is outside the database layer

## Automation

Automate repeatable engineering activities.

---

## Operations

Standardize operational processes and runbooks.

---

## Knowledge

Capture and preserve engineering expertise.
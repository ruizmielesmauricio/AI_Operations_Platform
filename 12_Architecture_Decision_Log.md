# 12_Architecture_Decision_Log.md

**Version:** 1.0
**Status:** Accepted
**Phase:** Company Governance
**Author:** Founder & CTO
**Last Updated:** TBD

---

# Document Contract

## Purpose

The Decision Register records all significant business, product, architecture, and engineering decisions made throughout the life of the company.

Each decision documents what was decided, why it was chosen, and its current status.

The register provides historical context and ensures future decisions remain consistent with the Company's Constitution.

---

## Audience

* Founder
* CTO
* Product Team
* Engineering Team
* Future Employees
* Investors

---

# Decision Status

| Status      | Meaning                      |
| ----------- | ---------------------------- |
| Proposed    | Under discussion             |
| Draft       | Being documented             |
| Accepted    | Official company decision    |
| Implemented | Implemented in production    |
| Superseded  | Replaced by a newer decision |
| Rejected    | Considered but not adopted   |
| Deprecated  | No longer recommended        |

---

# Business Decisions (BD)

## BD-001

**Decision**

Target independent bike shops as the first commercial vertical.

**Reason**

Bike shops have inventory, workshop operations, suppliers and seasonal demand, making them an excellent first market while remaining small enough to benefit from affordable AI.

**Status**

Accepted

---

## BD-002

**Decision**

Build a reusable platform rather than a bike-shop-only application.

**Reason**

The architecture should support future expansion into other retail sectors without major redesign while maintaining complete focus on bike shops during the initial commercial phase.

**Status**

Accepted

---

## BD-003

**Decision**

Company tagline.

**Decision**

> AI: Helping small businesses make enterprise decisions.

**Status**

Accepted

---

# Product Decisions (PD)

## PD-001

**Decision**

Organise the platform around five operational domains.

**Domains**

* Retail Operations
* Workshop Operations
* Financial Performance
* Business Knowledge
* AI Decision Support

**Status**

Accepted

---

## PD-002

**Decision**

Workshop Operations is part of Version 1.

**Reason**

Workshop revenue is a significant component of many bike shops and must be analysed alongside retail operations.

**Status**

Accepted

---

## PD-003

**Decision**

Every feature must improve at least one of the following:

* Save time
* Save money
* Reduce operational risk
* Improve business decisions

**Status**

Accepted

---

# Architecture Decisions (ADR)

## ADR-001

**Decision**

Adopt an AI-agnostic architecture.

**Reason**

Avoid vendor lock-in, improve flexibility, optimise costs and allow future migration between AI providers.

**Status**

Accepted

---

## ADR-002

**Decision**

Business Logic First.

**Reason**

Business calculations, forecasting and machine learning produce recommendations.

Large Language Models explain recommendations rather than generating business logic.

**Status**

Accepted

---

## ADR-003

**Decision**

Separate the platform into specialised engines.

**Components**

* Database Engine
* Calculation Engine
* Machine Learning Engine
* AI Engine

**Status**

Accepted

---

# Engineering Decisions (ED)

## ED-001

**Decision**

Documentation before implementation.

**Reason**

Business requirements and architecture should be fully understood before production development begins.

**Status**

Accepted

---

## ED-002

**Decision**

Every design document follows the company documentation standard.

**Reason**

Consistency improves maintainability and collaboration.

**Status**

Accepted

---

## ED-003

**Decision**

Every document begins with a Document Contract.

**Reason**

Clearly defines purpose, audience, scope and related documents while preventing overlap.

**Status**

Accepted

---

## ED-004

**Decision**

One document, one responsibility.

**Reason**

Documentation should remain modular, focused and easy to maintain.

**Status**

Accepted

---

# Future Decisions

Additional decisions will be added as the project evolves.


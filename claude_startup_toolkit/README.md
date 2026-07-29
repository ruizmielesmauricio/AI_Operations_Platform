# Claude Code Startup Engineering Toolkit

This repository package contains **29 focused Claude Code Skills**, reviewer subagents, templates, standards, and a root `CLAUDE.md` for building a secure, modular, attractive, low-cost, multi-business SaaS.

## What is included

### Architecture and product
- `startup-product-architect`
- `saas-database-architect`
- `api-contract-engineer`
- `documentation-adr-maintainer`

### Database and platform
- `postgresql-engineer`
- `supabase-engineer`
- `neon-engineer`
- `data-ingestion-quality`

### Application engineering
- `nodejs-backend-engineer`
- `python-data-engineer`
- `frontend-application-architect`
- `html-css-accessibility`
- `testing-quality-engineer`
- `devops-deployment-engineer`
- `observability-reliability`
- `performance-cost-optimizer`

### Product design and intelligence
- `ui-ux-design-system`
- `analytics-bi-designer`
- `machine-learning-engineer`
- `ai-integration-engineer`
- `website-growth-seo`

### Payments, finance, compliance, and trust
- `stripe-payments-engineer`
- `financial-modeling-and-controls`
- `ireland-company-registration`
- `gdpr-privacy-engineer`
- `security-architect`
- `identity-access-engineer`
- `email-validation-deliverability`
- `legal-commercial-review-coordinator`

## Installation into your existing GitHub repository

1. Download and unzip this package.
2. Copy these items into the root of your SaaS repository:
   - `.claude/`
   - `docs/`
   - `scripts/`
   - `README_CLAUDE_TOOLKIT.md` (rename this package README if desired)
3. **Merge** the supplied `CLAUDE.md` with your existing root `CLAUDE.md`; do not overwrite accepted project facts.
4. Commit the files:
   ```bash
   git add .claude CLAUDE.md docs scripts
   git commit -m "Add Claude startup engineering toolkit"
   git push
   ```
5. Open a terminal in the repository and run:
   ```bash
   claude
   ```

Claude Code reads the root `CLAUDE.md` and discovers project Skills from `.claude/skills/`.

## Using a Skill explicitly

```text
/saas-database-architect design the portable multi-tenant platform foundation.
Read all accepted architecture decisions first. Do not edit files until you
have presented the proposed schema, tenant model, ERD, security model, and
migration plan.
```

```text
/ui-ux-design-system review the onboarding and first-data-upload journey.
Create responsive desktop and mobile states, accessible interactions,
empty/loading/error states, and a design-token proposal.
```

```text
/stripe-payments-engineer design the €79 monthly subscription lifecycle.
Include Checkout, Customer Portal, verified webhooks, local entitlement
projection, trial and failed-payment behaviour, reconciliation, and tests.
```

## Letting Claude select a Skill automatically

A natural prompt can trigger a Skill based on its description:

```text
Review our Supabase RLS policies for cross-tenant access and create pgTAP tests.
```

For major architecture or security work, explicit slash invocation is clearer.

## Recommended staged use

1. `startup-product-architect`
2. `ui-ux-design-system`
3. `saas-database-architect`
4. provider Skill: `supabase-engineer` or `neon-engineer`
5. backend/frontend implementation Skills
6. `testing-quality-engineer`
7. reviewer subagents
8. documentation and ADR update
9. deployment and observability review

## Important

Skills guide Claude; they do not guarantee correctness or legal compliance. Review migrations, security policies, financial calculations, payment flows, and legal/regulatory work with qualified humans before production.

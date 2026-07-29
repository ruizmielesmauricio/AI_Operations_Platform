/
├── README.md                      # Project intro, quick start, links to docs
├── CLAUDE.md                      # ← Claude project instructions (see below)
├── LICENSE
├── .gitignore
├── .env.example                   # Template env vars, NEVER real secrets
├── docker-compose.yml
│
├── docs/
│   ├── README.md                  # Doc index: which set is which, reading order
│   │
│   ├── governance/                # Strategy & company-level (your governance set)
│   │   ├── 00_Company_Constitution.md
│   │   ├── 01_Project_Vision.md
│   │   ├── 02_Operational_Domains.md
│   │   ├── 03_System_Architecture.md
│   │   ├── 04_Technology_Stack.md
│   │   ├── 05_AI_Architecture.md
│   │   ├── 06_Database_Design.md
│   │   ├── 07_Deployment_Guide.md
│   │   ├── 08_Cost_Analysis.md
│   │   ├── 09_Business_Model.md
│   │   ├── 10_Product_Requirements.md
│   │   ├── 11_Development_Roadmap.md
│   │   ├── 12_Architecture_Decision_Log.md
│   │   ├── 13_Branding_Strategy.md
│   │   └── 15_Customer_Discovery.md
│   │
│   ├── technical/                 # Implementation-level (your detailed set)
│   │   ├── 00_Project_Overview.md
│   │   ├── 01_Product_Vision.md
│   │   ├── 02_Business_Model.md
│   │   ├── 03_Architecture.md
│   │   ├── 04_Database.md
│   │   ├── 05_AI_Strategy.md
│   │   ├── 06_Development_Rules.md
│   │   ├── 07_Cost_Strategy.md
│   │   ├── 08_Tech_Stack.md
│   │   ├── 09_Product_Modules.md
│   │   ├── 10_Roadmap.md
│   │   ├── 11_ADRs.md
│   │   └── 12_Glossary.md
│   │
│   ├── decisions/                 # One file per ADR/BD/PD/ED
│   │   ├── ADR-001-shared-multitenant-platform.md
│   │   ├── ADR-004-neon-postgres-supabase-auth.md
│   │   ├── ADR-013-openrouter-ai-routing.md
│   │   └── ...
│   │
│   ├── business/                  # Commercial material
│   │   ├── onepager-internal.md
│   │   ├── onepager-customer-pitch.md
│   │   ├── competitor-research.md
│   │   └── interviews/            # One file per bike shop interview
│   │       └── 2026-08-shop-name.md
│   │
│   ├── templates/
│   │   ├── document_template.md
│   │   ├── adr_template.md
│   │   └── interview_template.md
│   │
│   └── diagrams/                  # Exported images, .drawio, mermaid sources
│
├── backend/
│   ├── app/
│   │   ├── api/                   # FastAPI routes (thin)
│   │   ├── application/           # Application services
│   │   ├── domain/                # Business logic, formulas
│   │   ├── repositories/          # DB access
│   │   ├── models/                # SQLAlchemy models
│   │   ├── schemas/               # Pydantic schemas
│   │   ├── analytics/             # Calculation engine
│   │   ├── forecasting/           # Forecast models
│   │   ├── ai/                    # AI Provider Gateway (OpenRouter lives here ONLY)
│   │   ├── imports/               # Upload, mapping, validation, normalisation
│   │   ├── templates/             # Business template definitions (bike_shop, cafe, …)
│   │   ├── billing/               # Stripe integration
│   │   ├── jobs/                  # Background workers
│   │   ├── security/              # Auth, tenant scoping
│   │   └── settings/
│   ├── migrations/                # Alembic
│   ├── tests/
│   │   ├── unit/                  # Formula tests
│   │   ├── integration/
│   │   └── tenant_isolation/      # Critical — keep separate and visible
│   ├── pyproject.toml
│   └── Dockerfile
│
├── frontend/
│   ├── app/                       # Next.js routes
│   ├── components/
│   ├── lib/
│   │   └── api/                   # API client layer (all backend calls go here)
│   ├── types/                     # Generated from backend schemas where possible
│   ├── public/
│   ├── package.json
│   └── Dockerfile
│
├── infrastructure/
│   ├── docker/
│   ├── coolify/                   # Deployment config
│   └── monitoring/                # Uptime Kuma config, alert rules
│
├── scripts/
│   ├── seed_dev_data.py
│   ├── generate_import_template.py
│   └── backup_check.sh
│
└── .github/
    ├── workflows/
    │   ├── test.yml
    │   ├── build.yml
    │   └── deploy.yml
    ├── ISSUE_TEMPLATE/
    └── pull_request_template.md
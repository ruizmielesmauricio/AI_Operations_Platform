"""Customer help content and human support handoff (PR-5.7, E26/E27).

- ``content/*.md``: the approved help knowledge base — versioned Markdown
  articles with front-matter, reviewed like any other source file.
- ``knowledge_base``: loads the articles and retrieves passages with a
  deterministic lexical ranker (no AI, no embeddings, no network).
- ``service``: the "Contact support" handoff — a tenant-scoped
  SupportRequest row, an audit event and an owner-visible notification.

The AI support lane itself (classify -> retrieve -> explain -> verify)
lives in ``app/ai/support_lane.py`` because it calls the AI provider,
which only ``app/ai/`` may do (CLAUDE.md).
"""

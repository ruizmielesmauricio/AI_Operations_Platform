"""The AI Provider Gateway — the ONLY place in the codebase allowed to import
an AI provider SDK (OpenRouter), per CLAUDE.md's non-negotiable and
05_AI_Architecture.md. Business modules never call a model directly; they
call this gateway with structured findings, never raw customer data, and it
returns plain-language explanations. AI never calculates, aggregates,
validates, or invents a number (PR-5.3).
"""

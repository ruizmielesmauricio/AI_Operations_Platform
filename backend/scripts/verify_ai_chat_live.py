"""Manual, one-off live verification for Stage E19-E24's AI chat — not a
pytest test (the automated suite mocks app.ai.client.chat_completion
throughout, per the plan's stated scope), and not wired into CI. Run this
once a real OPENROUTER_API_KEY is set in backend/.env, against a business
that already has some imported sales history, to confirm the whole
classify -> fetch -> explain -> guardrail pipeline works against the real
OpenRouter API end-to-end.

Usage (from backend/, with the venv/deps installed and DATABASE_URL
pointed at a real Postgres that has at least one business):

    python scripts/verify_ai_chat_live.py <business_id> "How is my revenue doing?"

Prints the classified intent, whether the guardrail accepted the answer,
and the answer text itself. A network/auth error here means the
OpenRouter key or model in Settings needs attention before relying on
the /chat route live.
"""

import sys
import uuid

from app.ai.service import answer_question
from app.models.base import SessionLocal


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <business_id> <question>", file=sys.stderr)
        raise SystemExit(1)

    business_id = uuid.UUID(sys.argv[1])
    question = sys.argv[2]

    with SessionLocal() as db:
        result = answer_question(db, business_id=business_id, user_id="manual-verification-script", question=question)

    print(f"intent:   {result.intent}")
    print(f"grounded: {result.grounded}")
    print(f"answer:   {result.answer}")


if __name__ == "__main__":
    main()

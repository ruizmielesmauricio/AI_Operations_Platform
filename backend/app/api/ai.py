from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.service import answer_question
from app.api.deps import get_db
from app.models.membership import Membership
from app.schemas.ai import ChatRequest, ChatResponse
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/ai", tags=["ai"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ChatResponse:
    # answer_question never raises for an AI-provider failure (PR-5.4 —
    # it catches AIProviderError internally and returns a friendly
    # fallback AnswerResult) — this route stays thin and always returns
    # 200 with a message the frontend can render directly.
    result = answer_question(
        db, business_id=membership.business_id, user_id=membership.user_id, question=body.question,
        previous_question=body.previous_question, previous_answer=body.previous_answer,
        previous_intent=body.previous_intent,
    )
    return ChatResponse(answer=result.answer, intent=result.intent, grounded=result.grounded, links=list(result.links))

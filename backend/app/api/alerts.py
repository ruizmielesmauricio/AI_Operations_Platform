from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.membership import Membership
from app.repositories.alert import AlertRepository
from app.schemas.alert import AlertOut
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    alerts = AlertRepository(db).list_active_for_business(membership.business_id)
    return [AlertOut.model_validate(a) for a in alerts]

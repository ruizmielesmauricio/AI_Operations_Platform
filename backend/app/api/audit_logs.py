from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.membership import Membership
from app.repositories.audit_log import AuditLogRepository
from app.schemas.audit_log import AuditLogOut
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    # get_current_membership already confirms real membership on
    # business_id (tenant-scoped, never trusts the URL alone) — the
    # owner-only check below is on top of that, since audit history is
    # more sensitive than the profile/business data every member can see.
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[AuditLogOut]:
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can view its audit history"
        )
    # A plain read — deliberately does not itself write an AuditLog row;
    # no existing policy in this codebase audits reads, only mutations.
    rows = AuditLogRepository(db).list_for_business(membership.business_id, limit=limit)
    return [AuditLogOut.model_validate(r) for r in rows]

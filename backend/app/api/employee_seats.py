from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.employee_seats import (
    AlreadyAMemberOrInvited,
    EmployeeSeatLimitReached,
    InvalidEmployeeRole,
    MAX_EMPLOYEE_SEATS_PER_BUSINESS,
    NoAccountForEmail,
    add_employee,
)
from app.billing.exceptions import EmployeeSeatPriceNotConfigured
from app.models.membership import Membership
from app.repositories.employee_seat import EmployeeSeatRepository
from app.schemas.employee_seat import EmployeeSeatCreate, EmployeeSeatCreateResponse, EmployeeSeatOut
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/employee-seats", tags=["employee-seats"])


@router.get("", response_model=list[EmployeeSeatOut])
def list_employee_seats(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[EmployeeSeatOut]:
    # Owner/admin-only, same as adding one — a pending invite's email is
    # sensitive enough (who's about to get access) that a regular staff
    # member shouldn't see it either.
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can view employee seats"
        )
    rows = EmployeeSeatRepository(db).list_for_business(membership.business_id)
    return [EmployeeSeatOut.model_validate(r) for r in rows]


@router.post("", response_model=EmployeeSeatCreateResponse, status_code=status.HTTP_201_CREATED)
def create_employee_seat(
    payload: EmployeeSeatCreate,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> EmployeeSeatCreateResponse:
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can add an employee"
        )
    try:
        seat, checkout_url = add_employee(
            db,
            business_id=membership.business_id,
            business_email=current_user.email,
            invited_by_user_id=current_user.id,
            first_name=payload.first_name,
            surname=payload.surname,
            email=payload.email,
            role=payload.role,
        )
    except InvalidEmployeeRole as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except EmployeeSeatLimitReached as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This shop already has {MAX_EMPLOYEE_SEATS_PER_BUSINESS} employee seats.",
        ) from exc
    except NoAccountForEmail as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No account found for {exc.email} — ask them to sign up first, then try again.",
        ) from exc
    except AlreadyAMemberOrInvited as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{exc.email} is already a member of this shop, or already has a pending invite.",
        ) from exc
    except EmployeeSeatPriceNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Employee seats aren't available yet — billing isn't fully configured.",
        ) from exc
    return EmployeeSeatCreateResponse(
        employee_seat=EmployeeSeatOut.model_validate(seat), checkout_url=checkout_url
    )

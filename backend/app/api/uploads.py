import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.imports import service
from app.imports.exceptions import (
    FileTooLarge,
    HeaderRowNotFound,
    InsufficientMapping,
    InvalidFieldMapping,
    UnsupportedEntityType,
    UnsupportedFileType,
    UploadNotReady,
)
from app.models.membership import Membership
from app.repositories.upload import UploadRepository
from app.schemas.import_mapping import (
    ConfirmMappingRequest,
    ConfirmMappingResponse,
    DetectMappingResponse,
)
from app.schemas.upload import UploadCreateRequest, UploadCreateResponse, UploadOut
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

# Tenant-scoped: business_id comes from the URL and is verified by
# get_current_membership (PR-6.1/6.2), never trusted from a request body.
router = APIRouter(prefix="/businesses/{business_id}/uploads", tags=["uploads"])


def _get_upload_or_404(db: Session, upload_id: uuid.UUID, business_id: uuid.UUID):
    upload = UploadRepository(db).get_for_business(upload_id, business_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
    return upload


@router.post("", response_model=UploadCreateResponse, status_code=status.HTTP_201_CREATED)
def request_upload(
    payload: UploadCreateRequest,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> UploadCreateResponse:
    try:
        upload, upload_url = service.create_upload(
            db,
            business_id=membership.business_id,
            filename=payload.filename,
            uploaded_by=current_user.id,
            entity_type=payload.entity_type,
        )
    except UnsupportedFileType as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UnsupportedEntityType as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UploadCreateResponse(id=upload.id, upload_url=upload_url)


@router.post("/{upload_id}/complete", response_model=UploadOut)
def complete_upload(
    upload_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> UploadOut:
    upload = _get_upload_or_404(db, upload_id, membership.business_id)
    upload = service.mark_uploaded(db, upload)
    return UploadOut.model_validate(upload)


@router.get("", response_model=list[UploadOut])
def list_uploads(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[UploadOut]:
    uploads = UploadRepository(db).list_for_business(membership.business_id)
    return [UploadOut.model_validate(u) for u in uploads]


@router.post("/{upload_id}/detect-mapping", response_model=DetectMappingResponse)
def detect_mapping(
    upload_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> DetectMappingResponse:
    upload = _get_upload_or_404(db, upload_id, membership.business_id)
    try:
        result = service.detect_mapping_for_upload(db, upload)
    except UploadNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HeaderRowNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not find a header row in this file",
        ) from exc
    except FileTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    return DetectMappingResponse(
        status=result.status,
        mapping_profile_id=result.mapping_profile_id,
        suggested_mapping=result.suggested_mapping,
        columns=result.columns,
        field_candidates=result.field_candidates,
        unmapped_columns=result.unmapped_columns,
    )


@router.post("/{upload_id}/confirm-mapping", response_model=ConfirmMappingResponse)
def confirm_mapping(
    upload_id: uuid.UUID,
    payload: ConfirmMappingRequest,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ConfirmMappingResponse:
    upload = _get_upload_or_404(db, upload_id, membership.business_id)
    try:
        record, mapping_profile_id = service.confirm_mapping(db, upload, payload.field_mapping)
    except UploadNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HeaderRowNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not find a header row in this file",
        ) from exc
    except FileTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except InvalidFieldMapping as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InsufficientMapping as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Not enough information to calculate sales — map a sale date and a price field",
        ) from exc
    return ConfirmMappingResponse(
        import_record_id=record.id, mapping_profile_id=mapping_profile_id, status=record.status
    )

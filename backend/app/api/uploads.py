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
    InvalidHeaderRowIndex,
    UnsupportedEntityType,
    UnsupportedFileType,
    UploadNotReady,
)
from app.models.import_record import ImportRecord
from app.models.membership import Membership
from app.models.upload import Upload
from app.imports.aliases import SUPPORTED_ENTITY_TYPES
from app.repositories.import_record import ImportRecordRepository
from app.repositories.upload import UploadRepository
from app.schemas.import_mapping import (
    ConfirmMappingRequest,
    ConfirmMappingResponse,
    DetectMappingRequest,
    DetectMappingResponse,
)
from app.schemas.upload import (
    ImportRecordSummary,
    UploadCreateRequest,
    UploadCreateResponse,
    UploadFreshnessEntry,
    UploadOut,
)
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

# Tenant-scoped: business_id comes from the URL and is verified by
# get_current_membership (PR-6.1/6.2), never trusted from a request body.
router = APIRouter(prefix="/businesses/{business_id}/uploads", tags=["uploads"])

_INSUFFICIENT_MAPPING_MESSAGES = {
    "sales": "Not enough information to calculate sales — map a sale date and a price field",
    "inventory": "Not enough information to record stock — map a product name or SKU, and a quantity",
    "purchases": (
        "Not enough information to record this restock — map a date, a product name or SKU, "
        "and a quantity received"
    ),
    "repairs": "Not enough information to record this repair — map a date, and a description, price, or labour cost",
}


def _get_upload_or_404(db: Session, upload_id: uuid.UUID, business_id: uuid.UUID):
    upload = UploadRepository(db).get_for_business(upload_id, business_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
    return upload


def _to_upload_out(upload: Upload, import_record: ImportRecord | None) -> UploadOut:
    return UploadOut(
        id=upload.id,
        original_filename=upload.original_filename,
        entity_type=upload.entity_type,
        status=upload.status,
        created_at=upload.created_at,
        import_record=ImportRecordSummary.model_validate(import_record) if import_record else None,
    )


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
    return _to_upload_out(upload, None)  # never has an import record yet — just uploaded


@router.get("", response_model=list[UploadOut])
def list_uploads(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[UploadOut]:
    uploads = UploadRepository(db).list_for_business(membership.business_id)
    records_by_upload = ImportRecordRepository(db).map_by_upload_id(membership.business_id)
    return [_to_upload_out(u, records_by_upload.get(u.id)) for u in uploads]


@router.get("/freshness", response_model=list[UploadFreshnessEntry])
def get_upload_freshness(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[UploadFreshnessEntry]:
    latest = ImportRecordRepository(db).latest_completed_by_entity_type(membership.business_id)
    return [
        UploadFreshnessEntry(entity_type=et, last_completed_at=latest.get(et))
        for et in SUPPORTED_ENTITY_TYPES
    ]


@router.post("/{upload_id}/detect-mapping", response_model=DetectMappingResponse)
def detect_mapping(
    upload_id: uuid.UUID,
    payload: DetectMappingRequest = DetectMappingRequest(),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> DetectMappingResponse:
    upload = _get_upload_or_404(db, upload_id, membership.business_id)
    try:
        result = service.detect_mapping_for_upload(db, upload, payload.header_row_index)
    except UploadNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HeaderRowNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not find a header row in this file",
        ) from exc
    except InvalidHeaderRowIndex as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except FileTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    return DetectMappingResponse(
        status=result.status,
        mapping_profile_id=result.mapping_profile_id,
        suggested_mapping=result.suggested_mapping,
        columns=result.columns,
        field_candidates=result.field_candidates,
        unmapped_columns=result.unmapped_columns,
        preview_rows=result.preview_rows,
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
        record, mapping_profile_id = service.confirm_mapping(
            db, upload, payload.field_mapping, payload.header_row_index
        )
    except UploadNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HeaderRowNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not find a header row in this file",
        ) from exc
    except InvalidHeaderRowIndex as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except FileTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except InvalidFieldMapping as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InsufficientMapping as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_INSUFFICIENT_MAPPING_MESSAGES.get(exc.entity_type, str(exc)),
        ) from exc
    return ConfirmMappingResponse(
        import_record_id=record.id, mapping_profile_id=mapping_profile_id, status=record.status
    )

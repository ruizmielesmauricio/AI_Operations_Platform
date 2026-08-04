import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.imports import importer
from app.imports.exceptions import (
    FileTooLarge,
    HeaderRowNotFound,
    ImportNotReversible,
    ImportRecordNotReady,
    ImportSupersededByLaterInventoryImport,
    MappedColumnMissing,
)
from app.models.membership import Membership
from app.repositories.import_record import ImportRecordRepository
from app.repositories.upload import UploadRepository
from app.schemas.import_run import ImportRunResponse, ImportUndoResponse
from app.security.tenant import get_current_membership

# Kept separate from app/api/uploads.py: this operates on ImportRecord, a
# distinct resource from Upload, and running/undoing an import is a
# different concern from the upload/detect/confirm flow B7 already owns.
router = APIRouter(prefix="/businesses/{business_id}", tags=["imports"])


@router.post("/uploads/{upload_id}/import", response_model=ImportRunResponse)
def run_import(
    upload_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ImportRunResponse:
    upload = UploadRepository(db).get_for_business(upload_id, membership.business_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
    import_record = ImportRecordRepository(db).get_for_upload(upload_id, membership.business_id)
    if import_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No mapping confirmed for this upload yet")

    try:
        result = importer.run_import(db, upload, import_record)
    except ImportRecordNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HeaderRowNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not find a header row in this file",
        ) from exc
    except MappedColumnMissing as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except FileTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    return ImportRunResponse(
        import_record_id=result.import_record_id,
        status=result.status,
        rows_total=result.rows_total,
        rows_imported=result.rows_imported,
        rows_rejected=result.rows_rejected,
        rejection_summary=result.rejection_summary,
    )


@router.post("/import-records/{import_record_id}/undo", response_model=ImportUndoResponse)
def undo_import(
    import_record_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ImportUndoResponse:
    import_record = ImportRecordRepository(db).get_for_business(import_record_id, membership.business_id)
    if import_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import record not found")

    try:
        record = importer.undo_import(db, import_record)
    except ImportNotReversible as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ImportSupersededByLaterInventoryImport as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ImportUndoResponse(
        import_record_id=record.id, status=record.status, reversed_at=record.reversed_at
    )

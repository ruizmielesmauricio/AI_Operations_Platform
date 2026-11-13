from fastapi import APIRouter

from app.schemas.business import BusinessTemplateOut
from app.templates import list_templates

router = APIRouter(prefix="/business-templates", tags=["businesses"])


@router.get("", response_model=list[BusinessTemplateOut])
def get_business_templates() -> list[BusinessTemplateOut]:
    """The business types a new account can choose at signup. Static
    configuration, no tenant data, so no auth needed."""
    return [
        BusinessTemplateOut(
            key=t.key,
            label=t.label,
            description=t.description,
            group=t.group,
            supports_repairs=t.supports_repairs,
        )
        for t in list_templates()
    ]

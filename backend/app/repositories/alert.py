import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alert import Alert


class AlertRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_active_for_business(self, business_id: uuid.UUID) -> list[Alert]:
        return list(
            self.session.scalars(
                select(Alert)
                .where(Alert.business_id == business_id, Alert.status == "active")
                .order_by(Alert.created_at.desc())
            )
        )

    def get_active_by_type_and_product_ids(
        self, business_id: uuid.UUID, alert_type: str, product_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Alert]:
        """One query, not N+1 — mirrors InventoryMovementRepository.sum_by_product_ids.
        A product_id absent from the result has no active alert of this
        type; callers must treat a missing key as "none", not query again."""
        if not product_ids:
            return {}
        rows = self.session.scalars(
            select(Alert).where(
                Alert.business_id == business_id,
                Alert.alert_type == alert_type,
                Alert.status == "active",
                Alert.product_id.in_(product_ids),
            )
        ).all()
        return {alert.product_id: alert for alert in rows}

    def create(self, *, business_id: uuid.UUID, alert_type: str, product_id: uuid.UUID, payload: dict) -> Alert:
        # Flush only — app/application/alerts.py owns the commit, same
        # convention as every other repository in this codebase.
        alert = Alert(business_id=business_id, alert_type=alert_type, product_id=product_id, payload=payload, status="active")
        self.session.add(alert)
        self.session.flush()
        return alert

    def update_payload(self, alert: Alert, payload: dict) -> None:
        alert.payload = payload
        self.session.flush()

    def resolve(self, alert: Alert) -> None:
        alert.status = "resolved"
        self.session.flush()

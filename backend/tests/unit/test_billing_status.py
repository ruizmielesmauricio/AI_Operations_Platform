import pytest

from app.billing.status import derive_subscription_status


def test_subscription_updated_echoes_payload_status():
    assert derive_subscription_status("customer.subscription.updated", "past_due") == "past_due"


def test_subscription_created_echoes_payload_status():
    assert derive_subscription_status("customer.subscription.created", "trialing") == "trialing"


def test_subscription_deleted_forces_canceled_regardless_of_payload():
    assert derive_subscription_status("customer.subscription.deleted", "active") == "canceled"


def test_invoice_paid_maps_to_active():
    assert derive_subscription_status("invoice.paid", None) == "active"


def test_invoice_payment_failed_maps_to_past_due():
    assert derive_subscription_status("invoice.payment_failed", None) == "past_due"


def test_missing_payload_status_on_lifecycle_event_raises():
    with pytest.raises(ValueError):
        derive_subscription_status("customer.subscription.updated", None)


def test_unhandled_event_type_raises():
    with pytest.raises(ValueError):
        derive_subscription_status("customer.created", "active")

class InvalidWebhookSignature(Exception):
    """A Stripe webhook payload's signature could not be verified. Kept
    independent of the `stripe` SDK's own exception type so callers outside
    client.py never need to import stripe to handle this case.
    """


class EmployeeSeatPriceNotConfigured(Exception):
    """Raised when settings.stripe_employee_seat_price_id is empty —
    a real Stripe Price object needs to be created in the Dashboard
    first (same manual step stripe_branch_price_id needed). Raised
    explicitly here rather than left to fail confusingly inside the
    Stripe SDK call itself.
    """

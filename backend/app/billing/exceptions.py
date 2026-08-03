class InvalidWebhookSignature(Exception):
    """A Stripe webhook payload's signature could not be verified. Kept
    independent of the `stripe` SDK's own exception type so callers outside
    client.py never need to import stripe to handle this case.
    """

"""Stage D17/D18's report scheduler — run as its own service
(docker-compose.yml's `scheduler`), not inside the API process. See
app/scheduler/tick.py for the reconciliation logic and
app/scheduler/__main__.py for the polling loop that drives it.
"""

"""Background workers — import processing, scheduled weekly/monthly reports
(PR-8), and any other long-running or scheduled task. Runs as a separate
process from the API in production (03_System_Architecture.md); for the
prototype these can run in-process or via a simple scheduled script.
"""

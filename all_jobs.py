"""Imports every job module so its @register decorator runs."""
import app.ingest.cvm_fidc  # noqa: F401
import app.jobs.backup  # noqa: F401

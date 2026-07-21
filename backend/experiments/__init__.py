"""Explicitly opt-in experiment definitions and safety gates.

Nothing in this package performs provider traffic when imported.  Experiment
drivers must validate their frozen manifest and direct-provider preflight evidence before
passing any request to a provider adapter.
"""

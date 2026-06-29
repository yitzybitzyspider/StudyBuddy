"""Minimal local web UI for StudyBuddy (Phase 4, thin presentation layer).

A small Flask app over the existing pipeline modules. It adds no pipeline logic; it collects
form input and renders results. With ANTHROPIC_API_KEY set it runs live; with
STUDYBUDDY_OFFLINE=1 it runs on canned data (no key).
"""

from .app import create_app

__all__ = ["create_app"]

"""Storage backends for the knowledge layer's per-user data (platform upgrade, Loop 26).

The engine talks to ``studybuddy.store`` (the facade); the facade talks to a backend that
implements the :class:`~studybuddy.storage.base.StorageBackend` protocol. Two backends:

- :class:`~studybuddy.storage.local.LocalBackend` — plain JSON files under the knowledge
  root (the original behavior; default; what tests and the CLI use).
- ``storage.supa.SupabaseBackend`` — per-user rows in Supabase Postgres with RLS (Loop 28).

Only per-user *data* goes through a backend (subjects, concepts, items, materials, learner
state, working docs). The knowledge-layer *product* — prompt registry, heuristics, run log,
proposals, design docs — stays as git files and never enters the protocol.
"""

from .base import StorageBackend
from .local import LocalBackend

__all__ = ["StorageBackend", "LocalBackend"]

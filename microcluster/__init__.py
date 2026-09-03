"""MicroCluster: privacy-preserving health-signal detection and disclosure.

Two independent engines:

- ``microcluster.detection``  -- is anything unusual happening?
- ``microcluster.disclosure`` -- what, if anything, may be said, and at
  what scope?

See ``CLAUDE.md`` for the thesis and the decided rules.
"""

from . import config, detection, disclosure, engine, models

__all__ = ["config", "detection", "disclosure", "engine", "models"]

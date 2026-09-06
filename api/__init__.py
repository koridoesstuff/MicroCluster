"""FastAPI layer for the MicroCluster outbreak simulator.

Detection and disclosure run SERVER SIDE only (CLAUDE.md, SECURITY
POSTURE). The API returns exactly what the floor-plan animation renders --
per-agent suite, position and infection state, plus that day's
detection/disclosure verdict -- and never a raw ``Report`` or any ground
truth beyond what is drawn on screen.

The ASGI app is ``api.app:app``; import it from there. ``api.bands`` is
kept dependency-light (no FastAPI import) so other packages can reuse the
count-banding rules.
"""

"""Placeware local licence enforcement (signed licence file + backend lock).

See backend/docs/Latestmods-TB/License Plan/LICENSING-RUNBOOK.md for operating it.
"""
from .license_manager import LicenseStatus, license_manager

__all__ = ["LicenseStatus", "license_manager"]

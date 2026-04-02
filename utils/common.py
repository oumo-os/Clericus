"""
Common utility functions for Clericus.
"""

import os

def ensure_dir(path: str):
    """
    Ensure that a directory exists; create it if necessary.
    """
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
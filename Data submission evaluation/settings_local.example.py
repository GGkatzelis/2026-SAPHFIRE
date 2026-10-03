"""Template for settings_local.py (git-ignored): the private, machine-specific
values. Copy this file to settings_local.py and fill in the real values."""
from pathlib import Path

# Sciebo desktop-client sync of the shared campaign folder
SCIEBO_ROOT = Path(r"C:\Users\<you>\sciebo - <account>\SAPHFIRE 2026")
# Public share link of that folder (shown on the status page)
SCIEBO_SHARE_URL = "https://fz-juelich.sciebo.de/s/<share-id>"
# Who receives the upload emails
NOTIFY_TO = "<you>@fz-juelich.de"

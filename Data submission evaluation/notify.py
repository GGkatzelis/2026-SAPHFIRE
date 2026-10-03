"""Send the evaluation report by email through the local Outlook (no SMTP setup).

Uses the Outlook profile that is signed in on this PC, so the mail leaves from
your own account and appears in your Sent Items.
"""
from __future__ import annotations

from pathlib import Path


def send_mail(to: str, subject: str, html_body: str, attachments: list[Path] = ()) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)            # 0 = olMailItem
        mail.To = to
        mail.Subject = subject
        mail.HTMLBody = html_body
        for a in attachments:
            mail.Attachments.Add(str(Path(a).resolve()))
        mail.Send()
    finally:
        pythoncom.CoUninitialize()

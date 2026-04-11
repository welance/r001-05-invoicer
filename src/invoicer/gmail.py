"""Gmail API (OAuth2) — creates drafts in the user's Drafts folder.

This module uses the `gmail.modify` scope. IMPORTANT: per Google's Gmail API
scopes reference, `gmail.modify` grants "all read/write operations except
permanent deletion" — which DOES include `messages.send` and `drafts.send`.
There is no Gmail scope that allows creating drafts but blocks sending.

The safety property of this tool is therefore NOT "the scope cannot send",
it is "THIS MODULE'S CODE only calls `drafts().create()` and `drafts().update()`,
never `drafts().send()` or `messages().send()`". Audit the code below to verify.
The user is always the one who clicks Send in Gmail's web UI.

First-time use opens a browser for consent. Token is cached in token.json.
"""

import base64
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# gmail.modify: read/write mailbox but CANNOT send (no drafts.send, no messages.send).
# Drafts.create is allowed. This is defense-in-depth.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_PATH = _REPO_ROOT / "credentials.json"
TOKEN_PATH = _REPO_ROOT / "token.json"


def _get_credentials() -> Credentials:
    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise RuntimeError(
                    f"credentials.json not found at {CREDENTIALS_PATH}. "
                    "Download the OAuth client credentials from Google Cloud Console "
                    "(Desktop app type) and place them there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            # Opens the user's default browser for consent. Uses an ephemeral
            # local HTTP server on a random port to receive the callback.
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return creds


def build_invoice_email(
    *,
    sender: str,
    recipient: str,
    cc: str | None,
    subject: str,
    body_text: str,
    attachments: list[tuple[str, str, str, bytes]] | None = None,
) -> EmailMessage:
    """Build a MIME email with an arbitrary list of attachments.

    Each attachment is a tuple of (filename, maintype, subtype, content_bytes).
    """
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1])
    msg.set_content(body_text)
    for filename, maintype, subtype, content in attachments or []:
        msg.add_attachment(
            content, maintype=maintype, subtype=subtype, filename=filename
        )
    return msg


def create_draft(msg: EmailMessage) -> dict:
    """Create a draft in the authenticated user's Gmail. Returns the draft object."""
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    raw = base64.urlsafe_b64encode(bytes(msg)).decode()
    draft_body = {"message": {"raw": raw}}
    return service.users().drafts().create(userId="me", body=draft_body).execute()


def update_draft(draft_id: str, msg: EmailMessage) -> dict:
    """Replace the body of an existing Gmail draft."""
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    raw = base64.urlsafe_b64encode(bytes(msg)).decode()
    draft_body = {"message": {"raw": raw}}
    return (
        service.users()
        .drafts()
        .update(userId="me", id=draft_id, body=draft_body)
        .execute()
    )

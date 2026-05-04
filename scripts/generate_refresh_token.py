"""One-time helper: generate a Google OAuth refresh token for the follow-up
email job. Run this on your local machine. It opens a browser, you authorize
the app once, and it prints a refresh_token you paste into Render.

PREREQUISITES
-------------
1. A Google Cloud project (existing or new) with the following APIs enabled:
     - Gmail API
     - Google Calendar API
2. An OAuth 2.0 Client ID of type "Desktop app". Download the client_secret JSON.
3. The Google account being authorized must be cma@sixpeakcapital.com (this is
   the account the portals will send "From:" and read calendar invitees as).

USAGE
-----
    pip install google-auth-oauthlib
    python scripts/generate_refresh_token.py path/to/client_secret.json

A browser will open. Click through the consent screen (you'll see a "Google
hasn't verified this app" warning since the project is in Testing mode — click
"Advanced" → "Go to {project name}" to proceed). Once authorized, this script
prints three values:

    GOOGLE_CLIENT_ID=...
    GOOGLE_CLIENT_SECRET=...
    GOOGLE_REFRESH_TOKEN=...

Paste those into the Render dashboard for all three portal services
(work-portal-api, lv-exec, sp-finance). The same token works for all three.

SECURITY NOTE
-------------
The refresh_token grants long-lived access to send Gmail and read Calendar.
Store it only in Render env vars and your password manager. Don't commit it.
If it leaks, revoke at https://myaccount.google.com/permissions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("client_secret_json",
                        help="Path to the OAuth client secret JSON downloaded from Google Cloud Console")
    args = parser.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib not installed. Run:\n"
              "  pip install google-auth-oauthlib", file=sys.stderr)
        return 1

    secret_path = Path(args.client_secret_json)
    if not secret_path.exists():
        print(f"ERROR: client secret file not found: {secret_path}", file=sys.stderr)
        return 1

    with secret_path.open("r", encoding="utf-8") as f:
        client_config = json.load(f)

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # run_local_server starts a temporary HTTP listener and opens the browser
    # to the consent URL. After auth, Google redirects back with the code.
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print("ERROR: no refresh_token returned. Make sure access_type='offline' "
              "and prompt='consent' (this script sets both). If the account has "
              "previously authorized this app, revoke at "
              "https://myaccount.google.com/permissions and re-run.",
              file=sys.stderr)
        return 1

    # Pull the matching client_id/secret out of the JSON so the user has
    # all three values together for paste-into-Render.
    section = client_config.get("installed") or client_config.get("web") or {}
    client_id = section.get("client_id", "")
    client_secret = section.get("client_secret", "")

    print()
    print("=" * 60)
    print("SUCCESS — copy these into Render env vars for ALL THREE portal services")
    print("(work-portal-api, lv-exec, sp-finance):")
    print("=" * 60)
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 60)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

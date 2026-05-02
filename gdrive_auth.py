#!/usr/bin/env python3
"""
Run ONCE locally to get OAuth2 refresh token for Google Drive.
Then copy the printed values to .env and Render env vars.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/drive']

flow = InstalledAppFlow.from_client_secrets_file('oauth_credentials.json', SCOPES)
creds = flow.run_local_server(port=0)

print("\n=== הכנס את הערכים האלה ל-.env ול-Render ===")
print(f"GOOGLE_CLIENT_ID={creds.client_id}")
print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")

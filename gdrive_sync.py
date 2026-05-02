import os
import io
import json

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2 import service_account

SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID', '')

_BASE = os.path.dirname(os.path.abspath(__file__))
_CREDS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE',
                         os.path.join(_BASE, 'credentials.json'))
if not os.path.exists(_CREDS_FILE):
    _CREDS_FILE = '/etc/secrets/credentials.json'


def _service():
    creds = service_account.Credentials.from_service_account_file(
        _CREDS_FILE, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def _find_file_id(svc, filename):
    q = f"name='{filename}' and '{FOLDER_ID}' in parents and trashed=false"
    res = svc.files().list(q=q, fields='files(id)').execute()
    files = res.get('files', [])
    return files[0]['id'] if files else None


def upload_json(filename, data):
    if not FOLDER_ID:
        return
    try:
        svc = _service()
        content = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype='application/json', resumable=False)
        file_id = _find_file_id(svc, filename)
        if file_id:
            svc.files().update(fileId=file_id, media_body=media).execute()
        else:
            meta = {'name': filename, 'parents': [FOLDER_ID]}
            svc.files().create(body=meta, media_body=media, fields='id').execute()
    except Exception as e:
        print(f"[gdrive] upload '{filename}' failed: {e}")


def download_json(filename):
    if not FOLDER_ID:
        return {}
    try:
        svc = _service()
        file_id = _find_file_id(svc, filename)
        if not file_id:
            return {}
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = dl.next_chunk()
        return json.loads(buf.getvalue().decode('utf-8'))
    except Exception as e:
        print(f"[gdrive] download '{filename}' failed: {e}")
        return {}

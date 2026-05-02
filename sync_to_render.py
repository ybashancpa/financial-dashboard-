import requests
import json
import os
from dotenv import load_dotenv
load_dotenv()

RENDER_URL = os.getenv('RENDER_URL')
SECRET_KEY = os.getenv('DASHBOARD_SECRET_KEY')

def sync_to_render(filename, data):
    try:
        response = requests.post(
            f"{RENDER_URL}/api/update-data",
            json={"filename": filename, "data": data},
            headers={"X-Secret-Key": SECRET_KEY},
            timeout=30
        )
        if response.status_code == 200:
            print(f"[sync] {filename} synced OK")
        else:
            print(f"[sync] {filename} failed: {response.status_code}")
    except Exception as e:
        print(f"[sync] {filename} error: {e}")

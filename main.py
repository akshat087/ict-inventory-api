from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from fastapi.responses import JSONResponse
import pandas as pd
import tempfile
import os
import io
import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

app = FastAPI()

# Load credentials and keys from environment
openai.api_key = os.getenv("OPENAI_API_KEY")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

SCOPES = ['https://www.googleapis.com/auth/drive']
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=credentials)

class FileRequest(BaseModel):
    file_id: str

@app.post("/preview-inventory")
async def preview_inventory(req: FileRequest):
    print(f"Called with file_id: {req.file_id}")

    # Step 1: Download the Excel file from Google Drive
    try:
        request = drive_service.files().get_media(fileId=req.file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to download file: {str(e)}"})

    # Step 2: Save temporarily and read with pandas
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_file.write(fh.getvalue())
            tmp_path = tmp_file.name

        df = pd.read_excel(tmp_path)
        preview = df.head(3).to_dict(orient="records")

        return JSONResponse(content={"file_preview": preview})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to process Excel file: {str(e)}"})

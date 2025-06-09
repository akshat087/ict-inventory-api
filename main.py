from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from fastapi.responses import JSONResponse
import pandas as pd
import tempfile
import os
import io
import openai
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

app = FastAPI()

# Initialize OpenAI client (1.x+)
client = OpenAI()
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
SCOPES = ['https://www.googleapis.com/auth/drive']
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=credentials)

class FileRequest(BaseModel):
    file_id: str
    output_folder_id: Optional[str] = None

def is_missing(val):
    return str(val).strip().upper() in ["", "N/A", "NA", "NONE"]

@app.post("/preview-inventory")
async def preview_inventory(req: FileRequest):
    print(f"/preview-inventory called with file_id: {req.file_id}")
    try:
        request = drive_service.files().get_media(fileId=req.file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_file.write(fh.getvalue())
            tmp_path = tmp_file.name

        df = pd.read_excel(tmp_path)
        df = df.head(20).fillna("N/A").astype(str)
        preview = df.to_dict(orient="records")

        formatted_assets = ""
        for i, asset in enumerate(preview, start=1):
            description = ", ".join([f"{k}: {v}" for k, v in asset.items()])
            formatted_assets += f"{i}. {description}\n"

        prompt = f"""
You are a DORA compliance and ICT risk expert for banking systems.

Please analyze the following ICT assets and provide for each:
- The top ICT risks
- Recommended controls
- Key system or vendor dependencies

Format your response per asset like:
**Asset Name**
- Risks:
- Controls:
- Dependencies:

Assets:
{formatted_assets}
        """

        analysis = query_openai(prompt)

        return JSONResponse(content={"file_preview": preview, "analysis": analysis})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

def query_openai(prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a DORA compliance expert for financial institutions."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[OpenAI Error] {str(e)}"

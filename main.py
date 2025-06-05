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

# Load credentials
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
    print(f"✅ Called with file_id: {req.file_id}")

    # Step 1: Download file
    try:
        request = drive_service.files().get_media(fileId=req.file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to download file: {str(e)}"})

    # Step 2: Read file + analyze full content
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_file.write(fh.getvalue())
            tmp_path = tmp_file.name

        df = pd.read_excel(tmp_path)

        # Limit to a reasonable number of rows for GPT context (adjust if needed)
        max_assets = 20
        df = df.head(max_assets)
        preview = df.to_dict(orient="records")

        # Step 3: Format prompt
        formatted_assets = ""
        for i, asset in enumerate(preview, start=1):
            asset_description = ", ".join([f"{k}: {v}" for k, v in asset.items()])
            formatted_assets += f"{i}. {asset_description}\n"

        prompt = f"""
You are a DORA compliance and ICT risk expert for banking systems.

Please analyze the following ICT assets and provide for **each one**:
- The top ICT risks
- Recommended controls (e.g. standards, processes, frameworks)
- Any key system or vendor dependencies

Format your response per asset like:
**Asset Name**
- Risks:
- Controls:
- Dependencies:

Assets:
{formatted_assets}
        """

        analysis = query_openai(prompt)

        return JSONResponse(content={
            "file_preview": preview,
            "analysis": analysis
        })

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to process Excel file: {str(e)}"})


def query_openai(prompt: str) -> str:
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a banking ICT risk and DORA compliance expert."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[OpenAI Error] {str(e)}"

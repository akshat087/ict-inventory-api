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
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

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
    output_folder_id: Optional[str] = None

def is_missing(val):
    return str(val).strip().upper() in ["", "N/A", "NA", "NONE"]

@app.post("/preview-inventory")
async def preview_inventory(req: FileRequest):
    print(f"✅ /preview-inventory called with file_id: {req.file_id}")
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

@app.post("/export-inventory-analysis")
async def export_inventory_analysis(req: FileRequest):
    print(f"✅ /export-inventory-analysis called with file_id: {req.file_id}")
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

        for index, row in df.iterrows():
            asset_description = ", ".join([f"{k}: {v}" for k, v in row.items()])
            if "Identified ICT Risks" not in df.columns or is_missing(row.get("Identified ICT Risks")):
                prompt = f"What are the ICT risks for: {asset_description}?"
                df.at[index, "Identified ICT Risks"] = query_openai(prompt)
            if "Recommended Controls" not in df.columns or is_missing(row.get("Recommended Controls")):
                prompt = f"What controls should be applied for: {asset_description}?"
                df.at[index, "Recommended Controls"] = query_openai(prompt)
            if "Key Dependencies" not in df.columns or is_missing(row.get("Key Dependencies")):
                prompt = f"What are the key system or vendor dependencies for: {asset_description}?"
                df.at[index, "Key Dependencies"] = query_openai(prompt)

        updated_path = tmp_path.replace(".xlsx", "_analyzed.xlsx")
        df.to_excel(updated_path, index=False)

        file_metadata = {
            'name': os.path.basename(updated_path),
            'parents': [req.output_folder_id] if req.output_folder_id else []
        }
        media = MediaFileUpload(updated_path, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()

        drive_service.permissions().create(fileId=uploaded['id'], body={'type': 'anyone', 'role': 'reader'}).execute()
        return JSONResponse(content={"updated_file_link": uploaded.get("webViewLink")})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

def query_openai(prompt: str) -> str:
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a DORA compliance expert for financial institutions."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[OpenAI Error] {str(e)}"

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
import tempfile
import os
import io
import openai
from openai import OpenAI
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

app = FastAPI()

# Environment & setup
client = OpenAI()
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
SCOPES = ['https://www.googleapis.com/auth/drive']
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=credentials)

# Define and mount static directory using absolute path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(BASE_DIR, "files")
os.makedirs(FILES_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=FILES_DIR), name="files")

class FileRequest(BaseModel):
    file_id: str

def is_missing(val):
    return str(val).strip().upper() in ["", "N/A", "NA", "NONE"]

@app.post("/generate-inventory-analysis")
async def generate_inventory_analysis(req: FileRequest):
    try:
        # Download file from Google Drive
        request = drive_service.files().get_media(fileId=req.file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_file.write(fh.getvalue())
            tmp_path = tmp_file.name

        # Read and clean DataFrame
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

        # Save to files directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"inventory_analyzed_{timestamp}.xlsx"
        filepath = os.path.join(FILES_DIR, filename)
        df.to_excel(filepath, index=False)

        # Construct full download URL
        backend_url = os.getenv("BACKEND_URL", "https://ict-inventory-api.onrender.com")
        download_url = f"{backend_url}/files/{filename}"
        return JSONResponse(content={"download_link": download_url})

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

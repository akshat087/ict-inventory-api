from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional
from fastapi.responses import JSONResponse
import pandas as pd
import openai
import tempfile
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import io

app = FastAPI()

# Replace with your OpenAI API key and Google service account credentials path
OPENAI_API_KEY = "your-openai-api-key"
SERVICE_ACCOUNT_FILE = "service_account.json"

openai.api_key = OPENAI_API_KEY

SCOPES = ['https://www.googleapis.com/auth/drive']
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

drive_service = build('drive', 'v3', credentials=credentials)

class FileRequest(BaseModel):
    file_id: str
    output_folder_id: Optional[str] = None

@app.post("/analyze-inventory")
async def analyze_inventory(req: FileRequest):
    file_id = req.file_id
    output_folder_id = req.output_folder_id

    # Download the file from Google Drive
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()

    # Save the file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
        tmp_file.write(fh.getvalue())
        tmp_file_path = tmp_file.name

    # Process the Excel file
    df = pd.read_excel(tmp_file_path)

    for index, row in df.iterrows():
        if not row.get("Identified ICT Risks"):
            prompt = f"What are the key ICT risks for the following asset in a bank: {row['Asset Name']}?"
            risks = query_openai(prompt)
            df.at[index, "Identified ICT Risks"] = risks

        if not row.get("Recommended Controls"):
            prompt = f"What controls should be applied to mitigate the ICT risks for: {row['Asset Name']}?"
            controls = query_openai(prompt)
            df.at[index, "Recommended Controls"] = controls

        if not row.get("Key Dependencies"):
            prompt = f"What are the key system or vendor dependencies for: {row['Asset Name']}?"
            deps = query_openai(prompt)
            df.at[index, "Key Dependencies"] = deps

    updated_path = tmp_file_path.replace(".xlsx", "_updated.xlsx")
    df.to_excel(updated_path, index=False)

    # Upload updated file to Google Drive
    file_metadata = {
        'name': os.path.basename(updated_path),
        'parents': [output_folder_id] if output_folder_id else []
    }
    media = MediaFileUpload(updated_path, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()

    return JSONResponse(content={"updated_file_link": uploaded_file.get("webViewLink")})

def query_openai(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert in ICT risk management for banks."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=200
    )
    return response.choices[0].message.content.strip()

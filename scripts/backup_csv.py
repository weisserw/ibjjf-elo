#!/usr/bin/env python3

import argparse
import csv
import traceback
import sys
import gzip
import os
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Google API setup
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
SERVICE_ACCOUNT_FILE = "/etc/secrets/service-account.json"


def get_folder_id(drive_service, folder_name):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get("files", [])
    if not items:
        raise FileNotFoundError(f"Folder '{folder_name}' not found.")
    return items[0]["id"]


def upload_to_drive(file_path):
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    drive_service = build("drive", "v3", credentials=credentials)

    folder_id = get_folder_id(drive_service, "IBJJF CSV Files")

    file_metadata = {"name": os.path.basename(file_path), "parents": [folder_id]}
    media = MediaFileUpload(file_path, mimetype="text/csv")
    file = (
        drive_service.files()
        .create(body=file_metadata, media_body=media, fields="id")
        .execute()
    )
    return file.get("id")


def create_google_sheet(filename, data):
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    drive_service = build("drive", "v3", credentials=credentials)
    sheets_service = build("sheets", "v4", credentials=credentials)
    gc = gspread.authorize(credentials)

    folder_id = get_folder_id(drive_service, "IBJJF Spreadsheets")

    spreadsheet = {"properties": {"title": filename}}
    spreadsheet = (
        sheets_service.spreadsheets()
        .create(body=spreadsheet, fields="spreadsheetId")
        .execute()
    )
    spreadsheet_id = spreadsheet.get("spreadsheetId")

    drive_service.files().update(
        fileId=spreadsheet_id,
        addParents=folder_id,
        removeParents=None,
        fields="id, parents",
    ).execute()

    permission = {"type": "anyone", "role": "reader"}
    drive_service.permissions().create(fileId=spreadsheet_id, body=permission).execute()

    sheet = gc.open_by_key(spreadsheet_id)
    worksheet = sheet.get_worksheet(0)
    worksheet.update([data[0]] + data[1:])

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def main():
    try:
        parser = argparse.ArgumentParser(
            description="Copy CSV files to Google Drive / Sheets"
        )
        parser.add_argument(
            "csv_files", metavar="csv_file", type=str, nargs="+", help="CSV file paths"
        )
        args = parser.parse_args()

        for csv_file_path in args.csv_files:
            with open(csv_file_path, "rb") as f_in:
                with gzip.open(f"{csv_file_path}.gz", "wb") as f_out:
                    f_out.writelines(f_in)
            try:
                upload_to_drive(f"{csv_file_path}.gz")
                print(f"{csv_file_path}: File uploaded to Google Drive.")
            finally:
                os.remove(f"{csv_file_path}.gz")

            with open(csv_file_path, "r") as file:
                reader = csv.reader(file)
                data = list(reader)
            sheet_link = create_google_sheet(csv_file_path, data)
            print(f"{csv_file_path}: Google Sheet Created: {sheet_link}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

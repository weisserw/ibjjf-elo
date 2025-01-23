#!/usr/bin/env python3

import argparse
import csv
import traceback
import sys
import os
import gspread
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

# Google API setup
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def get_credentials_from_env():
    service_account_info = json.loads(os.getenv("GC_SERVICE_ACCOUNT"))
    return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)


def get_folder_id(drive_service, folder_name):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get("files", [])
    if not items:
        raise FileNotFoundError(f"Folder '{folder_name}' not found.")
    return items[0]["id"]


def get_s3_client():
    aws_creds = json.loads(os.getenv("AWS_CREDS"))
    return boto3.client(
        "s3",
        aws_access_key_id=aws_creds["aws_access_key_id"],
        aws_secret_access_key=aws_creds["aws_secret_access_key"],
        region_name=aws_creds.get("region"),
    )


def upload_to_s3(s3_client, file_path, bucket_name, prefix):
    try:
        s3_client.upload_file(
            file_path, bucket_name, f"{prefix}/{os.path.basename(file_path)}"
        )
        print(f"{file_path}: File uploaded to S3.")
    except (NoCredentialsError, PartialCredentialsError) as e:
        print(f"Credentials error: {e}")
        raise
    except Exception as e:
        print(f"An error occurred: {e}")
        raise


def create_google_sheet(filename, data):
    credentials = get_credentials_from_env()
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
            description="Copy CSV files to AWS S3 / Google Sheets"
        )
        parser.add_argument(
            "csv_files", metavar="csv_file", type=str, nargs="+", help="CSV file paths"
        )
        parser.add_argument(
            "--historical",
            action="store_true",
            help="Upload files to 'ibjjf_historical_data' prefix",
        )
        parser.add_argument(
            "--no-sheets",
            action="store_true",
            help="Do not create Google Sheets",
        )
        args = parser.parse_args()

        s3_client = get_s3_client()
        bucket_name = os.getenv("S3_BUCKET")
        if not bucket_name:
            raise ValueError("S3_BUCKET environment variable not set")

        prefix = "ibjjf_historical_data" if args.historical else "ibjjf_csv_files"

        for csv_file_path in args.csv_files:
            try:
                upload_to_s3(s3_client, csv_file_path, bucket_name, prefix)
            except Exception as e:
                print(f"Failed to upload {csv_file_path}: {e}")

            if not args.historical and not args.no_sheets:
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

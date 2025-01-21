#!/usr/bin/env python3

import argparse
import os
import re
import json
import gzip
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from progress.bar import Bar

# Google API setup
SCOPES = [
    "https://www.googleapis.com/auth/drive",
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


def get_latest_files(drive_service, folder_id):
    query = f"'{folder_id}' in parents and trashed=false"
    page_token = None
    file_dict = {}
    pattern = re.compile(r"^(\d+)\..+\.(\d{12})\.csv(\.gz)?$")

    while True:
        results = (
            drive_service.files()
            .list(
                q=query, fields="nextPageToken, files(id, name)", pageToken=page_token
            )
            .execute()
        )
        items = results.get("files", [])

        for item in items:
            match = pattern.match(item["name"])
            if match:
                file_id, timestamp, _ = match.groups()
                if (
                    file_id not in file_dict
                    or timestamp > file_dict[file_id]["timestamp"]
                ):
                    file_dict[file_id] = {
                        "id": item["id"],
                        "name": item["name"],
                        "timestamp": timestamp,
                    }
            else:
                file_dict[item["id"]] = {
                    "id": item["id"],
                    "name": item["name"],
                    "timestamp": "0",
                }

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    return sorted(file_dict.values(), key=lambda x: x["name"], reverse=True)


def download_file(drive_service, file_id, file_name):
    request = drive_service.files().get_media(fileId=file_id)
    file_path = os.path.join(os.getcwd(), file_name)

    with open(file_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    if file_name.endswith(".gz"):
        with gzip.open(file_path, "rb") as f_in:
            with open(file_path[:-3], "wb") as f_out:
                f_out.write(f_in.read())
        os.remove(file_path)


def main():
    parser = argparse.ArgumentParser(description="Download CSV files from Google Drive")
    parser.add_argument(
        "--historical",
        action="store_true",
        help="Download files from 'Historical IBJJF Data' directory",
    )
    args = parser.parse_args()

    credentials = get_credentials_from_env()
    drive_service = build("drive", "v3", credentials=credentials)

    folder_name = "Historical IBJJF Data" if args.historical else "IBJJF CSV Files"
    folder_id = get_folder_id(drive_service, folder_name)

    files_to_download = get_latest_files(drive_service, folder_id)

    with Bar("Downloading files", max=len(files_to_download)) as bar:
        for file_info in files_to_download:
            download_file(drive_service, file_info["id"], file_info["name"])
            bar.next()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
import re
import json
import gzip
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from progress_bar import Bar


def get_s3_client():
    aws_creds = json.loads(os.getenv("AWS_CREDS"))
    return boto3.client(
        "s3",
        aws_access_key_id=aws_creds["aws_access_key_id"],
        aws_secret_access_key=aws_creds["aws_secret_access_key"],
        region_name=aws_creds.get("region"),
    )


def get_latest_files(s3_client, bucket_name, prefix):
    response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    if "Contents" not in response:
        raise FileNotFoundError(
            f"No files found in bucket '{bucket_name}' with prefix '{prefix}'"
        )

    file_dict = {}
    pattern = re.compile(r"^(\d+)\..+\.(\d{12})\.csv(\.gz)?$")

    for obj in response["Contents"]:
        match = pattern.match(os.path.basename(obj["Key"]))
        if match:
            file_id, timestamp, _ = match.groups()
            if file_id not in file_dict or timestamp > file_dict[file_id]["timestamp"]:
                file_dict[file_id] = {
                    "key": obj["Key"],
                    "timestamp": timestamp,
                }
        else:
            file_dict[obj["Key"]] = {
                "key": obj["Key"],
                "timestamp": "0",
            }

    return sorted(file_dict.values(), key=lambda x: x["timestamp"], reverse=True)


def download_file(s3_client, bucket_name, key, file_name):
    file_path = os.path.join(os.getcwd(), file_name)
    try:
        s3_client.download_file(bucket_name, key, file_path)
    except (NoCredentialsError, PartialCredentialsError) as e:
        print(f"Credentials error: {e}")
        raise
    except Exception as e:
        print(f"An error occurred: {e}")
        raise

    if file_name.endswith(".gz"):
        with gzip.open(file_path, "rb") as f_in:
            with open(file_path[:-3], "wb") as f_out:
                f_out.write(f_in.read())
        os.remove(file_path)


def main():
    parser = argparse.ArgumentParser(description="Download CSV files from AWS S3")
    parser.add_argument(
        "--historical",
        action="store_true",
        help="Download files from 'ibjjf_historical_data' prefix",
    )
    parser.add_argument(
        "--recent",
        type=int,
        help="Download the N most recent files",
    )
    parser.add_argument(
        "--no-tty",
        action="store_true",
        help="Log output compatible with non-tty environments",
    )
    args = parser.parse_args()

    if args.historical and args.recent:
        parser.error("Cannot use --recent with --historical")

    s3_client = get_s3_client()
    bucket_name = os.getenv("S3_BUCKET")
    if not bucket_name:
        raise ValueError("S3_BUCKET environment variable not set")

    prefix = "ibjjf_historical_data/" if args.historical else "ibjjf_csv_files/"
    files_to_download = get_latest_files(s3_client, bucket_name, prefix)

    if args.recent:
        files_to_download = files_to_download[: args.recent]

    with Bar(
        "Downloading files",
        max=len(files_to_download),
        check_tty=False,
        no_tty=args.no_tty,
    ) as bar:
        for file_info in files_to_download:
            download_file(
                s3_client,
                bucket_name,
                file_info["key"],
                os.path.basename(file_info["key"]),
            )
            bar.next()


if __name__ == "__main__":
    main()

import json
import os
import boto3
import requests
from bs4 import BeautifulSoup
import logging
from datetime import datetime, timezone
from models import Athlete

log = logging.getLogger("ibjjf")


def get_s3_client():
    aws_creds = json.loads(os.getenv("AWS_CREDS"))
    return boto3.client(
        "s3",
        aws_access_key_id=aws_creds["aws_access_key_id"],
        aws_secret_access_key=aws_creds["aws_secret_access_key"],
        region_name=aws_creds.get("region"),
    )


bucket_name = os.getenv("S3_BUCKET")
photo_key = "photos"
if os.getenv("DATABASE_URL") is None:
    photo_key = "photos-dev"


def get_instagram_profile_photo_url(instagram_username):
    url = f"https://www.instagram.com/{instagram_username}/"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception("Failed to fetch Instagram profile page")
    soup = BeautifulSoup(response.text, "html.parser")
    meta_tag = soup.find("meta", property="og:image")
    if meta_tag:
        return meta_tag["content"]
    raise Exception(f"Profile photo not found at {url}")


def save_instagram_profile_photo_to_s3(s3_client, athlete: Athlete):
    photo_path = f"{photo_key}/{athlete.id}.jpg"

    photo_url = get_instagram_profile_photo_url(athlete.instagram_profile)

    response = requests.get(photo_url)
    if response.status_code != 200:
        raise Exception("Failed to download profile photo")
    s3_client.put_object(Bucket=bucket_name, Key=photo_path, Body=response.content)
    log.info(
        f"Athlete {athlete.name}: Profile photo uploaded to S3 with key: {photo_path}"
    )

    athlete.profile_image_saved_at = datetime.now(timezone.utc)


def get_public_photo_url(s3_client, athlete: Athlete):
    if not athlete.profile_image_key:
        raise Exception("Athlete does not have a profile image saved")
    # sign URL with AWS credentials
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": athlete.profile_image_key},
        ExpiresIn=3600,  # URL valid for 1 hour
    )
    return url

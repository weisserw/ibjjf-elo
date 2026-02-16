import json
import os
import boto3
import requests
import re
from uuid import UUID
from bs4 import BeautifulSoup
import logging
from datetime import datetime, timezone
from models import Athlete
from normalize import normalize

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

    image_url = None
    name = None
    if meta_tag:
        image_url = meta_tag["content"]

    if not image_url:
        raise Exception(f"Profile photo not found at {url}")

    meta_tag = soup.find("meta", property="og:title")
    if meta_tag:
        name_match = re.search(r"^(.+) \(", meta_tag["content"])
        if name_match:
            name = name_match.group(1)
    if not name:
        print(
            f"Warning: Could not extract name from Instagram profile {instagram_username}"
        )

    return image_url, name


def save_instagram_profile_photo_to_s3(
    s3_client, athlete: Athlete, save_photo: bool = True, save_name: bool = True
):
    photo_url, ig_name = get_instagram_profile_photo_url(athlete.instagram_profile)

    if save_photo:
        response = requests.get(photo_url)
        if response.status_code != 200:
            raise Exception("Failed to download profile photo")
        content_type = (
            (response.headers.get("Content-Type") or "").split(";")[0].strip()
        )
        if content_type.lower() != "image/jpeg":
            raise Exception(
                f"Unexpected Instagram profile photo content type: {content_type or 'unknown'}"
            )
        save_profile_photo_to_s3(
            s3_client,
            athlete,
            response.content,
            content_type=content_type,
            validate_image_bytes=False,
        )

    if save_name and not athlete.personal_name:
        athlete.personal_name = ig_name
        athlete.normalized_personal_name = (
            None if ig_name is None else normalize(ig_name)
        )
        log.info(f"Athlete {athlete.name}: Instagram personal name saved: {ig_name}")


def detect_image_content_type(photo_bytes: bytes):
    if photo_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def save_profile_photo_to_s3(
    s3_client,
    athlete: Athlete,
    photo_bytes: bytes,
    content_type: str = None,
    validate_image_bytes: bool = True,
):
    if not photo_bytes:
        raise ValueError("Profile photo bytes are required")

    photo_path = f"{photo_key}/{athlete.id}.jpg"
    normalized_content_type = (
        None if content_type is None else content_type.split(";")[0].strip().lower()
    )

    if validate_image_bytes:
        detected_content_type = detect_image_content_type(photo_bytes)
        if detected_content_type != "image/jpeg":
            raise ValueError("Invalid profile photo format")
        final_content_type = detected_content_type
    else:
        if normalized_content_type != "image/jpeg":
            raise ValueError("Profile photo content type must be image/jpeg")
        final_content_type = normalized_content_type

    s3_client.put_object(
        Bucket=bucket_name,
        Key=photo_path,
        Body=photo_bytes,
        ContentType=final_content_type,
    )
    log.info(
        f"Athlete {athlete.name}: Profile photo uploaded to S3 with key: {photo_path}"
    )
    athlete.profile_image_saved_at = datetime.now(timezone.utc)


def get_public_photo_url(s3_client, athlete: Athlete):
    if not getattr(athlete, "profile_image_saved_at", None):
        raise Exception("Athlete does not have a profile image saved")

    athlete_id = getattr(athlete, "id", None)
    if athlete_id is None:
        raise Exception("Athlete does not have an ID")

    if isinstance(athlete_id, str):
        athlete_id = UUID(athlete_id)

    photo_path = f"{photo_key}/{athlete_id}.jpg"
    # sign URL with AWS credentials
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": photo_path},
        ExpiresIn=3600,  # URL valid for 1 hour
    )
    return url

import json
import os
import boto3
import requests
from botocore.config import Config
from uuid import UUID
from bs4 import BeautifulSoup
import logging
import io
from datetime import datetime, timezone
from urllib.parse import urlparse

from PIL import Image, ImageOps, UnidentifiedImageError
from models import Athlete

log = logging.getLogger("ibjjf")

INSTAGRAM_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}


def convert_image_to_jpeg(image_bytes: bytes, quality: int = 90) -> bytes:
    """Decode an uploaded image and return orientation-corrected RGB JPEG bytes."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                image = rgb
            else:
                image = image.convert("RGB")

            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Invalid image data") from exc


def get_s3_client():
    aws_creds = json.loads(os.getenv("AWS_CREDS"))
    return boto3.client(
        "s3",
        aws_access_key_id=aws_creds["aws_access_key_id"],
        aws_secret_access_key=aws_creds["aws_secret_access_key"],
        region_name=aws_creds.get("region"),
        config=Config(
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


bucket_name = os.getenv("S3_BUCKET")
photo_key = "photos"
if os.getenv("DATABASE_URL") is None:
    photo_key = "photos-dev"


def get_instagram_profile_photo_url(instagram_username):
    url = f"https://www.instagram.com/{instagram_username}/"
    response = requests.get(url, headers=INSTAGRAM_REQUEST_HEADERS)
    if response.status_code != 200:
        raise Exception("Failed to fetch Instagram profile page")
    soup = BeautifulSoup(response.text, "html.parser")
    profile_meta_tag = soup.find("meta", property="og:url")
    profile_url = profile_meta_tag.get("content") if profile_meta_tag else None
    parsed_profile_url = urlparse(profile_url or "")
    if (
        parsed_profile_url.hostname not in ("instagram.com", "www.instagram.com")
        or parsed_profile_url.path.strip("/").lower()
        != instagram_username.strip("@").lower()
    ):
        raise Exception(f"Instagram did not return profile metadata for {url}")

    meta_tag = soup.find("meta", property="og:image")

    image_url = meta_tag.get("content") if meta_tag else None

    if not image_url:
        raise Exception(f"Profile photo not found at {url}")

    image_hostname = (urlparse(image_url).hostname or "").lower()
    if not (
        image_hostname.startswith("scontent-")
        and image_hostname.endswith(".cdninstagram.com")
    ):
        raise Exception(f"Instagram returned a non-profile image for {url}")

    return image_url


def save_instagram_profile_photo_to_s3(
    s3_client, athlete: Athlete, save_photo: bool = True
):
    photo_url = get_instagram_profile_photo_url(athlete.instagram_profile)

    if save_photo:
        response = requests.get(photo_url, headers=INSTAGRAM_REQUEST_HEADERS)
        if response.status_code != 200:
            raise Exception("Failed to download profile photo")
        content_type = (
            (response.headers.get("Content-Type") or "").split(";")[0].strip()
        )
        if content_type.lower() not in ("image/jpeg", "image/png"):
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


def detect_image_content_type(photo_bytes: bytes):
    if photo_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if photo_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
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

    allowed_content_types = ("image/jpeg", "image/png")

    if validate_image_bytes:
        detected_content_type = detect_image_content_type(photo_bytes)
        if detected_content_type not in allowed_content_types:
            raise ValueError("Invalid profile photo format")
        final_content_type = detected_content_type
    else:
        if normalized_content_type not in allowed_content_types:
            raise ValueError(
                "Profile photo content type must be image/jpeg or image/png"
            )
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

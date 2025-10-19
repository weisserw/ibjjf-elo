import json
import os
import boto3
import requests
from bs4 import BeautifulSoup
import logging
from datetime import datetime, timezone
from models import Athlete
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

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


def init_chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )

    driver_path = os.getenv("CHROMEDRIVER_PATH")
    if driver_path:
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
    else:
        driver = webdriver.Chrome(options=chrome_options)

    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def get_instagram_profile_photo_url(instagram_username, driver):
    url = f"https://www.instagram.com/{instagram_username}/"
    driver.get(url)
    try:
        # Wait up to 10 seconds for the meta tag to appear
        WebDriverWait(driver, 10).until(
            lambda d: d.find_element(By.XPATH, '//meta[@property="og:image"]')
        )
    except Exception:
        raise Exception(f"Profile photo not found at {url}")
    soup = BeautifulSoup(driver.page_source, "html.parser")
    meta_tag = soup.find("meta", property="og:image")
    if meta_tag:
        return meta_tag["content"]
    raise Exception(f"Profile photo not found at {url}")


def save_instagram_profile_photo_to_s3(s3_client, driver, athlete: Athlete):
    photo_path = f"{photo_key}/{athlete.id}.jpg"

    photo_url = get_instagram_profile_photo_url(athlete.instagram_profile, driver)

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

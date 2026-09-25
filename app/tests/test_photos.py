import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from photos import get_instagram_profile_photo_url  # noqa: E402


def instagram_response(html):
    response = Mock()
    response.status_code = 200
    response.text = html
    return response


class InstagramProfilePhotoTestCase(unittest.TestCase):
    @patch("photos.requests.get")
    def test_accepts_profile_media(self, mock_get):
        image_url = "https://scontent-example.cdninstagram.com/v/profile.jpg"
        mock_get.return_value = instagram_response(
            f"""
            <meta property="og:url" content="https://www.instagram.com/Jessakainajj/">
            <meta property="og:image" content="{image_url}">
            """
        )

        self.assertEqual(get_instagram_profile_photo_url("jessakainajj"), image_url)

    @patch("photos.requests.get")
    def test_rejects_fallback_page(self, mock_get):
        mock_get.return_value = instagram_response(
            """
            <meta property="og:url" content="https://www.instagram.com/">
            <meta property="og:image" content="https://static.cdninstagram.com/logo.png">
            """
        )

        with self.assertRaisesRegex(Exception, "did not return profile metadata"):
            get_instagram_profile_photo_url("jessakainajj")

    @patch("photos.requests.get")
    def test_rejects_non_profile_image(self, mock_get):
        mock_get.return_value = instagram_response(
            """
            <meta property="og:url" content="https://www.instagram.com/jessakainajj/">
            <meta property="og:image" content="https://static.cdninstagram.com/logo.png">
            """
        )

        with self.assertRaisesRegex(Exception, "returned a non-profile image"):
            get_instagram_profile_photo_url("jessakainajj")


if __name__ == "__main__":
    unittest.main()

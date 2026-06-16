import os
import sys
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")),
)

from constants import ADULT, BLACK, HEAVY, MALE, MIDDLE  # noqa: E402
from extensions import db  # noqa: E402
from models import (  # noqa: E402
    Athlete,
    Division,
    Event,
    Match,
    MatchParticipant,
    Team,
    YoutubeMatchVideo,
)
from normalize import normalize  # noqa: E402
from test_db import TestDbMixin  # noqa: E402

import youtube_match_import_lib as lib  # noqa: E402


class PureFunctionTestCase(unittest.TestCase):
    RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>yt:video:xSNMFhpTSv4</id>
    <yt:videoId>xSNMFhpTSv4</yt:videoId>
    <title>Lucas Calado vs Zenon Cruz Jr / Charlotte Spring Open 2026</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=xSNMFhpTSv4"/>
    <published>2026-06-15T13:45:00+00:00</published>
    <updated>2026-06-15T14:45:00+00:00</updated>
    <media:group>
      <media:title>Lucas Calado vs Zenon Cruz Jr / Charlotte Spring Open 2026</media:title>
      <media:description>ADULT / BLACK-BELT / MALE / HEAVY - FINAL</media:description>
      <media:thumbnail url="https://i.ytimg.com/vi/xSNMFhpTSv4/hqdefault.jpg"/>
    </media:group>
  </entry>
</feed>
    """
    CHANNEL_DATA = {
        "contents": [
            {
                "lockupViewModel": {
                    "contentId": "xSNMFhpTSv4",
                    "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                    "contentImage": {
                        "thumbnailViewModel": {
                            "image": {
                                "sources": [
                                    {
                                        "url": "https://i.ytimg.com/small.jpg",
                                        "width": 120,
                                    },
                                    {
                                        "url": "https://i.ytimg.com/large.jpg",
                                        "width": 640,
                                    },
                                ]
                            }
                        }
                    },
                    "metadata": {
                        "lockupMetadataViewModel": {
                            "title": {
                                "content": (
                                    "Lucas Calado vs Zenon Cruz Jr / "
                                    "Charlotte Spring Open 2026"
                                )
                            },
                            "metadata": {
                                "contentMetadataViewModel": {
                                    "metadataRows": [
                                        {
                                            "metadataParts": [
                                                {"text": {"content": "78 views"}},
                                                {
                                                    "text": {"content": "2 weeks ago"},
                                                    "accessibilityLabel": "2 weeks ago",
                                                },
                                            ]
                                        }
                                    ]
                                }
                            },
                        }
                    },
                    "rendererContext": {
                        "commandContext": {
                            "onTap": {
                                "innertubeCommand": {
                                    "commandMetadata": {
                                        "webCommandMetadata": {
                                            "url": "/watch?v=xSNMFhpTSv4"
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            }
        ]
    }

    def test_parse_youtube_match_title(self):
        parsed = lib.parse_youtube_match_title(
            "Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026"
        )
        self.assertEqual(parsed.athlete1, "Igor Carlos")
        self.assertEqual(parsed.athlete2, "Hiago Barra")
        self.assertEqual(parsed.event_name, "Charlotte Spring Open 2026")

    def test_parse_youtube_match_title_rejects_promos(self):
        self.assertIsNone(lib.parse_youtube_match_title("Mia Funegra Returns to Japan"))

    def test_parse_youtube_division_description(self):
        parsed = lib.parse_youtube_division_description(
            "ADULT / BLACK-BELT / MALE / MEDIUM-HEAVY - FINAL"
        )
        self.assertEqual(parsed.age, ADULT)
        self.assertEqual(parsed.belt, BLACK)
        self.assertEqual(parsed.gender, MALE)
        self.assertEqual(parsed.weight, "Medium Heavy")
        self.assertEqual(parsed.round_name, "FINAL")

    def test_parse_rss_uploads_xml(self):
        uploads = lib.parse_rss_uploads_xml(self.RSS_XML)
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0].youtube_video_id, "xSNMFhpTSv4")
        self.assertEqual(
            uploads[0].title,
            "Lucas Calado vs Zenon Cruz Jr / Charlotte Spring Open 2026",
        )
        self.assertEqual(uploads[0].url, "https://www.youtube.com/watch?v=xSNMFhpTSv4")
        self.assertEqual(
            uploads[0].description, "ADULT / BLACK-BELT / MALE / HEAVY - FINAL"
        )
        self.assertEqual(
            uploads[0].thumbnail_url,
            "https://i.ytimg.com/vi/xSNMFhpTSv4/hqdefault.jpg",
        )
        self.assertEqual(uploads[0].published_at, datetime(2026, 6, 15, 13, 45, 0))
        self.assertEqual(uploads[0].updated_at, datetime(2026, 6, 15, 14, 45, 0))

    def test_fetch_rss_uploads_uses_browser_user_agent(self):
        class Response:
            content = self.RSS_XML

            def raise_for_status(self):
                return None

        with patch(
            "youtube_match_import_lib.requests.get", return_value=Response()
        ) as mock_get:
            lib.fetch_rss_uploads()

        _, kwargs = mock_get.call_args
        self.assertIn("Mozilla/5.0", kwargs["headers"]["User-Agent"])

    def test_parse_channel_uploads_data_uses_relative_publish_time(self):
        uploads = lib.parse_channel_uploads_data(
            self.CHANNEL_DATA, now=datetime(2026, 6, 16, 12, 0, 0)
        )
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0].youtube_video_id, "xSNMFhpTSv4")
        self.assertEqual(
            uploads[0].title,
            "Lucas Calado vs Zenon Cruz Jr / Charlotte Spring Open 2026",
        )
        self.assertEqual(uploads[0].url, "https://www.youtube.com/watch?v=xSNMFhpTSv4")
        self.assertEqual(uploads[0].thumbnail_url, "https://i.ytimg.com/large.jpg")
        self.assertEqual(uploads[0].published_at, datetime(2026, 6, 2, 12, 0, 0))


class YoutubeMatchImportDbTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        event = Event(
            id=uuid.uuid4(),
            ibjjf_id="charlotte-2026",
            name="Charlotte Spring International Open IBJJF Jiu-Jitsu Championship 2026",
            normalized_name=normalize(
                "Charlotte Spring International Open IBJJF Jiu-Jitsu Championship 2026"
            ),
            slug="charlotte-spring-2026",
        )
        middle = Division(
            id=uuid.uuid4(),
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=MIDDLE,
        )
        heavy = Division(
            id=uuid.uuid4(),
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=HEAVY,
        )
        team = Team(id=uuid.uuid4(), name="Team", normalized_name=normalize("Team"))
        athletes = [
            Athlete(
                id=uuid.uuid4(),
                name=name,
                normalized_name=normalize(name),
                slug=normalize(name).replace(" ", "-"),
            )
            for name in [
                "Igor Carlos",
                "Hiago Barra",
                "Lucas Calado",
                "Zenon Cruz Jr",
            ]
        ]
        db.session.add_all([event, middle, heavy, team, *athletes])
        db.session.flush()

        cls.event_id = event.id
        cls.middle_match_id = uuid.uuid4()
        cls.heavy_match_id = uuid.uuid4()
        middle_match = Match(
            id=cls.middle_match_id,
            happened_at=datetime(2026, 6, 14),
            event_id=event.id,
            division_id=middle.id,
            rated=True,
            rated_winner_only=False,
        )
        heavy_match = Match(
            id=cls.heavy_match_id,
            happened_at=datetime(2026, 6, 14),
            event_id=event.id,
            division_id=heavy.id,
            rated=True,
            rated_winner_only=False,
        )
        db.session.add_all([middle_match, heavy_match])
        db.session.flush()

        pairs = [
            (middle_match.id, athletes[0], True),
            (middle_match.id, athletes[1], False),
            (heavy_match.id, athletes[2], True),
            (heavy_match.id, athletes[3], False),
        ]
        participants = []
        for idx, (match_id, athlete, red) in enumerate(pairs):
            participants.append(
                MatchParticipant(
                    id=uuid.uuid4(),
                    match_id=match_id,
                    athlete_id=athlete.id,
                    team_id=team.id,
                    seed=idx + 1,
                    red=red,
                    winner=red,
                    start_rating=1500,
                    end_rating=1510,
                    start_match_count=0,
                    end_match_count=1,
                )
            )
        db.session.add_all(participants)
        db.session.commit()

    def test_upsert_youtube_match_videos_inserts_and_updates(self):
        with self.app_module.app.app_context():
            upload = lib.YoutubeUpload(
                youtube_video_id="abc123",
                url="https://www.youtube.com/watch?v=abc123",
                title="Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026",
                description="ADULT / BLACK-BELT / MALE / MIDDLE - FINAL",
                published_at=datetime(2026, 6, 15),
                updated_at=datetime(2026, 6, 15),
                thumbnail_url="https://img.example/thumb.jpg",
            )
            inserted, updated = lib.upsert_youtube_match_videos(db.session, [upload])
            self.assertEqual((inserted, updated), (1, 0))

            changed = lib.YoutubeUpload(
                youtube_video_id="abc123",
                url="https://www.youtube.com/watch?v=abc123",
                title="Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026",
                description="ADULT / BLACK-BELT / MALE / MIDDLE - SEMIFINAL",
                published_at=datetime(2026, 6, 15),
                updated_at=datetime(2026, 6, 16),
                thumbnail_url="https://img.example/thumb2.jpg",
            )
            inserted, updated = lib.upsert_youtube_match_videos(db.session, [changed])
            self.assertEqual((inserted, updated), (0, 1))
            row = YoutubeMatchVideo.query.filter_by(youtube_video_id="abc123").one()
            self.assertIn("SEMIFINAL", row.description)

    def test_channel_backfill_does_not_overwrite_rss_metadata(self):
        with self.app_module.app.app_context():
            rss_upload = lib.YoutubeUpload(
                youtube_video_id="preserve123",
                url="https://www.youtube.com/watch?v=preserve123",
                title="Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026",
                description="ADULT / BLACK-BELT / MALE / MIDDLE - FINAL",
                published_at=datetime(2026, 6, 15, 13, 45),
                updated_at=datetime(2026, 6, 15, 14, 45),
                thumbnail_url="https://img.example/rss.jpg",
            )
            lib.upsert_youtube_match_videos(db.session, [rss_upload])

            channel_upload = lib.YoutubeUpload(
                youtube_video_id="preserve123",
                url="https://www.youtube.com/watch?v=preserve123",
                title="Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026",
                description=None,
                published_at=datetime(2026, 6, 1),
                updated_at=None,
                thumbnail_url="https://img.example/channel.jpg",
            )
            inserted, updated = lib.upsert_youtube_match_videos(
                db.session, [channel_upload]
            )
            self.assertEqual((inserted, updated), (0, 1))
            row = YoutubeMatchVideo.query.filter_by(
                youtube_video_id="preserve123"
            ).one()
            self.assertEqual(
                row.description, "ADULT / BLACK-BELT / MALE / MIDDLE - FINAL"
            )
            self.assertEqual(row.published_at, datetime(2026, 6, 15, 13, 45))
            self.assertEqual(row.thumbnail_url, "https://img.example/rss.jpg")

    def test_auto_update_combines_channel_and_rss_with_rss_metadata(self):
        with self.app_module.app.app_context():
            channel_overlap = lib.YoutubeUpload(
                youtube_video_id="auto_overlap",
                url="https://www.youtube.com/watch?v=auto_overlap",
                title="Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026",
                description=None,
                published_at=datetime(2026, 6, 1),
                updated_at=None,
                thumbnail_url="https://img.example/channel.jpg",
            )
            channel_only = lib.YoutubeUpload(
                youtube_video_id="auto_channel_only",
                url="https://www.youtube.com/watch?v=auto_channel_only",
                title="Lucas Calado vs Zenon Cruz Jr / Charlotte Spring Open 2026",
                description=None,
                published_at=datetime(2026, 6, 2),
                updated_at=None,
                thumbnail_url="https://img.example/channel-only.jpg",
            )
            rss_overlap = lib.YoutubeUpload(
                youtube_video_id="auto_overlap",
                url="https://www.youtube.com/watch?v=auto_overlap",
                title="Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026",
                description="ADULT / BLACK-BELT / MALE / MIDDLE - FINAL",
                published_at=datetime(2026, 6, 15, 13, 45),
                updated_at=datetime(2026, 6, 15, 14, 45),
                thumbnail_url="https://img.example/rss.jpg",
            )

            with patch(
                "youtube_match_import_lib.fetch_channel_uploads",
                return_value=[channel_overlap, channel_only],
            ) as mock_channel, patch(
                "youtube_match_import_lib.fetch_rss_uploads",
                return_value=[rss_overlap],
            ):
                inserted, updated = lib.update_youtube_match_videos(
                    db.session, source="auto", max_pages=2
                )

            mock_channel.assert_called_once_with(max_pages=2)
            self.assertEqual((inserted, updated), (2, 0))
            overlap = YoutubeMatchVideo.query.filter_by(
                youtube_video_id="auto_overlap"
            ).one()
            self.assertEqual(
                overlap.description, "ADULT / BLACK-BELT / MALE / MIDDLE - FINAL"
            )
            self.assertEqual(overlap.published_at, datetime(2026, 6, 15, 13, 45))
            channel_row = YoutubeMatchVideo.query.filter_by(
                youtube_video_id="auto_channel_only"
            ).one()
            self.assertIsNone(channel_row.description)
            self.assertEqual(channel_row.published_at, datetime(2026, 6, 2))

    def test_scan_youtube_match_videos_matches_correct_match(self):
        with self.app_module.app.app_context():
            db.session.get(Match, self.middle_match_id).video_link = None
            video = YoutubeMatchVideo(
                youtube_video_id="middle123",
                url="https://www.youtube.com/watch?v=middle123",
                title="Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026",
                description="ADULT / BLACK-BELT / MALE / MIDDLE - FINAL",
                published_at=datetime(2026, 6, 15),
                updated_at=datetime(2026, 6, 15),
                scraped_at=datetime(2026, 6, 16),
            )
            db.session.add(video)
            db.session.commit()

            entries = lib.scan_youtube_match_videos(
                db.session,
                datetime(2026, 6, 1),
                datetime(2026, 6, 30, 23, 59, 59),
            )
            entry = [e for e in entries if e["video"].youtube_video_id == "middle123"][
                0
            ]
            self.assertEqual(entry["status"], "matched")
            self.assertEqual(entry["matched_candidate"].match.id, self.middle_match_id)

    def test_import_youtube_match_video_links_sets_match_video_link(self):
        with self.app_module.app.app_context():
            db.session.get(Match, self.middle_match_id).video_link = None
            video = YoutubeMatchVideo(
                id=uuid.uuid4(),
                youtube_video_id="import123",
                url="https://www.youtube.com/watch?v=import123",
                title="Igor Carlos vs Hiago Barra / Charlotte Spring Open 2026",
                description="ADULT / BLACK-BELT / MALE / MIDDLE - FINAL",
                published_at=datetime.utcnow(),
                scraped_at=datetime.utcnow(),
            )
            db.session.add(video)
            db.session.commit()

            imported, skipped, errors = lib.import_youtube_match_video_links(
                db.session, [(video.id, self.middle_match_id)]
            )
            self.assertEqual((imported, skipped, errors), (1, 0, []))
            match = db.session.get(Match, self.middle_match_id)
            self.assertEqual(
                match.video_link, "https://www.youtube.com/watch?v=import123"
            )
            self.assertEqual(video.imported_match_id, self.middle_match_id)
            self.assertIsNotNone(video.imported_at)


if __name__ == "__main__":
    unittest.main()

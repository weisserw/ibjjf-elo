import uuid
import json
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    Float,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from extensions import db


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)


class Event(db.Model):
    __tablename__ = "events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ibjjf_id = Column(String, unique=True, nullable=True)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)
    slug = Column(String, nullable=False)

    __table_args__ = (
        Index("ix_events_ibjjf_id", "ibjjf_id"),
        Index("ix_events_normalized_name", "normalized_name"),
        UniqueConstraint(
            "slug",
            name="uq_event_slug",
        ),
    )


class Division(db.Model):
    __tablename__ = "divisions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gi = Column(Boolean, nullable=False)
    gender = Column(String, nullable=False)
    age = Column(String, nullable=False)
    belt = Column(String, nullable=False)
    weight = Column(String, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "gi": self.gi,
            "gender": self.gender,
            "age": self.age,
            "belt": self.belt,
            "weight": self.weight,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), cls=JSONEncoder)

    __table_args__ = (
        Index("ix_divisions_all", "gi", "gender", "age", "belt", "weight"),
        Index("ix_divisions_age_covering", "age", "id"),
    )

    def display_name(self):
        return f"{self.age} / {self.gender} / {self.belt} / {self.weight}"


class Athlete(db.Model):
    __tablename__ = "athletes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ibjjf_id = Column(String, unique=True, nullable=True)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)
    instagram_profile = Column(String, nullable=True)
    country = Column(String, nullable=True)
    country_note = Column(String, nullable=True)
    country_note_pt = Column(String, nullable=True)
    profile_image_saved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    personal_name = Column(String, nullable=True)
    normalized_personal_name = Column(String, nullable=True)
    slug = Column(String, nullable=False)

    __table_args__ = (
        Index("ix_athletes_ibjjf_id", "ibjjf_id"),
        Index("ix_athletes_normalized_name_covering", "normalized_name", "id"),
        UniqueConstraint(
            "slug",
            name="uq_athlete_slug",
        ),
    )


class Team(db.Model):
    __tablename__ = "teams"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)

    __table_args__ = (Index("ix_teams_normalized_name", "normalized_name"),)


class Medal(db.Model):
    __tablename__ = "medals"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    happened_at = Column(DateTime, nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    division_id = Column(UUID(as_uuid=True), ForeignKey("divisions.id"), nullable=False)
    athlete_id = Column(UUID(as_uuid=True), ForeignKey("athletes.id"), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    place = Column(Integer, nullable=False)
    default_gold = Column(Boolean, nullable=False)

    division = relationship("Division", lazy="select", viewonly=True)
    athlete = relationship("Athlete", lazy="select", viewonly=True)
    team = relationship("Team", lazy="select", viewonly=True)
    event = relationship("Event", lazy="select", viewonly=True)

    __table_args__ = (
        Index("ix_medals_event_id", "event_id"),
        Index("ix_medals_division_id", "division_id"),
        Index("ix_medals_athlete_id", "athlete_id"),
        Index("ix_medals_team_id", "team_id"),
        Index("ix_medals_happened_at", "happened_at"),
    )


class Match(db.Model):
    __tablename__ = "matches"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    happened_at = Column(DateTime, nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    division_id = Column(UUID(as_uuid=True), ForeignKey("divisions.id"), nullable=False)
    rated = Column(Boolean, nullable=False)
    rated_winner_only = Column(Boolean, nullable=True)
    match_number = Column(Integer, nullable=True)
    match_location = Column(String, nullable=True)
    fight_number = Column(Integer, nullable=True)

    participants = relationship("MatchParticipant", lazy="select", viewonly=True)
    division = relationship("Division", lazy="select", viewonly=True)
    event = relationship("Event", lazy="select", viewonly=True)

    __table_args__ = (
        Index("ix_matches_event_id", "event_id"),
        Index("ix_matches_division_id", "division_id"),
        Index("ix_matches_happened_at", "happened_at"),
        Index("ix_matches_division_id_covering", "division_id", "happened_at", "id"),
    )


class MatchParticipant(db.Model):
    __tablename__ = "match_participants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    athlete_id = Column(UUID(as_uuid=True), ForeignKey("athletes.id"), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    seed = Column(Integer, nullable=False)
    red = Column(Boolean, nullable=False)
    winner = Column(Boolean, nullable=False)
    note = Column(Text)
    rating_note = Column(Text)
    start_rating = Column(Float, nullable=False)
    end_rating = Column(Float, nullable=False)
    weight_for_open = Column(String, nullable=True)
    start_match_count = Column(Integer, nullable=False)
    end_match_count = Column(Integer, nullable=False)

    athlete = relationship("Athlete", lazy="select", viewonly=True)
    match = relationship("Match", lazy="select", viewonly=True)
    team = relationship("Team", lazy="select", viewonly=True)

    def to_dict(self):
        return {
            "id": self.id,
            "match_id": self.match_id,
            "athlete_id": self.athlete_id,
            "team_id": self.team_id,
            "seed": self.seed,
            "red": self.red,
            "winner": self.winner,
            "note": self.note,
            "start_rating": self.start_rating,
            "end_rating": self.end_rating,
            "weight_for_open": self.weight_for_open,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), cls=JSONEncoder)

    __table_args__ = (
        Index("ix_match_participants_match_id", "match_id"),
        Index("ix_match_participants_athlete_id", "athlete_id"),
        Index("ix_match_participants_team_id", "team_id"),
        Index(
            "ix_match_participants_match_id_covering", "match_id", "athlete_id", "id"
        ),
    )


Index(
    "ix_match_participants_winners",
    MatchParticipant.match_id,
    MatchParticipant.athlete_id,
    postgresql_where=MatchParticipant.winner == True,
)
Index(
    "ix_match_participants_losers",
    MatchParticipant.match_id,
    MatchParticipant.athlete_id,
    postgresql_where=MatchParticipant.winner == False,
)


class AthleteRatingAverage(db.Model):
    __tablename__ = "athlete_rating_averages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gender = Column(String, nullable=False)
    age = Column(String, nullable=False)
    belt = Column(String, nullable=False)
    gi = Column(Boolean, nullable=False)
    weight = Column(String, nullable=True)
    avg_rating = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "gender",
            "age",
            "belt",
            "gi",
            "weight",
            name="uq_athlete_rating_averages_all",
        ),
    )


class AthleteRating(db.Model):
    __tablename__ = "athlete_ratings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    athlete_id = Column(UUID(as_uuid=True), ForeignKey("athletes.id"), nullable=False)
    gender = Column(String, nullable=False)
    age = Column(String, nullable=False)
    belt = Column(String, nullable=False)
    gi = Column(Boolean, nullable=False)
    weight = Column(String, nullable=True)
    rating = Column(Float, nullable=False)
    match_happened_at = Column(DateTime, nullable=False)
    rank = Column(Integer, nullable=True)
    percentile = Column(Float, nullable=True)
    match_count = Column(Integer, nullable=False)
    previous_rating = Column(Float, nullable=True)
    previous_rank = Column(Integer, nullable=True)
    previous_match_count = Column(Integer, nullable=True)
    previous_percentile = Column(Float, nullable=True)

    athlete = relationship("Athlete", lazy="select", viewonly=True)

    __table_args__ = (
        Index("ix_athlete_ratings_athlete_id", "athlete_id"),
        Index("ix_athlete_ratings_rating", "rating"),
        Index("ix_athlete_ratings_all", "gender", "age", "belt", "gi", "weight"),
        UniqueConstraint(
            "athlete_id",
            "gender",
            "age",
            "gi",
            "weight",
            name="uq_athlete_ratings_athlete_gender_age_gi",
        ),
    )


class BracketPage(db.Model):
    __tablename__ = "bracket_pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    saved_at = Column(DateTime, nullable=False)
    link = Column(String, nullable=False)
    html = Column(Text, nullable=False)

    __table_args__ = (
        Index("ix_bracket_pages_saved_at", "saved_at"),
        Index("ix_bracket_pages_link", "link"),
    )


class RegistrationLink(db.Model):
    __tablename__ = "registration_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    event_id = Column(String, nullable=True)
    normalized_name = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    link = Column(String, nullable=False)
    hidden = Column(Boolean, nullable=True)
    event_start_date = Column(DateTime, nullable=True)
    event_end_date = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_registration_links_link", "link", unique=True),
        Index("ix_registration_links_event_start_date", "event_start_date"),
        Index("ix_registration_links_event_end_date", "event_end_date"),
    )


class RegistrationLinkCompetitor(db.Model):
    __tablename__ = "registration_link_competitors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    registration_link_id = Column(
        UUID(as_uuid=True),
        ForeignKey("registration_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    athlete_name = Column(String, nullable=False)
    division_id = Column(UUID(as_uuid=True), ForeignKey("divisions.id"), nullable=False)

    __table_args__ = (
        Index(
            "ix_registration_link_competitors_all",
            "athlete_name",
            "registration_link_id",
            "division_id",
        ),
    )


class Suspension(db.Model):
    __tablename__ = "suspensions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    athlete_name = Column(String, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)


class LiveRating(db.Model):
    __tablename__ = "live_ratings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    athlete_id = Column(UUID(as_uuid=True), ForeignKey("athletes.id"), nullable=False)
    rating = Column(Float, nullable=False)
    match_count = Column(Integer, nullable=False)
    gi = Column(Boolean, nullable=False)
    happened_at = Column(DateTime, nullable=False)
    division_id = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_live_ratings_athlete_id", "athlete_id"),)


class ManualPromotions(db.Model):
    __tablename__ = "manual_promotions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    athlete_id = Column(UUID(as_uuid=True), ForeignKey("athletes.id"), nullable=False)
    belt = Column(String, nullable=False)
    promoted_at = Column(DateTime, nullable=False)

    __table_args__ = (Index("ix_manual_promotions_athlete_id", "athlete_id"),)

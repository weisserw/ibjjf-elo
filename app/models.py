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
from sqlalchemy.dialects.postgresql import UUID
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

    __table_args__ = (
        Index("ix_events_ibjjf_id", "ibjjf_id"),
        Index("ix_events_name", "name"),
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
    )

    def display_name(self):
        return f"{self.age} / {self.gender} / {self.belt} / {self.weight}"


class Athlete(db.Model):
    __tablename__ = "athletes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ibjjf_id = Column(String, unique=True, nullable=True)
    name = Column(String, nullable=False)

    __table_args__ = (
        Index("ix_athletes_ibjjf_id", "ibjjf_id"),
        Index("ix_athletes_name", "name"),
    )


class Team(db.Model):
    __tablename__ = "teams"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)

    __table_args__ = (Index("ix_teams_name", "name"),)


class DefaultGold(db.Model):
    __tablename__ = "default_golds"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    happened_at = Column(DateTime, nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    division_id = Column(UUID(as_uuid=True), ForeignKey("divisions.id"), nullable=False)
    athlete_id = Column(UUID(as_uuid=True), ForeignKey("athletes.id"), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)

    division = relationship("Division", lazy="joined", viewonly=True)
    athlete = relationship("Athlete", lazy="joined", viewonly=True)
    event = relationship("Event", lazy="joined", viewonly=True)

    __table_args__ = (
        Index("ix_default_golds_event_id", "event_id"),
        Index("ix_default_golds_division_id", "division_id"),
        Index("ix_default_golds_athlete_id", "athlete_id"),
        Index("ix_default_golds_team_id", "team_id"),
        Index("ix_default_golds_happened_at", "happened_at"),
    )


class Match(db.Model):
    __tablename__ = "matches"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    happened_at = Column(DateTime, nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    division_id = Column(UUID(as_uuid=True), ForeignKey("divisions.id"), nullable=False)
    rated = Column(Boolean, nullable=False)

    participants = relationship("MatchParticipant", lazy="joined", viewonly=True)
    division = relationship("Division", lazy="joined", viewonly=True)
    event = relationship("Event", lazy="joined", viewonly=True)

    __table_args__ = (
        Index("ix_matches_event_id", "event_id"),
        Index("ix_matches_division_id", "division_id"),
        Index("ix_matches_happened_at", "happened_at"),
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

    athlete = relationship("Athlete", lazy="joined", viewonly=True)
    match = relationship("Match", lazy="joined", viewonly=True)

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

    athlete = relationship("Athlete", lazy="joined", viewonly=True)

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

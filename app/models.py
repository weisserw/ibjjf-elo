import uuid
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, Text, Float, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from extensions import db

class Event(db.Model):
    __tablename__ = 'events'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ibjjf_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)

    __table_args__ = (
        Index('ix_events_ibjjf_id', 'ibjjf_id'),
        Index('ix_events_name', 'name'),
    )

class Division(db.Model):
    __tablename__ = 'divisions'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gi = Column(Boolean, nullable=False)
    gender = Column(String, nullable=False)
    age = Column(String, nullable=False)
    belt = Column(String, nullable=False)
    weight = Column(String, nullable=False)

    __table_args__ = (
        Index('ix_divisions_all', 'gi', 'gender', 'age', 'belt', 'weight'),
    )

    def display_name(self):
        return f'{self.age} / {self.gender} / {self.belt} / {self.weight}'

class Athlete(db.Model):
    __tablename__ = 'athletes'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ibjjf_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)

    __table_args__ = (
        Index('ix_athletes_ibjjf_id', 'ibjjf_id'),
        Index('ix_athletes_name', 'name'),
    )

class Team(db.Model):
    __tablename__ = 'teams'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)

    __table_args__ = (
        Index('ix_teams_name', 'name'),
    )

class Match(db.Model):
    __tablename__ = 'matches'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    happened_at = Column(DateTime, nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey('events.id'), nullable=False)
    division_id = Column(UUID(as_uuid=True), ForeignKey('divisions.id'), nullable=False)
    rated = Column(Boolean, nullable=False)

    participants = relationship("MatchParticipant", lazy='joined')
    division = relationship("Division", lazy='joined')
    event = relationship("Event", lazy='joined')

    __table_args__ = (
        Index('ix_matches_event_id', 'event_id'),
        Index('ix_matches_division_id', 'division_id'),
        Index('ix_matches_happened_at', 'happened_at'),
    )

class MatchParticipant(db.Model):
    __tablename__ = 'match_participants'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    athlete_id = Column(UUID(as_uuid=True), ForeignKey('athletes.id'), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    seed = Column(Integer, nullable=False)
    red = Column(Boolean, nullable=False)
    winner = Column(Boolean, nullable=False)
    note = Column(Text)
    start_rating = Column(Float, nullable=False)
    end_rating = Column(Float, nullable=False)

    athlete = relationship("Athlete", lazy='joined')

    __table_args__ = (
        Index('ix_match_participants_match_id', 'match_id'),
        Index('ix_match_participants_athlete_id', 'athlete_id'),
        Index('ix_match_participants_team_id', 'team_id'),
    )

class CurrentRating(db.Model):
    __tablename__ = 'current_ratings'
    athlete_id = Column(UUID(as_uuid=True), ForeignKey('athletes.id'), primary_key=True)
    rating = Column(Float, nullable=False)
    gender = Column(String, nullable=False)
    age = Column(String, nullable=False)
    belt = Column(String, nullable=False)
    gi = Column(Boolean, nullable=False)
    match_happened_at = Column(DateTime, nullable=False)

    athlete = relationship("Athlete", lazy='joined')

    __table_args__ = (
        Index('ix_current_ratings_athlete_id', 'athlete_id'),
        Index('ix_current_ratings_rating', 'rating'),
        Index('ix_current_ratings_all', 'gender', 'age', 'belt', 'gi'),
    )

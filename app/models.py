import uuid
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, Text, Float, Index
from sqlalchemy.dialects.postgresql import UUID
from app import db

class Event(db.Model):
    __tablename__ = 'events'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ibjjf_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)

class Division(db.Model):
    __tablename__ = 'divisions'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gi = Column(Boolean, nullable=False)
    gender = Column(String, nullable=False)
    age = Column(String, nullable=False)
    belt = Column(String, nullable=False)
    weight = Column(String, nullable=False)

class Athlete(db.Model):
    __tablename__ = 'athletes'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ibjjf_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)

class Team(db.Model):
    __tablename__ = 'teams'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)

class Match(db.Model):
    __tablename__ = 'matches'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    happened_at = Column(DateTime, nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey('events.id'), nullable=False)
    division_id = Column(UUID(as_uuid=True), ForeignKey('divisions.id'), nullable=False)

    __table_args__ = (
        Index('ix_event_id', 'event_id'),
        Index('ix_division_id', 'division_id'),
    )

class MatchParticipant(db.Model):
    __tablename__ = 'match_participants'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    athlete_id = Column(UUID(as_uuid=True), ForeignKey('athletes.id'), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    seed = Column(Integer, nullable=False)
    winner = Column(Boolean, nullable=False)
    note = Column(Text)
    start_rating = Column(Float, nullable=False)
    end_rating = Column(Float, nullable=False)

    __table_args__ = (
        Index('ix_match_id', 'match_id'),
        Index('ix_athlete_id', 'athlete_id'),
        Index('ix_team_id', 'team_id'),
    )

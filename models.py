from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String(10), nullable=False)
    county = Column(String(50), nullable=False)
    town = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    messages = relationship("Message", back_populates="user")
    more_details = relationship("UserMoreDetails", back_populates="user", uselist=False)
    self_description = relationship("UserSelfDescription", back_populates="user", uselist=False)
    match_requests = relationship("MatchRequest", back_populates="requesting_user")
    match_batches = relationship("MatchBatch", back_populates="user")

class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('match_requests.id'), nullable=False)
    matched_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    displayed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    match_request = relationship("MatchRequest", back_populates="matches")
    matched_user = relationship("User")

class UserMoreDetails(Base):
    __tablename__ = "usermoredetails"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    level_of_education = Column(String(100))
    profession = Column(String(100))
    marital_status = Column(String(50))
    religion = Column(String(50))
    ethnicity = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="more_details")

class UserSelfDescription(Base):
    __tablename__ = 'userselfdescription'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="self_description")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    message_direction = Column(String(10), nullable=False)  # 'incoming' or 'outgoing'
    message_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="messages")

class MatchRequest(Base):
    __tablename__ = "match_requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    age_range = Column(String(20), nullable=False)
    county = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    requesting_user = relationship("User", back_populates="match_requests")
    matches = relationship("Match", back_populates="match_request")

class MatchBatch(Base):
    __tablename__ = "match_batches"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('match_requests.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    total_matches = Column(Integer, nullable=False)
    matches_shown = Column(Integer, nullable=False, default=0)
    match_data = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    match_request = relationship("MatchRequest")
    user = relationship("User", back_populates="match_batches")


from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class UserEvent(Base):
    __tablename__ = "user_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    article_id = Column(Integer, nullable=True)
    event_type = Column(String, nullable=False)  # view / like / skip
    dwell_time = Column(Float, default=0.0)  # seconds
    created_at = Column(DateTime, default=datetime.utcnow)

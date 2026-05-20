import uuid
import hashlib
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, LargeBinary
from sqlalchemy.sql import text
from ..db.session import Base, USE_SQLITE


def _new_binary_uuid() -> bytes:
    return uuid.uuid4().bytes


_CREATED_AT_DEFAULT = text("CURRENT_TIMESTAMP") if USE_SQLITE else text("convert_tz(now(),'UTC','+05:30')")


class SessionLog(Base):
    __tablename__ = "session_logs"

    session_id    = Column(LargeBinary(16), primary_key=True, default=_new_binary_uuid)
    user_id       = Column(LargeBinary(16), nullable=False)
    ip_address    = Column(String(45),   nullable=False)
    state         = Column(String(100),  nullable=True)
    city          = Column(String(100),  nullable=True)
    document_type = Column(String(30),   nullable=True)
    pdf_location  = Column(Text,         nullable=True)
    json_location = Column(Text,         nullable=True)
    created_at    = Column(DateTime,     server_default=_CREATED_AT_DEFAULT)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id                = Column(Integer,      primary_key=True, autoincrement=True)
    name              = Column(String(200),  nullable=False)
    email             = Column(String(255),  nullable=False)
    service           = Column(String(50),   nullable=False)
    token_hash        = Column(String(64),   nullable=False)
    access_granted_at = Column(DateTime,     nullable=False)
    access_expires_at = Column(DateTime,     nullable=False)
    expiry_days       = Column(Integer,      nullable=False, default=1)
    ip_address        = Column(String(45),   nullable=True)
    user_agent        = Column(String(512),  nullable=True)
    revoked           = Column(Boolean,      nullable=False, default=False)
    revoked_at        = Column(DateTime,     nullable=True)
    notes             = Column(Text,         nullable=True)
    created_at        = Column(DateTime,     server_default=_CREATED_AT_DEFAULT)

    @staticmethod
    def hash_token(raw_jwt: str) -> str:
        return hashlib.sha256(raw_jwt.encode()).hexdigest()

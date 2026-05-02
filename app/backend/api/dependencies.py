import logging
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.backend.core.config import settings
from app.backend.core.security import decode_access_token
from app.backend.db import session as db_session
from app.backend.services.auth_service import get_user_by_id

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield DB session with automatic rollback on error."""
    if db_session.SessionLocal is None:
        logger.error("[DB ERROR] SessionLocal not initialized")
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    async with db_session.SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.exception("[DB ERROR] Database transaction failed")
            raise HTTPException(status_code=500, detail="Database error")
        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.exception("[DB ERROR] Unexpected database error")
            raise HTTPException(status_code=500, detail="Database error")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
):
    """Get current authenticated user with safe token handling."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials, settings.JWT_SECRET_KEY)
    except ValueError as exc:
        logger.warning("[AUTH] Token decode failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    except Exception as e:
        logger.exception("[AUTH] Unexpected token decode error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    try:
        user = await get_user_by_id(session, int(user_id))
    except Exception as e:
        logger.exception("[AUTH] Failed to fetch user")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User lookup failed")

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

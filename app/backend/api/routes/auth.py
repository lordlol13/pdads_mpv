from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.api.dependencies import get_current_user, get_db_session
from app.backend.core.config import settings
from app.backend.schemas.auth import (
    AuthForgotPasswordRequest,
    AuthForgotPasswordResponse,
    AuthCheckAvailabilityRequest,
    AuthCheckAvailabilityResponse,
    OAuthProvidersResponse,
    AuthLoginRequest,
    AuthRegisterCompleteRequest,
    AuthRegisterRequest,
    AuthRegisterStartRequest,
    AuthRegisterStartResponse,
    AuthVerifyCodeRequest,
    AuthVerifyCodeResponse,
    AuthResetPasswordRequest,
    TokenResponse,
    UserPublic,
)
from app.backend.services.email_service import send_verification_code
from app.backend.services.auth_service import (
    authenticate_user,
    check_email_exists,
    check_username_exists,
    complete_verified_registration,
    create_registration_verification,
    create_password_reset_request,
    issue_access_token,
    register_user,
    reset_password_with_code,
    verify_registration_code,
)
from app.backend.services.oauth_service import (
    begin_oauth_login,
    build_oauth_error_redirect,
    build_oauth_success_redirect,
    get_enabled_oauth_providers,
    handle_oauth_callback,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/check-availability", response_model=AuthCheckAvailabilityResponse)
async def check_availability(
    payload: AuthCheckAvailabilityRequest,
    session: AsyncSession = Depends(get_db_session),
):
    username_exists = None
    email_exists = None
    if payload.username:
        username_exists = await check_username_exists(session, payload.username)
    if payload.email:
        email_exists = await check_email_exists(session, payload.email)
    return AuthCheckAvailabilityResponse(username_exists=username_exists, email_exists=email_exists)


@router.post("/register/start", response_model=AuthRegisterStartResponse)
async def register_start(
    payload: AuthRegisterStartRequest,
    session: AsyncSession = Depends(get_db_session),
):
    data = await create_registration_verification(
        session,
        username=payload.username,
        email=payload.email,
        password=payload.password,
    )

    sent = send_verification_code(payload.email, data["code"])
    if not sent and not settings.AUTH_DEBUG_RETURN_CODE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery is not configured. Contact support or enable AUTH_DEBUG_RETURN_CODE for testing.",
        )

    debug_code = data["code"] if settings.AUTH_DEBUG_RETURN_CODE else None

    return AuthRegisterStartResponse(
        verification_id=data["verification_id"],
        expires_in_seconds=data["expires_in_seconds"],
        debug_code=debug_code,
    )


@router.post("/register/verify", response_model=AuthVerifyCodeResponse)
async def register_verify(
    payload: AuthVerifyCodeRequest,
    session: AsyncSession = Depends(get_db_session),
):
    result = await verify_registration_code(session, payload.verification_id, payload.code)
    return AuthVerifyCodeResponse(**result)


@router.post("/register/complete", response_model=UserPublic)
async def register_complete(
    payload: AuthRegisterCompleteRequest,
    session: AsyncSession = Depends(get_db_session),
):
    user = await complete_verified_registration(
        session,
        verification_id=payload.verification_id,
        interests=payload.interests,
        custom_interests=payload.custom_interests,
        profession=payload.profession,
        country_code=payload.country_code,
        country_name=payload.country_name,
        city=payload.city,
        region_code=payload.region_code,
    )
    return UserPublic(**user)


@router.post("/register", response_model=UserPublic)
async def register(payload: AuthRegisterRequest, session: AsyncSession = Depends(get_db_session)):
    user = await register_user(
        session,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        location=payload.location,
        interests=payload.interests,
        country_code=payload.country_code,
        region_code=payload.region_code,
    )
    return UserPublic(**user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: AuthLoginRequest, session: AsyncSession = Depends(get_db_session)):
    user = await authenticate_user(session, payload.identifier, payload.password)
    token = issue_access_token(user)
    return TokenResponse(access_token=token, expires_in_minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)


@router.get("/oauth/providers", response_model=OAuthProvidersResponse)
async def oauth_providers():
    return OAuthProvidersResponse(providers=get_enabled_oauth_providers())


@router.get("/oauth/{provider}/login")
async def oauth_login(provider: str, request: Request):
    return await begin_oauth_login(request, provider)


@router.get("/oauth/{provider}/callback", name="oauth_callback")
async def oauth_callback(
    provider: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        access_token, _ = await handle_oauth_callback(request, session, provider)
        return RedirectResponse(url=build_oauth_success_redirect(access_token, provider), status_code=302)
    except HTTPException as exc:
        message = str(exc.detail or "OAuth authentication failed")
        return RedirectResponse(url=build_oauth_error_redirect(message, provider), status_code=302)


@router.post("/password/forgot", response_model=AuthForgotPasswordResponse)
async def forgot_password(payload: AuthForgotPasswordRequest, session: AsyncSession = Depends(get_db_session)):
    sent = await create_password_reset_request(session, email=payload.email)
    return AuthForgotPasswordResponse(sent=sent)


@router.post("/password/reset")
async def reset_password(payload: AuthResetPasswordRequest, session: AsyncSession = Depends(get_db_session)):
    await reset_password_with_code(
        session,
        email=payload.email,
        code=payload.code,
        new_password=payload.new_password,
    )
    return {"success": True}


@router.get("/me", response_model=UserPublic)
async def me(current_user: dict = Depends(get_current_user)):
    return UserPublic(**current_user)

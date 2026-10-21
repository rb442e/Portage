"""Sign-in with an emailed code, the current user, and admin user management."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class CodeRequest(BaseModel):
    email: str = Field(..., max_length=254)


class VerifyRequest(BaseModel):
    email: str = Field(..., max_length=254)
    code: str = Field(..., max_length=20)


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


class SignupRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)
    name: str = Field("", max_length=120)


class ResetRequest(BaseModel):
    email: str = Field(..., max_length=254)
    code: str = Field(..., max_length=20)
    password: str = Field(..., max_length=256)


class NewUser(BaseModel):
    email: str = Field(..., max_length=254)
    role: str = "viewer"
    name: str = Field("", max_length=120)


class UserPatch(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None


def _fail(e: auth.AuthError):
    raise HTTPException(status_code=e.status, detail=str(e))


def _secure_cookie(request: Request) -> bool:
    return auth._flag("PORTAGE_COOKIE_SECURE") or request.url.scheme == "https"


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _signed_in(request: Request, response: Response, token: str, user: Dict[str, Any]) -> Dict[str, Any]:
    response.set_cookie(auth.COOKIE, token, max_age=auth.session_hours() * 3600, httponly=True, samesite="lax",
                        secure=_secure_cookie(request), path="/")
    return {"status": "signed_in", "user": user}


@router.get("/config")
def config() -> Dict[str, Any]:
    return {"enabled": auth.enabled(), "email_configured": auth.email_configured(),
            "dev_codes": auth.dev_log_codes() and not os.environ.get("PORTAGE_SMTP_HOST", "").strip(),
            "code_ttl_minutes": auth.CODE_TTL // 60, "resend_seconds": auth.RESEND_COOLDOWN,
            "signup_open": auth.signup_open() or bool(auth.allowed_domains()), "password_min": auth.PASSWORD_MIN}


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response) -> Dict[str, Any]:
    try:
        token, user = auth.login(body.email, body.password, _ip(request), request.headers.get("user-agent", ""))
    except auth.AuthError as e:
        _fail(e)
    return _signed_in(request, response, token, user)


@router.post("/signup")
def signup(body: SignupRequest, request: Request) -> Dict[str, Any]:
    try:
        auth.signup_start(body.email, body.password, _ip(request), body.name)
    except auth.AuthError as e:
        _fail(e)
    return {"sent": True, "message": "Check your email for a verification code."}


@router.post("/signup/verify")
def signup_verify(body: VerifyRequest, request: Request, response: Response) -> Dict[str, Any]:
    try:
        result = auth.signup_verify(body.email, body.code, request.headers.get("user-agent", ""))
    except auth.AuthError as e:
        _fail(e)
    if result["status"] == "signed_in":
        return _signed_in(request, response, result["token"], result["user"])
    return {"status": "pending"}


@router.post("/password/forgot")
def forgot_password(body: CodeRequest, request: Request) -> Dict[str, Any]:
    try:
        auth.forgot_password(body.email, _ip(request))
    except auth.AuthError as e:
        _fail(e)
    return {"sent": True, "message": "If an account exists for this address, we've emailed a reset code."}


@router.post("/password/reset")
def reset_password(body: ResetRequest, request: Request, response: Response) -> Dict[str, Any]:
    try:
        token, user = auth.reset_password(body.email, body.code, body.password, request.headers.get("user-agent", ""))
    except auth.AuthError as e:
        _fail(e)
    return _signed_in(request, response, token, user)


@router.post("/request-code")
def request_code(body: CodeRequest, request: Request) -> Dict[str, Any]:
    try:
        auth.request_code(body.email, _ip(request))
    except auth.AuthError as e:
        _fail(e)
    return {"sent": True, "message": "If this address can sign in to Portage, a code is on its way."}


@router.post("/verify")
def verify(body: VerifyRequest, request: Request, response: Response) -> Dict[str, Any]:
    try:
        token, user = auth.verify_code(body.email, body.code, request.headers.get("user-agent", ""))
    except auth.AuthError as e:
        _fail(e)
    return _signed_in(request, response, token, user)


@router.post("/logout")
def logout(request: Request, response: Response) -> Dict[str, bool]:
    auth.logout(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"signed_out": True}


@router.get("/me")
def me(request: Request) -> Dict[str, Any]:
    if not auth.enabled():
        return {"user": auth.LOCAL_USER}
    user = auth.user_for_token(request.cookies.get(auth.COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return {"user": user}


def _directory() -> Dict[str, Any]:
    return {"users": auth.list_users(), "admin_emails": auth.admin_emails(),
            "allowed_domains": auth.allowed_domains(), "roles": list(auth.ROLES)}


@router.get("/users")
def users() -> Dict[str, Any]:
    return _directory()


@router.post("/users")
def add_user(body: NewUser, request: Request) -> Dict[str, Any]:
    try:
        auth.add_user(body.email, body.role, auth.current_user(request)["email"], body.name)
    except auth.AuthError as e:
        _fail(e)
    return _directory()


@router.patch("/users/{email}")
def update_user(email: str, body: UserPatch, request: Request) -> Dict[str, Any]:
    try:
        auth.update_user(email, auth.current_user(request)["email"], body.role, body.status)
    except auth.AuthError as e:
        _fail(e)
    return _directory()


@router.delete("/users/{email}")
def remove_user(email: str, request: Request) -> Dict[str, Any]:
    try:
        auth.remove_user(email, auth.current_user(request)["email"])
    except auth.AuthError as e:
        _fail(e)
    return _directory()

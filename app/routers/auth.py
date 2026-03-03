"""Authentication routes for bootstrap, login, logout, and status."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from ..auth import (
    SESSION_COOKIE_NAME,
    authenticate_login,
    bootstrap_single_admin,
    create_login_session,
    get_client_ip,
    is_bootstrap_required,
    logout_session,
    resolve_session_from_request,
    session_cookie_max_age,
    session_cookie_secure,
)


router = APIRouter()


class AuthLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class AuthBootstrapRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class AuthStatusResponse(BaseModel):
    authenticated: bool
    bootstrap_required: bool
    username: str = ""


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    if await is_bootstrap_required():
        return RedirectResponse(url="/auth/setup", status_code=307)
    if await resolve_session_from_request(request) is not None:
        return RedirectResponse(url="/", status_code=307)
    return HTMLResponse(content=_login_html())


@router.get("/auth/setup", response_class=HTMLResponse)
async def auth_setup_page() -> Response:
    if not await is_bootstrap_required():
        return RedirectResponse(url="/", status_code=307)
    return HTMLResponse(content=_bootstrap_html())


@router.get("/api/auth/status", response_model=AuthStatusResponse)
async def auth_status(request: Request) -> AuthStatusResponse:
    bootstrap_required = await is_bootstrap_required()
    if bootstrap_required:
        return AuthStatusResponse(authenticated=False, bootstrap_required=True, username="")
    session = await resolve_session_from_request(request)
    if session is None:
        return AuthStatusResponse(authenticated=False, bootstrap_required=False, username="")
    return AuthStatusResponse(authenticated=True, bootstrap_required=False, username=str(session["username"]))


@router.post("/api/auth/bootstrap")
async def auth_bootstrap(payload: AuthBootstrapRequest, request: Request) -> JSONResponse:
    if not await is_bootstrap_required():
        raise HTTPException(status_code=409, detail="Authentication is already configured.")

    client_ip = get_client_ip(request)
    try:
        user = await bootstrap_single_admin(payload.username, payload.password)
        cookie_value, username = await create_login_session(str(user["id"]), str(user["username"]), client_ip)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    response = JSONResponse({"ok": True, "username": username})
    _set_session_cookie(response, cookie_value, request)
    return response


@router.post("/api/auth/login")
async def auth_login(payload: AuthLoginRequest, request: Request) -> JSONResponse:
    if await is_bootstrap_required():
        raise HTTPException(status_code=409, detail="Authentication is not initialized. Complete bootstrap first.")

    client_ip = get_client_ip(request)
    try:
        cookie_value, username = await authenticate_login(payload.username, payload.password, client_ip)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    response = JSONResponse({"ok": True, "username": username})
    _set_session_cookie(response, cookie_value, request)
    return response


@router.post("/api/auth/logout")
async def auth_logout(request: Request) -> JSONResponse:
    await logout_session(str(request.cookies.get(SESSION_COOKIE_NAME, "")))
    response = JSONResponse({"ok": True})
    _clear_session_cookie(response, request)
    return response


def _set_session_cookie(response: JSONResponse, cookie_value: str, request: Request) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        max_age=session_cookie_max_age(),
        httponly=True,
        secure=session_cookie_secure(request),
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: JSONResponse, request: Request) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=session_cookie_secure(request),
        samesite="lax",
        path="/",
    )


def _login_html() -> str:
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Krill Login</title><style>"
        "body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:linear-gradient(160deg,#e7f0ff,#f6fafc);color:#1b2232;min-height:100vh;display:grid;place-items:center;padding:20px;}"
        ".card{width:100%;max-width:420px;background:#fff;border:1px solid #d7dce7;border-radius:14px;box-shadow:0 12px 38px rgba(26,40,70,.08);padding:24px;}"
        "h1{margin:0 0 8px;font-size:24px;color:#0f3f8a;}"
        "p{margin:0 0 16px;color:#4e5c76;}"
        "label{display:block;font-size:13px;margin:12px 0 6px;color:#42506a;}"
        "input{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #c7d0df;border-radius:10px;font-size:15px;}"
        "button{margin-top:14px;width:100%;padding:11px 12px;border:none;border-radius:10px;background:#1557b3;color:#fff;font-size:15px;font-weight:600;cursor:pointer;}"
        "button:disabled{opacity:.7;cursor:not-allowed;}"
        "#status{margin-top:12px;font-size:13px;min-height:20px;}"
        "</style></head><body><main class='card'><h1>Krill Login</h1><p>Sign in to access this server.</p>"
        "<form id='login-form'><label for='username'>Username</label><input id='username' autocomplete='username' required maxlength='64'>"
        "<label for='password'>Password</label><input id='password' type='password' autocomplete='current-password' required maxlength='200'>"
        "<button id='submit' type='submit'>Login</button></form><div id='status'></div></main><script>"
        "const form=document.getElementById('login-form');const status=document.getElementById('status');const btn=document.getElementById('submit');"
        "form.addEventListener('submit',async(e)=>{e.preventDefault();btn.disabled=true;status.textContent='Signing in...';"
        "const payload={username:String(document.getElementById('username').value||''),password:String(document.getElementById('password').value||'')};"
        "try{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});"
        "const p=await r.json().catch(()=>({}));if(!r.ok){status.textContent=String(p.detail||'Login failed.');btn.disabled=false;return;}"
        "window.location.replace('/');}catch(_e){status.textContent='Login failed.';btn.disabled=false;}});"
        "</script></body></html>"
    )


def _bootstrap_html() -> str:
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Krill Auth Setup</title><style>"
        "body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:linear-gradient(160deg,#f0f8ef,#f9fbff);color:#1b2232;min-height:100vh;display:grid;place-items:center;padding:20px;}"
        ".card{width:100%;max-width:440px;background:#fff;border:1px solid #d7dce7;border-radius:14px;box-shadow:0 12px 38px rgba(26,40,70,.08);padding:24px;}"
        "h1{margin:0 0 8px;font-size:24px;color:#1b6b45;}"
        "p{margin:0 0 16px;color:#4e5c76;}"
        "label{display:block;font-size:13px;margin:12px 0 6px;color:#42506a;}"
        "input{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #c7d0df;border-radius:10px;font-size:15px;}"
        "button{margin-top:14px;width:100%;padding:11px 12px;border:none;border-radius:10px;background:#1d7a4f;color:#fff;font-size:15px;font-weight:600;cursor:pointer;}"
        "button:disabled{opacity:.7;cursor:not-allowed;}"
        "#status{margin-top:12px;font-size:13px;min-height:20px;}"
        "</style></head><body><main class='card'><h1>Secure Krill</h1><p>Create the first admin account to enable login protection.</p>"
        "<form id='bootstrap-form'><label for='username'>Admin username</label><input id='username' autocomplete='username' required maxlength='64'>"
        "<label for='password'>Admin password</label><input id='password' type='password' autocomplete='new-password' required maxlength='200'>"
        "<button id='submit' type='submit'>Create Admin</button></form><div id='status'></div></main><script>"
        "const form=document.getElementById('bootstrap-form');const status=document.getElementById('status');const btn=document.getElementById('submit');"
        "form.addEventListener('submit',async(e)=>{e.preventDefault();btn.disabled=true;status.textContent='Creating admin...';"
        "const payload={username:String(document.getElementById('username').value||''),password:String(document.getElementById('password').value||'')};"
        "try{const r=await fetch('/api/auth/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});"
        "const p=await r.json().catch(()=>({}));if(!r.ok){status.textContent=String(p.detail||'Setup failed.');btn.disabled=false;return;}"
        "window.location.replace('/');}catch(_e){status.textContent='Setup failed.';btn.disabled=false;}});"
        "</script></body></html>"
    )

"""MCP/tool management routes: listing, verification, scripts, WhatsApp, and Git SSH."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..config import McpConfig, load_settings, save_settings
from ..integrations.whatsapp.sidecar_manager import connect as whatsapp_connect
from ..integrations.whatsapp.sidecar_manager import list_contacts as whatsapp_list_contacts
from ..integrations.whatsapp.sidecar_manager import status as whatsapp_status
from ..mcps import get_mcp, get_mcp_options, is_supported_mcp
from ..mcps.git_ops import (
    SSH_PRIVATE_PARAM,
    SSH_PUBLIC_PARAM,
    get_or_create_ssh_public_key,
    get_workspace_path,
    verify_github_ssh_access,
)
from ..mcps.scripts import (
    _parse_script_source,
    _render_script_source_from_record,
    _validate_script_metadata_headers,
)
from ..config import delete_script, get_script, list_scripts, upsert_script

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class VerifyMcpRequest(BaseModel):
    mcp_id: str
    params: dict[str, str] = Field(default_factory=dict)


class VerifyMcpResponse(BaseModel):
    ok: bool
    detail: str


class GitSshKeyResponse(BaseModel):
    public_key: str


class GitSshVerifyResponse(BaseModel):
    ok: bool
    detail: str


class WhatsAppStatusResponse(BaseModel):
    connected: bool
    state: str
    detail: str = ""
    qr_data_url: str = ""


# ---------------------------------------------------------------------------
# MCP listing and verification
# ---------------------------------------------------------------------------

@router.get("/api/mcps")
async def get_mcps() -> list[dict[str, object]]:
    return get_mcp_options()


@router.post("/api/mcps/verify", response_model=VerifyMcpResponse)
async def verify_mcp(payload: VerifyMcpRequest) -> VerifyMcpResponse:
    if not is_supported_mcp(payload.mcp_id):
        raise HTTPException(status_code=422, detail="Unsupported MCP.")

    mcp = get_mcp(payload.mcp_id)
    if mcp is None:
        raise HTTPException(status_code=422, detail="MCP not found.")

    settings = await load_settings()
    persisted_config = settings.mcp_configs.get(payload.mcp_id) or McpConfig()
    merged_params = dict(persisted_config.params)
    merged_params.update(payload.params)

    ok, detail = await mcp.verify(merged_params)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)

    return VerifyMcpResponse(ok=True, detail=detail)


# ---------------------------------------------------------------------------
# Scripts CRUD
# ---------------------------------------------------------------------------

@router.get("/api/mcps/scripts")
async def get_scripts_catalog() -> dict[str, object]:
    scripts = await list_scripts()
    items: list[dict[str, str]] = []
    for s in scripts:
        if not s.title.strip():
            continue
        items.append({
            "title": s.title,
            "description": s.description,
            "id": s.id,
        })
    return {"scripts": items, "titles": [i["title"] for i in items]}


@router.get("/api/mcps/scripts/{title}")
async def get_script_source(title: str) -> dict[str, object]:
    script = await get_script(title.strip())
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found.")
    source = _render_script_source_from_record(script)
    return {
        "title": script.title,
        "description": script.description,
        "instructions": script.instructions,
        "python_requirements": script.python_requirements,
        "source": source,
    }


@router.put("/api/mcps/scripts/{title}")
async def update_script_source(title: str, request: Request) -> dict[str, object]:
    body = await request.json()
    source = body.get("source", "")
    if not isinstance(source, str) or not source.strip():
        raise HTTPException(status_code=422, detail="Missing 'source' field.")
    try:
        _validate_script_metadata_headers(source)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    parsed = _parse_script_source(source)
    parsed_title = parsed.get("title", "").strip()
    script = await get_script(title.strip())
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found.")
    saved = await upsert_script(
        {
            "id": parsed_title,
            "title": parsed_title,
            "description": parsed.get("description", ""),
            "instructions": parsed.get("instructions", ""),
            "python_requirements": parsed.get("python_requirements", ""),
            "body": parsed.get("body", ""),
            "file_name": f"{parsed_title}.py",
        },
        script_id=title.strip(),
    )
    return {"ok": True, "title": saved.title}


@router.delete("/api/mcps/scripts/{title}")
async def delete_script_endpoint(title: str) -> dict[str, object]:
    script = await get_script(title.strip())
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found.")
    await delete_script(title.strip())
    return {"ok": True, "title": title.strip()}


@router.post("/api/mcps/scripts")
async def create_script_endpoint(request: Request) -> dict[str, object]:
    body = await request.json()
    source = body.get("source", "")
    if not isinstance(source, str) or not source.strip():
        raise HTTPException(status_code=422, detail="Missing 'source' field.")
    try:
        _validate_script_metadata_headers(source)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    parsed = _parse_script_source(source)
    parsed_title = parsed.get("title", "").strip()
    existing = await get_script(parsed_title)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Script '{parsed_title}' already exists. Use the editor to update it.",
        )
    saved = await upsert_script(
        {
            "id": parsed_title,
            "title": parsed_title,
            "description": parsed.get("description", ""),
            "instructions": parsed.get("instructions", ""),
            "python_requirements": parsed.get("python_requirements", ""),
            "body": parsed.get("body", ""),
            "file_name": f"{parsed_title}.py",
        },
        script_id=parsed_title,
    )
    return {"ok": True, "title": saved.title}


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------

@router.get("/api/mcps/whatsapp/status", response_model=WhatsAppStatusResponse)
async def get_whatsapp_runtime_status() -> WhatsAppStatusResponse:
    payload = await whatsapp_status()
    state = str(payload.get("status", "")).strip().lower()
    return WhatsAppStatusResponse(
        connected=state == "ready",
        state=state or "unknown",
        detail=str(payload.get("detail", "")),
        qr_data_url=str(payload.get("qr_data_url", "")),
    )


@router.get("/api/mcps/whatsapp/contacts")
async def get_whatsapp_contacts() -> dict[str, object]:
    contacts = await whatsapp_list_contacts()
    return {"ok": True, "contacts": contacts}


@router.get("/api/mcps/whatsapp/connect")
async def whatsapp_connect_popup() -> HTMLResponse:
    try:
        await whatsapp_connect()
    except Exception as exc:
        return HTMLResponse(content=_whatsapp_popup_html(error=str(exc)))
    return HTMLResponse(content=_whatsapp_popup_html())


# ---------------------------------------------------------------------------
# Git SSH
# ---------------------------------------------------------------------------

@router.get("/api/mcps/git/ssh-key", response_model=GitSshKeyResponse)
async def get_git_ssh_key() -> GitSshKeyResponse:
    settings = await load_settings()
    git_mcp_config = settings.mcp_configs.get("git_ops") or McpConfig()
    workspace = get_workspace_path()
    private_key, public_key = await get_or_create_ssh_public_key(git_mcp_config.params, workspace)

    updated_params = dict(git_mcp_config.params)
    updated_params[SSH_PRIVATE_PARAM] = private_key
    updated_params[SSH_PUBLIC_PARAM] = public_key
    settings.mcp_configs["git_ops"] = McpConfig(enabled=git_mcp_config.enabled, params=updated_params)
    await save_settings(settings)

    return GitSshKeyResponse(public_key=public_key)


@router.post("/api/mcps/git/verify-ssh", response_model=GitSshVerifyResponse)
async def verify_git_ssh() -> GitSshVerifyResponse:
    settings = await load_settings()
    git_mcp_config = settings.mcp_configs.get("git_ops") or McpConfig()
    workspace = get_workspace_path()
    private_key, public_key = await get_or_create_ssh_public_key(git_mcp_config.params, workspace)

    updated_params = dict(git_mcp_config.params)
    updated_params[SSH_PRIVATE_PARAM] = private_key
    updated_params[SSH_PUBLIC_PARAM] = public_key
    settings.mcp_configs["git_ops"] = McpConfig(enabled=git_mcp_config.enabled, params=updated_params)
    await save_settings(settings)

    ok, detail = await verify_github_ssh_access(workspace, private_key)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)
    return GitSshVerifyResponse(ok=True, detail=detail)


# ---------------------------------------------------------------------------
# WhatsApp popup HTML helper
# ---------------------------------------------------------------------------

def _whatsapp_popup_html(error: str = "") -> str:
    safe_error = str(error).replace("<", "&lt;").replace(">", "&gt;").strip()
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>WhatsApp Connect</title><style>"
        "body{font-family:ui-sans-serif,Segoe UI,Arial,sans-serif;margin:0;padding:24px;background:#f7f8fa;color:#1d2330;}"
        ".card{max-width:640px;margin:0 auto;padding:20px;border:1px solid #d7dbe3;border-radius:12px;background:#ffffff;}"
        "h1{margin:0 0 10px;font-size:20px;color:#1f6f43;}"
        "p{margin:0 0 10px;line-height:1.5;}"
        ".qr{display:flex;justify-content:center;align-items:center;min-height:320px;border:1px dashed #cfd8e3;border-radius:10px;background:#fbfcff;}"
        ".hint{color:#5f6f86;font-size:13px;}"
        "</style></head><body><div class='card'>"
        "<h1>WhatsApp Connect</h1>"
        + (f"<p style='color:#a1302d'>{safe_error}</p>" if safe_error else "<p>Scan the QR with WhatsApp Web to connect.</p>")
        + "<div id='status' class='hint'>Loading status...</div>"
        "<div id='qr' class='qr'>Waiting for QR...</div>"
        "</div><script>"
        "function escapeHtml(v){return String(v||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;');}"
        "async function tick(){"
        "try{const r=await fetch('/api/mcps/whatsapp/status',{cache:'no-store'});"
        "const p=await r.json();"
        "const state=String(p.state||'unknown');"
        "const normalizedState=state.toLowerCase();"
        "const detail=String(p.detail||'').trim();"
        "document.getElementById('status').textContent=detail?('State: '+state+' - '+detail):('State: '+state);"
        "if(p.connected||normalizedState==='ready'){"
        "try{if(window.opener){window.opener.postMessage({type:'krill-whatsapp-connected',state:normalizedState},window.location.origin);}}catch(_e){}"
        "try{const cr=await fetch('/api/mcps/whatsapp/contacts',{cache:'no-store'});"
        "if(cr.ok){document.getElementById('qr').innerHTML='<p>Connected and contacts loaded. Closing...</p>';window.setTimeout(function(){window.close();},900);return;}}catch(_e){}"
        "document.getElementById('qr').innerHTML='<p>Connected. You can close this window.</p>';window.setTimeout(function(){window.close();},1200);return;}"
        "if(normalizedState==='auth_failure'||normalizedState==='error'){document.getElementById('qr').innerHTML='<p>'+escapeHtml(detail||'WhatsApp login failed. Close this window and try Connect again.')+'</p>';window.setTimeout(tick,2000);return;}"
        "if(normalizedState==='disconnected'){document.getElementById('qr').innerHTML='<p>'+escapeHtml(detail||'WhatsApp disconnected. Retry Connect to generate a fresh QR code.')+'</p>';window.setTimeout(tick,2000);return;}"
        "if(normalizedState==='authenticated'||normalizedState==='loading'||normalizedState==='initializing'){document.getElementById('qr').innerHTML='<p>'+escapeHtml(detail||'Finalizing WhatsApp connection...')+'</p>';window.setTimeout(tick,1500);return;}"
        "if(normalizedState==='qr'&&p.qr_data_url){document.getElementById('qr').innerHTML='<img alt=\"WhatsApp QR\" style=\"max-width:280px\" src=\"'+p.qr_data_url+'\" />';window.setTimeout(tick,1500);return;}"
        "document.getElementById('qr').innerHTML='<p>'+escapeHtml(detail||'Waiting for WhatsApp to become ready...')+'</p>';"
        "}catch(_e){document.getElementById('status').textContent='Failed to load status';}"
        "window.setTimeout(tick,1500);}"
        "tick();"
        "</script></body></html>"
    )

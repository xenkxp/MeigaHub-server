from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger("uvicorn.error")

from .backend_manager import backend_manager
from .config import settings
from .model_manager import (
    download_file,
    ensure_models_dir,
    delete_local_model,
    hf_list_files_with_sizes,
    hf_resolve_url,
    hf_search_models_with_flags,
    list_local_models_with_sizes,
)

app = FastAPI(title="MeigaHub Server — Texto + Audio")

download_jobs: Dict[str, Dict[str, Any]] = {}


@app.on_event("startup")
async def on_startup() -> None:
    ensure_models_dir()
    routes = [
        {"path": getattr(route, "path", None), "methods": sorted(getattr(route, "methods", []) or [])}
        for route in app.router.routes
        if getattr(route, "path", None)
    ]
    print(f"Registered routes: {routes}")


def error_response(message: str, code: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": "backend_error", "code": code}},
    )


# Headers hop-by-hop que no deben reenviarse a través de un proxy
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "host", "content-length",
})


async def proxy_request(request: Request, target_url: str) -> Response:
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    logger.info("proxy → %s %s (%d bytes)", request.method, target_url, len(body))

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                timeout=None,
            )
    except httpx.HTTPError as exc:
        logger.error("proxy httpx error → %s: %s", type(exc).__name__, exc)
        return error_response(f"backend no disponible: {exc}", code="backend_read_error", status_code=502)
    except Exception as exc:
        logger.exception("proxy error inesperado → %s: %s", type(exc).__name__, exc)
        return error_response(f"error interno del proxy: {exc}", code="proxy_error", status_code=502)

    logger.info("proxy ← %s %s", response.status_code, response.headers.get("content-type", "?"))
    if response.status_code >= 400:
        body_preview = response.text[:500] if response.text else "(vacío)"
        logger.warning("backend respondió %s: %s", response.status_code, body_preview)
    content_type = response.headers.get("content-type", "application/json")
    return Response(content=response.content, status_code=response.status_code, media_type=content_type)


async def ensure_llm(model_name: Optional[str]) -> Optional[JSONResponse]:
    try:
        logger.info("ensure_llm model=%s", model_name)
        await backend_manager.ensure_backend_with_model("llm", model_name)
        logger.info("ensure_llm OK — backend listo")
        return None
    except Exception as exc:
        logger.exception("ensure_llm falló: %s", exc)
        return error_response(str(exc), code="llm_unavailable", status_code=409)
async def extract_model_name(request: Request) -> Optional[str]:
    try:
        data = await request.json()
    except Exception:
        return None
    if isinstance(data, dict):
        model = data.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    return None


async def ensure_whisper() -> Optional[JSONResponse]:
    try:
        logger.info("ensure_whisper")
        await backend_manager.ensure_backend("whisper")
        logger.info("ensure_whisper OK")
        return None
    except Exception as exc:
        logger.exception("ensure_whisper falló: %s", exc)
        return error_response(str(exc), code="whisper_unavailable", status_code=409)


@app.get("/status")
async def status() -> Dict[str, Any]:
    state = await backend_manager.get_status()
    return {
        "backend": state.backend,
        "model": state.model,
        "vram": state.vram,
        "busy": state.busy,
    }


@app.get("/ui/gpu")
async def gpu_info() -> Response:
    """Detecta la GPU con nvidia-smi y devuelve nombre + VRAM total/libre en MB."""
    info: Dict[str, Any] = {"name": None, "vram_total_mb": 0, "vram_free_mb": 0, "vram_used_mb": 0}
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return JSONResponse(content=info)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [nvidia_smi, "--query-gpu=name,memory.total,memory.free,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 4:
                info["name"] = parts[0]
                info["vram_total_mb"] = int(parts[1])
                info["vram_free_mb"] = int(parts[2])
                info["vram_used_mb"] = int(parts[3])
    except Exception as exc:
        logger.warning("nvidia-smi falló: %s", exc)
    return JSONResponse(content=info)


@app.get("/ui/models")
async def models_ui() -> Response:
    html = """
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>MeigaHub — Gestor de modelos</title>
    <style>
        *,*::before,*::after{box-sizing:border-box}
        :root{
            --bg:#0f1117;--surface:#1a1b26;--surface2:#24253a;--border:#2f3146;
            --text:#c0caf5;--text2:#565f89;--accent:#7aa2f7;--accent2:#bb9af7;
            --green:#9ece6a;--red:#f7768e;--orange:#ff9e64;--cyan:#7dcfff;
        }
        body{margin:0;font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
        .app{max-width:1100px;margin:0 auto;padding:24px 20px}
        header{display:flex;align-items:center;gap:12px;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--border)}
        header h1{font-size:1.5rem;font-weight:700;margin:0;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        header .pill{font-size:11px;padding:3px 10px;border-radius:20px;background:var(--surface2);color:var(--text2);border:1px solid var(--border)}
        .tabs{display:flex;gap:4px;margin-bottom:20px;background:var(--surface);padding:4px;border-radius:12px;border:1px solid var(--border)}
        .tab{flex:1;padding:10px 16px;text-align:center;border-radius:8px;cursor:pointer;font-size:14px;font-weight:500;color:var(--text2);transition:all .2s;border:none;background:none}
        .tab:hover{color:var(--text);background:var(--surface2)}
        .tab.active{background:var(--accent);color:#fff;box-shadow:0 2px 8px rgba(122,162,247,.3)}
        .panel{display:none}
        .panel.active{display:block}
        .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px}
        .card-header{display:flex;align-items:center;gap:8px;margin-bottom:14px}
        .card-header .icon{font-size:20px}
        .card-header h3{margin:0;font-size:15px;font-weight:600}
        .input-row{display:flex;gap:8px;margin-bottom:12px}
        .input-row input{flex:1}
        input,select{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:14px;width:100%;outline:none;transition:border-color .2s}
        input:focus,select:focus{border-color:var(--accent)}
        input::placeholder{color:var(--text2)}
        .btn{display:inline-flex;align-items:center;gap:6px;padding:9px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:all .15s}
        .btn:disabled{opacity:.5;cursor:not-allowed}
        .btn-primary{background:var(--accent);color:#fff}.btn-primary:hover:not(:disabled){background:#5d8cf6}
        .btn-success{background:var(--green);color:#1a1b26}.btn-success:hover:not(:disabled){filter:brightness(1.1)}
        .btn-danger{background:var(--red);color:#fff;font-size:12px;padding:6px 12px}.btn-danger:hover:not(:disabled){filter:brightness(1.1)}
        .btn-ghost{background:transparent;color:var(--text2);border:1px solid var(--border)}.btn-ghost:hover{color:var(--text);border-color:var(--text2)}
        .btn-sm{padding:6px 12px;font-size:12px}
        .actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;margin-top:12px}
        .model-card{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px;transition:border-color .2s;cursor:default}
        .model-card:hover{border-color:var(--accent)}
        .model-card .name{font-weight:600;font-size:14px;word-break:break-all;margin-bottom:6px}
        .model-card .meta{font-size:12px;color:var(--text2);line-height:1.6}
        .model-card .meta span{margin-right:12px}
        .badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:6px;font-weight:600}
        .badge-gguf{background:rgba(158,206,106,.15);color:var(--green)}
        .badge-no{background:rgba(247,118,142,.12);color:var(--red)}
        .badge-unk{background:rgba(86,95,137,.25);color:var(--text2)}
        .select-card{display:flex;align-items:center;gap:10px;margin:12px 0}
        .select-card select{flex:1}
        .file-info{font-size:12px;color:var(--text2);padding:4px 0}
        .progress-wrap{margin-top:12px}
        .progress-bar-bg{height:8px;background:var(--surface2);border-radius:4px;overflow:hidden}
        .progress-bar-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:4px;transition:width .3s;width:0%}
        .progress-label{font-size:12px;color:var(--text2);margin-top:4px}
        .status-row{display:flex;gap:12px;align-items:center;margin-bottom:16px;padding:12px 16px;background:var(--surface);border:1px solid var(--border);border-radius:10px;font-size:13px}
        .status-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
        .status-dot.on{background:var(--green);box-shadow:0 0 6px var(--green)}
        .status-dot.off{background:var(--text2)}
        .empty{text-align:center;padding:32px;color:var(--text2);font-size:14px}
        .spinner{display:inline-block;width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}
        @keyframes spin{to{transform:rotate(360deg)}}
        .gpu-bar{display:flex;gap:12px;align-items:center;margin-bottom:12px;padding:10px 16px;background:var(--surface);border:1px solid var(--border);border-radius:10px;font-size:13px}
        .gpu-bar .gpu-icon{font-size:18px}
        .gpu-bar .gpu-label{color:var(--text2)}
        .gpu-bar .gpu-val{font-weight:600;color:var(--text)}
        .vram-ok{color:var(--green);font-weight:600}
        .vram-tight{color:var(--orange);font-weight:600}
        .vram-no{color:var(--red);font-weight:600}
        .badge-rec{background:rgba(224,175,104,.2);color:var(--orange);font-weight:700;margin-left:6px;padding:2px 8px;border-radius:6px;font-size:11px}
        .footer{text-align:center;font-size:12px;color:var(--text2);margin-top:24px;padding-top:16px;border-top:1px solid var(--border)}
        .checkbox-row{display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:13px;color:var(--text2)}
        .checkbox-row input[type=checkbox]{width:auto;accent-color:var(--accent)}
        .toast{position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:500;color:#fff;z-index:999;opacity:0;transform:translateY(10px);transition:all .3s}
        .toast.show{opacity:1;transform:translateY(0)}
        .toast.ok{background:var(--green);color:#1a1b26}
        .toast.err{background:var(--red)}
    </style>
</head>
<body>
<div class="app">
    <header>
        <h1>⚡ MeigaHub — Modelos</h1>
        <span class="pill" id="statusPill">…</span>
    </header>
    <div id="statusRow" class="status-row">
        <div class="status-dot off" id="statusDot"></div>
        <span id="statusText">Cargando estado…</span>
    </div>
    <div class="gpu-bar" id="gpuBar" style="display:none">
        <span class="gpu-icon">🎮</span>
        <span class="gpu-label">GPU:</span>
        <span class="gpu-val" id="gpuName">—</span>
        <span class="gpu-label">| VRAM total:</span>
        <span class="gpu-val" id="gpuTotal">—</span>
        <span class="gpu-label">| Libre:</span>
        <span class="gpu-val" id="gpuFree">—</span>
    </div>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('search')">🔎 Buscar</div>
        <div class="tab" onclick="switchTab('download')">📦 Descargar</div>
        <div class="tab" onclick="switchTab('local')">💾 Locales</div>
    </div>

    <!-- ========== BUSCAR ========== -->
    <div class="panel active" id="panel-search">
        <div class="card">
            <div class="card-header"><span class="icon">🔎</span><h3>Buscar modelos en Hugging Face</h3></div>
            <div class="input-row">
                <input id="q" placeholder="llama, mistral, whisper, phi…" onkeydown="if(event.key==='Enter')search()"/>
                <button class="btn btn-primary" id="btnSearch" onclick="search()">Buscar</button>
            </div>
            <div class="checkbox-row">
                <input type="checkbox" id="onlyGguf" checked/><label for="onlyGguf">Solo repos con GGUF</label>
            </div>
            <div id="results"></div>
        </div>
    </div>

    <!-- ========== DESCARGAR ========== -->
    <div class="panel" id="panel-download">
        <div class="card">
            <div class="card-header"><span class="icon">📦</span><h3>Descargar archivo GGUF de un repo</h3></div>
            <div class="input-row">
                <input id="repo" placeholder="TheBloke/Mistral-7B-Instruct-v0.2-GGUF"/>
                <button class="btn btn-primary" id="btnFiles" onclick="loadFiles()">Listar archivos</button>
            </div>
            <div class="select-card">
                <select id="files" onchange="updateFileInfo()"><option value="">— selecciona un archivo —</option></select>
            </div>
            <div class="file-info" id="fileInfo"></div>
            <div class="actions">
                <button class="btn btn-success" id="btnDownload" onclick="download()">⬇ Descargar</button>
            </div>
            <div class="progress-wrap" id="progressWrap" style="display:none">
                <div class="progress-bar-bg"><div class="progress-bar-fill" id="bar"></div></div>
                <div class="progress-label" id="progressLabel"></div>
            </div>
        </div>
    </div>

    <!-- ========== LOCALES ========== -->
    <div class="panel" id="panel-local">
        <div class="card">
            <div class="card-header"><span class="icon">💾</span><h3>Modelos locales</h3></div>
            <div class="actions">
                <button class="btn btn-ghost btn-sm" onclick="loadLocal()">↻ Actualizar</button>
            </div>
            <div id="localList"></div>
        </div>
    </div>

    <div class="footer">Directorio de modelos: <strong>__MODELS_DIR__</strong></div>
</div>

<div class="toast" id="toast"></div>

<script>
/* ── helpers ── */
let _searchCtrl = null;
let _filesCtrl = null;
let _gpu = {name:null, vram_total_mb:0, vram_free_mb:0};

function $(id){ return document.getElementById(id) }

function formatBytes(b){
    if(!b) return '?';
    const u=['B','KB','MB','GB','TB']; let i=0,n=b;
    while(n>=1024&&i<u.length-1){n/=1024;i++}
    return n.toFixed(i>1?2:0)+' '+u[i];
}

function formatMB(mb){ return mb>=1024?(mb/1024).toFixed(1)+' GB':mb+' MB'; }

function vramClass(fileBytes){
    if(!_gpu.vram_total_mb||!fileBytes) return '';
    const needMB=Math.ceil(fileBytes/1048576*1.15);
    if(needMB>_gpu.vram_total_mb) return 'vram-no';
    if(needMB>_gpu.vram_total_mb*0.85) return 'vram-tight';
    return 'vram-ok';
}

function vramLabel(fileBytes){
    if(!_gpu.vram_total_mb||!fileBytes) return '';
    const needMB=Math.ceil(fileBytes/1048576*1.15);
    const cls=vramClass(fileBytes);
    if(cls==='vram-ok') return '<span class="vram-ok">✅ Cabe en VRAM</span>';
    if(cls==='vram-tight') return '<span class="vram-tight">⚠️ Justo en VRAM</span>';
    return '<span class="vram-no">❌ No cabe ('+formatMB(needMB)+' > '+formatMB(_gpu.vram_total_mb)+')</span>';
}

async function loadGpu(){
    try{
        const r=await fetch('/ui/gpu');
        const d=await r.json();
        _gpu=d;
        if(d.name){
            $('gpuBar').style.display='flex';
            $('gpuName').textContent=d.name;
            $('gpuTotal').textContent=formatMB(d.vram_total_mb);
            $('gpuFree').textContent=formatMB(d.vram_free_mb);
        }
    }catch(e){}
}

function toast(msg,ok=true){
    const t=$('toast'); t.textContent=msg; t.className='toast show '+(ok?'ok':'err');
    setTimeout(()=>t.className='toast',3000);
}

function switchTab(name){
    document.querySelectorAll('.tab').forEach((t,i)=>{
        const panels=['search','download','local'];
        const active=panels[i]===name;
        t.classList.toggle('active',active);
        $('panel-'+panels[i]).classList.toggle('active',active);
    });
    if(name==='local') loadLocal();
}

/* ── status ── */
async function loadStatus(){
    try{
        const r=await fetch('/status'); const d=await r.json();
        const on=d.backend!=='none';
        $('statusDot').className='status-dot '+(on?'on':'off');
        $('statusText').textContent=on?`Backend: ${d.backend} · Modelo: ${d.model||'—'}`:'Ningún backend activo';
        $('statusPill').textContent=on?d.backend.toUpperCase():'OFF';
    }catch(e){
        $('statusText').textContent='Sin conexión';
    }
}

/* ── search ── */
async function search(){
    const q=$('q').value.trim(); if(!q){toast('Escribe algo para buscar',false);return}
    const el=$('results'); const btn=$('btnSearch');
    if(_searchCtrl) _searchCtrl.abort();
    _searchCtrl=new AbortController();
    const timeout=setTimeout(()=>_searchCtrl.abort(),20000);
    el.innerHTML='<div class="empty"><span class="spinner"></span>Buscando "'+q+'" en Hugging Face…</div>';
    btn.disabled=true;
    try{
        const gguf=$('onlyGguf').checked?'1':'0';
        const r=await fetch('/ui/models/search?q='+encodeURIComponent(q)+'&only_gguf='+gguf+'&limit=12',{signal:_searchCtrl.signal});
        if(!r.ok) throw new Error('El servidor respondió '+r.status);
        const data=await r.json();
        if(!data.length){
            const tip=$('onlyGguf').checked?' Prueba desmarcando "Solo repos con GGUF".':'';
            el.innerHTML='<div class="empty">No se encontraron resultados para "'+q+'".'+tip+'</div>';
            return;
        }
        el.innerHTML='<div class="grid">'+data.map(x=>{
            const name=x.modelId||x.id||'?';
            const gguf=x.gguf_count;
            const has=x.has_gguf;
            let badge='';
            if(has===true&&gguf) badge=`<span class="badge badge-gguf">${gguf} GGUF</span>`;
            else if(has===true) badge='<span class="badge badge-gguf">✓ GGUF</span>';
            else if(has===false) badge='<span class="badge badge-no">sin GGUF</span>';
            else badge='<span class="badge badge-unk">sin verificar</span>';
            return `<div class="model-card" onclick="selectRepo('${name}')">
                <div class="name">${name}</div>
                <div class="meta">${badge}</div>
            </div>`;
        }).join('')+'</div>';
    }catch(e){
        if(e.name==='AbortError'){
            el.innerHTML='<div class="empty" style="color:var(--orange)">⏱ La búsqueda tardó demasiado. Intenta de nuevo.</div>';
        }else if(e.message==='Failed to fetch'){
            el.innerHTML='<div class="empty" style="color:var(--red)">⚠ No se puede conectar al servidor. ¿Está corriendo?</div>';
        }else{
            el.innerHTML='<div class="empty" style="color:var(--red)">❌ '+e.message+'</div>';
        }
    }finally{clearTimeout(timeout);btn.disabled=false}
}

function selectRepo(name){
    $('repo').value=name;
    switchTab('download');
    loadFiles();
}

/* ── files ── */
async function loadFiles(){
    const repo=$('repo').value.trim(); if(!repo){toast('Ingresa un repo',false);return}
    const btn=$('btnFiles');
    if(_filesCtrl) _filesCtrl.abort();
    _filesCtrl=new AbortController();
    const timeout=setTimeout(()=>_filesCtrl.abort(),15000);
    btn.disabled=true; $('files').innerHTML='<option>Cargando archivos…</option>';
    try{
        const r=await fetch('/ui/models/files?repo='+encodeURIComponent(repo),{signal:_filesCtrl.signal});
        if(!r.ok) throw new Error('Error '+r.status);
        const files=await r.json();
        window.__fc=files;
        if(!files.length){$('files').innerHTML='<option>No se encontraron archivos GGUF en este repo</option>';return}
        let bestIdx=-1, bestSize=0;
        files.forEach((f,i)=>{
            if(f.size && _gpu.vram_total_mb){
                const needMB=Math.ceil(f.size/1048576*1.15);
                if(needMB<=_gpu.vram_total_mb && f.size>bestSize){bestSize=f.size;bestIdx=i;}
            }
        });
        $('files').innerHTML=files.map((f,i)=>{
            const s=f.size?' ('+formatBytes(f.size)+')':'';
            const vc=vramClass(f.size);
            const icon=vc==='vram-ok'?'✅ ':vc==='vram-tight'?'⚠️ ':vc==='vram-no'?'❌ ':'';
            const rec=i===bestIdx?'⭐ ':'';
            return '<option value="'+f.name+'"'+(i===bestIdx?' selected':'')+'>'+rec+icon+f.name+s+'</option>';
        }).join('');
        updateFileInfo();
        toast(files.length+' archivo(s) GGUF encontrados');
    }catch(e){
        if(e.name==='AbortError'){$('files').innerHTML='<option>Timeout — intenta de nuevo</option>';toast('La petición tardó demasiado',false)}
        else if(e.message==='Failed to fetch'){$('files').innerHTML='<option>Sin conexión al servidor</option>';toast('Servidor no disponible',false)}
        else{$('files').innerHTML='<option>Error cargando</option>';toast(e.message,false)}
    }finally{clearTimeout(timeout);btn.disabled=false}
}

function updateFileInfo(){
    const files=window.__fc||[];
    const cur=files.find(f=>f.name===$('files').value);
    if(!cur){$('fileInfo').textContent='';return}
    const s=cur.size?formatBytes(cur.size):'?';
    const needMB=cur.size?Math.ceil(cur.size/1048576*1.15):0;
    const rec=needMB?formatMB(needMB):'?';
    let html='Tamaño: <strong>'+s+'</strong> · VRAM estimada: <strong>'+rec+'</strong>';
    html+=' · '+vramLabel(cur.size);
    $('fileInfo').innerHTML=html;
}

/* ── download ── */
async function download(){
    const repo=$('repo').value.trim();
    const file=$('files').value;
    if(!repo||!file){toast('Selecciona repo y archivo',false);return}
    $('btnDownload').disabled=true;
    $('progressWrap').style.display='block';
    $('bar').style.width='0%';
    $('progressLabel').textContent='Iniciando…';
    try{
        const r=await fetch('/ui/models/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo,file})});
        const d=await r.json();
        if(!d.id){toast(d.message||'Error al iniciar descarga',false);return}
        await pollProgress(d.id);
    }catch(e){toast(e.message,false)}
    finally{$('btnDownload').disabled=false}
}

async function pollProgress(id){
    while(true){
        try{
            const r=await fetch('/ui/models/download/'+id);
            const d=await r.json();
            if(d.status==='done'){
                $('bar').style.width='100%';
                $('progressLabel').textContent='✅ Descarga completada';
                toast('Descarga completada');
                loadLocal();
                return;
            }
            if(d.status==='error'){
                $('progressLabel').textContent='❌ '+(d.error||'Error');
                toast(d.error||'Error en descarga',false);
                return;
            }
            if(d.total_bytes){
                const pct=Math.floor((d.downloaded_bytes/d.total_bytes)*100);
                $('bar').style.width=pct+'%';
                $('progressLabel').textContent=pct+'% — '+formatBytes(d.downloaded_bytes)+' / '+formatBytes(d.total_bytes);
            }else{
                $('progressLabel').textContent='Descargando: '+formatBytes(d.downloaded_bytes);
            }
        }catch(e){}
        await new Promise(r=>setTimeout(r,1000));
    }
}

/* ── local ── */
async function loadLocal(){
    const el=$('localList');
    el.innerHTML='<div class="empty"><span class="spinner"></span>Cargando…</div>';
    try{
        const r=await fetch('/ui/models/local');
        const data=await r.json();
        if(!data.length){el.innerHTML='<div class="empty">No hay modelos locales</div>';return}
        el.innerHTML='<div class="grid">'+data.map(x=>{
            const s=x.size?formatBytes(x.size):'?';
            const needMB=x.size?Math.ceil(x.size/1048576*1.15):0;
            const rec=needMB?formatMB(needMB):'?';
            const vl=vramLabel(x.size);
            return `<div class="model-card">
                <div class="name">${x.name}</div>
                <div class="meta">
                    <span>📁 ${s}</span>
                    <span>🎮 VRAM: ${rec}</span>
                    <span>${vl}</span>
                </div>
                <button class="btn btn-danger btn-sm" style="margin-top:10px" onclick="removeModel('${x.name}')">🗑 Borrar</button>
            </div>`;
        }).join('')+'</div>';
    }catch(e){el.innerHTML='<div class="empty" style="color:var(--red)">Error: '+e.message+'</div>'}
}

async function removeModel(name){
    if(!confirm('¿Borrar '+name+'?')) return;
    try{
        const r=await fetch('/ui/models/local',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
        const d=await r.json();
        if(d.error){toast(d.error.message||'Error',false);return}
        toast('Modelo borrado');
        loadLocal();
    }catch(e){toast(e.message,false)}
}

/* ── init ── */
window.addEventListener('load',async()=>{await loadGpu();loadStatus();loadLocal();setInterval(loadStatus,15000)});
</script>
</body>
</html>
"""
    html = html.replace("__MODELS_DIR__", settings.models_dir)
    return Response(content=html, media_type="text/html")


@app.get("/ui/models/search")
async def models_search(q: str = "", limit: int = 12, only_gguf: int = 0) -> Response:
    if not q:
        return JSONResponse(content=[])
    try:
        results = await asyncio.to_thread(
            hf_search_models_with_flags, q, limit, bool(only_gguf)
        )
        if only_gguf:
            results = [item for item in results if item.get("has_gguf") is True]
    except Exception as exc:
        logger.error("search error: %s", exc)
        return JSONResponse(content=[], status_code=200)
    return JSONResponse(content=results)


@app.get("/ui/models/files")
async def models_files(repo: str) -> Response:
    files = await asyncio.to_thread(hf_list_files_with_sizes, repo)
    return JSONResponse(content=files)


@app.get("/ui/models/local")
async def models_local() -> Response:
    return JSONResponse(content=list_local_models_with_sizes())


@app.delete("/ui/models/local")
async def models_local_delete(payload: Dict[str, str]) -> Response:
    name = payload.get("name", "")
    if not name:
        return error_response("nombre requerido", code="invalid_request")
    try:
        await asyncio.to_thread(delete_local_model, name)
    except FileNotFoundError:
        return error_response("modelo no encontrado", code="not_found", status_code=404)
    except Exception as exc:
        return error_response(str(exc), code="delete_failed")
    return JSONResponse(content={"message": "borrado"})


@app.post("/ui/models/download")
async def models_download(payload: Dict[str, str]) -> Response:
    repo = payload.get("repo", "")
    filename = payload.get("file", "")
    if not repo or not filename:
        return error_response("repo y archivo requeridos", code="invalid_request")
    url = hf_resolve_url(repo, filename)
    job_id = str(uuid.uuid4())
    download_jobs[job_id] = {
        "status": "running",
        "downloaded_bytes": 0,
        "total_bytes": None,
    }

    def _on_progress(downloaded: int, total: int | None) -> None:
        download_jobs[job_id]["downloaded_bytes"] = downloaded
        download_jobs[job_id]["total_bytes"] = total

    async def _run_download() -> None:
        try:
            await asyncio.to_thread(
                download_file,
                url,
                filename,
                settings.huggingface_token or None,
                _on_progress,
            )
            download_jobs[job_id]["status"] = "done"
        except Exception as exc:
            download_jobs[job_id]["status"] = "error"
            download_jobs[job_id]["error"] = str(exc)

    asyncio.create_task(_run_download())
    return JSONResponse(content={"id": job_id})


@app.get("/ui/models/download/{job_id}")
async def models_download_status(job_id: str) -> Response:
    job = download_jobs.get(job_id)
    if not job:
        return error_response("descarga no encontrada", code="not_found", status_code=404)
    return JSONResponse(content=job)


@app.get("/v1/models")
async def models(request: Request) -> Response:
    mode = settings.models_list_mode.lower()
    active = backend_manager.active_backend

    if mode in {"local", "both"}:
        local = list_local_models_with_sizes()
        data = [{"id": item["name"], "object": "model"} for item in local]
        if mode == "local":
            return JSONResponse(content={"object": "list", "data": data})
        # both: merge active model at top if exists
        if active == "llm" and settings.llm_model_name:
            data = [{"id": settings.llm_model_name, "object": "model"}] + data
        elif active == "whisper" and settings.whisper_model_name:
            data = [{"id": settings.whisper_model_name, "object": "model"}] + data
        return JSONResponse(content={"object": "list", "data": data})

    # default: active only (OpenAI-compatible)
    if active == "llm":
        target = settings.llm_backend_url.rstrip("/") + "/v1/models"
        return await proxy_request(request, target)
    if active == "whisper":
        model_id = settings.whisper_model_name or "whisper"
        payload = {"object": "list", "data": [{"id": model_id, "object": "model"}]}
        return JSONResponse(content=payload)
    return JSONResponse(content={"object": "list", "data": []})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    model_name = await extract_model_name(request)
    error = await ensure_llm(model_name)
    if error:
        return error
    target = settings.llm_backend_url.rstrip("/") + "/v1/chat/completions"
    return await proxy_request(request, target)


@app.post("/v1/completions")
async def completions(request: Request) -> Response:
    model_name = await extract_model_name(request)
    error = await ensure_llm(model_name)
    if error:
        return error
    target = settings.llm_backend_url.rstrip("/") + "/v1/completions"
    return await proxy_request(request, target)


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> Response:
    model_name = await extract_model_name(request)
    error = await ensure_llm(model_name)
    if error:
        return error
    target = settings.llm_backend_url.rstrip("/") + "/v1/embeddings"
    return await proxy_request(request, target)


@app.post("/v1/responses")
async def responses(request: Request) -> Response:
    model_name = await extract_model_name(request)
    error = await ensure_llm(model_name)
    if error:
        return error
    if settings.responses_mode.lower() == "proxy":
        target = settings.llm_backend_url.rstrip("/") + "/v1/responses"
    else:
        target = settings.llm_backend_url.rstrip("/") + "/v1/chat/completions"
    return await proxy_request(request, target)


@app.post("/v1/audio/transcriptions")
async def audio_transcriptions(
    file: UploadFile = File(...),
    model: Optional[str] = Form(default=None),
    language: Optional[str] = Form(default=None),
    prompt: Optional[str] = Form(default=None),
    response_format: Optional[str] = Form(default=None),
    temperature: Optional[float] = Form(default=None),
) -> Response:
    error = await ensure_whisper()
    if error:
        return error
    target = settings.whisper_backend_url.rstrip("/") + "/inference"
    data = {}
    if model is not None:
        data["model"] = model
    if language is not None:
        data["language"] = language
    if prompt is not None:
        data["prompt"] = prompt
    if response_format is not None:
        data["response_format"] = response_format
    if temperature is not None:
        data["temperature"] = str(temperature)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            target,
            data=data,
            files={"file": (file.filename, await file.read(), file.content_type)},
            timeout=None,
        )
    content_type = response.headers.get("content-type", "application/json")
    return Response(content=response.content, status_code=response.status_code, media_type=content_type)


@app.post("/v1/audio/translations")
async def audio_translations(
    file: UploadFile = File(...),
    model: Optional[str] = Form(default=None),
    prompt: Optional[str] = Form(default=None),
    response_format: Optional[str] = Form(default=None),
    temperature: Optional[float] = Form(default=None),
) -> Response:
    error = await ensure_whisper()
    if error:
        return error
    target = settings.whisper_backend_url.rstrip("/") + "/inference"
    data = {}
    if model is not None:
        data["model"] = model
    if prompt is not None:
        data["prompt"] = prompt
    if response_format is not None:
        data["response_format"] = response_format
    if temperature is not None:
        data["temperature"] = str(temperature)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            target,
            data=data,
            files={"file": (file.filename, await file.read(), file.content_type)},
            timeout=None,
        )
    content_type = response.headers.get("content-type", "application/json")
    return Response(content=response.content, status_code=response.status_code, media_type=content_type)


@app.get("/debug/routes")
async def debug_routes() -> Dict[str, Any]:
    routes = [
        {
            "path": getattr(route, "path", None),
            "methods": sorted(getattr(route, "methods", []) or []),
            "name": getattr(route, "name", None),
        }
        for route in app.router.routes
        if getattr(route, "path", None)
    ]
    return {"routes": routes}


@app.api_route("/debug/echo", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def debug_echo(request: Request) -> Dict[str, Any]:
    headers = request.headers
    return {
        "method": request.method,
        "path": request.url.path,
        "query": str(request.url.query),
        "client": request.client.host if request.client else None,
        "content_type": headers.get("content-type"),
        "content_length": headers.get("content-length"),
        "user_agent": headers.get("user-agent"),
        "host": headers.get("host"),
    }

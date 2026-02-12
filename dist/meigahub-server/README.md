# ⚡ MeigaHub-server — Texto + Audio con gestión de VRAM

> Servidor proxy FastAPI compatible con la **API de OpenAI** que alterna automáticamente entre un backend de **texto (llama.cpp)** y uno de **audio (whisper.cpp)**, liberando VRAM de GPU cada vez que cambia de modo.

---

## 📖 ¿Qué hace esta aplicación?

Este servidor actúa como **proxy inteligente** entre tus aplicaciones y dos backends locales de IA:

| Función | Backend | Tecnología |
|---|---|---|
| Chat, completions, embeddings, responses | **LLM** | [llama.cpp](https://github.com/ggerganov/llama.cpp) |
| Transcripción y traducción de audio | **Whisper** | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) |

**Características principales:**

- 🔄 **Cambio automático de backend** — cuando llega una petición de texto arranca LLM; cuando llega una de audio arranca Whisper y apaga LLM (y viceversa), liberando VRAM.
- 🧠 **Cambio dinámico de modelo LLM** — puedes enviar el campo `"model"` en la petición y el servidor recargará llama-server con ese modelo GGUF automáticamente.
- 🖥️ **Interfaz web de gestión de modelos** — busca, descarga y elimina modelos GGUF desde Hugging Face directamente desde el navegador.
- 🎮 **Indicador de VRAM en tiempo real** — la UI muestra la GPU detectada, VRAM disponible y si cada modelo cabe en tu tarjeta.
- 📡 **Compatible con la API de OpenAI** — usa los mismos endpoints `/v1/*` que cualquier cliente OpenAI-compatible.

---

## 📁 Estructura de carpetas del sistema completo

```
C:\
├── apps\                              ← Ejecutables de los backends
│   ├── llama.cpp\                     ← llama.cpp (CPU)
│   │   └── llama-server.exe
│   ├── llama.cpp-cuda\                ← llama.cpp con aceleración CUDA (GPU NVIDIA)
│   │   └── llama-server.exe
│   └── whisper.cpp\
│       └── Release\
│           └── whisper-server.exe     ← whisper.cpp server
│
├── models\                            ← Modelos GGUF (LLM y Whisper)
│   ├── mistral-7b-instruct-v0.2.Q4_0.gguf
│   ├── qwen2.5-7b-instruct-q4_k_m.gguf
│   ├── Qwen3-14B.Q6_K.gguf
│   └── ggml-medium.bin                ← modelo Whisper
│
└── Users\<tu-usuario>\Desktop\
    └── servidordellm\                 ← ESTE PROYECTO (MeigaHub-server)
        ├── .env                       ← Configuración local (no se sube a git)
        ├── .env.example               ← Plantilla de configuración
        ├── requirements.txt           ← Dependencias Python
        ├── README.md
        ├── app\                       ← Código fuente del servidor
        │   ├── main.py                ← Endpoints FastAPI + proxy + UI
        │   ├── config.py              ← Configuración desde .env (Pydantic)
        │   ├── backend_manager.py     ← Arranque/parada/cambio de backends
        │   └── model_manager.py       ← Gestión de modelos + API de Hugging Face
        └── scripts\                   ← Utilidades de inicio/parada/test
            ├── start_server.bat       ← Doble clic para iniciar
            ├── stop_server.bat        ← Doble clic para detener
            ├── start_server.ps1       ← PowerShell start/stop
            ├── stop_server.ps1        ← Alias para stop
            ├── setup_check.ps1        ← Verifica que todo esté en su sitio
            └── test_llm.py            ← Smoke test de endpoints LLM
```

---

## 🔧 Requisitos previos

| Requisito | Detalle |
|---|---|
| **Sistema operativo** | Windows 10/11 (64-bit) |
| **Python** | 3.10 o superior ([python.org](https://www.python.org/downloads/)) |
| **GPU (recomendado)** | NVIDIA con drivers actualizados y CUDA (para versión CUDA de llama.cpp) |
| **RAM** | Mínimo 8 GB (16 GB recomendado para modelos 7B) |
| **Espacio en disco** | ~50 MB para el servidor + espacio para modelos GGUF (2–10 GB cada uno) |

---

## 🚀 Instalación paso a paso

### 1. Instalar llama.cpp (backend LLM)

llama.cpp es el motor que ejecuta los modelos de lenguaje GGUF.

**Opción A — Descargar binarios precompilados (recomendado):**

1. Ve a [llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases).
2. Descarga la versión adecuada:
   - **Con GPU NVIDIA (CUDA):** `llama-<version>-bin-win-cuda-cu12.2.0-x64.zip` (o la versión CUDA de tu driver).
   - **Solo CPU:** `llama-<version>-bin-win-x64.zip`
3. Extrae el contenido en una carpeta, por ejemplo:
   - `C:\apps\llama.cpp-cuda\` (versión CUDA)
   - `C:\apps\llama.cpp\` (versión CPU)
4. Verifica que existe `llama-server.exe` dentro de la carpeta.

**Opción B — Compilar desde fuente:**

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=ON    # usar -DGGML_CUDA=OFF para solo CPU
cmake --build build --config Release
```

### 2. Instalar whisper.cpp (backend Audio)

whisper.cpp es el motor que ejecuta los modelos de transcripción de audio.

**Opción A — Descargar binarios precompilados:**

1. Ve a [whisper.cpp releases](https://github.com/ggerganov/whisper.cpp/releases).
2. Descarga la versión para Windows (ej: `whisper-<version>-bin-x64.zip`).
3. Extrae en `C:\apps\whisper.cpp\Release\`.
4. Verifica que existe `whisper-server.exe`.

**Opción B — Compilar desde fuente:**

```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
cmake -B build
cmake --build build --config Release
```

### 3. Descargar modelos GGUF

Los modelos son archivos pesados que **no se incluyen en el instalador**. Colócalos en `C:\models\` (o la ruta que configures).

**Modelos LLM (texto):**
- Busca modelos GGUF en [Hugging Face](https://huggingface.co/models?search=gguf).
- Recomendaciones para empezar:
  - `mistral-7b-instruct-v0.2.Q4_0.gguf` (~4 GB, bueno para 8 GB VRAM)
  - `qwen2.5-7b-instruct-q4_k_m.gguf` (~4.5 GB)
- También puedes usar la **interfaz web del servidor** en `/ui/models` para buscar y descargar modelos directamente.

**Modelos Whisper (audio):**
- Descarga desde [Hugging Face - ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp/tree/main).
- Recomendaciones:
  - `ggml-medium.bin` (~1.5 GB, buen balance velocidad/calidad)
  - `ggml-small.bin` (~466 MB, más rápido)
  - `ggml-large-v3.bin` (~3 GB, mejor calidad)

### 4. Instalar MeigaHub-server (este proyecto)

```powershell
# Descargar desde GitHub
cd C:\Users\<tu-usuario>\Desktop
git clone https://github.com/xenkxp/MeigaHub-server.git servidordellm
cd servidordellm

# Instalar dependencias Python
py -3.12 -m pip install -r requirements.txt

# Copiar y editar la configuración
copy .env.example .env
notepad .env
```

> **Sin git?** Ve a https://github.com/xenkxp/MeigaHub-server → botón **Code** → **Download ZIP**, extrae y continúa desde `cd servidordellm`.

### 5. Configurar `.env`

Edita el archivo `.env` con las rutas reales de tu sistema:

```ini
# === SERVIDOR ===
SERVER_HOST=0.0.0.0
SERVER_PORT=3112

# === LLM (llama.cpp) ===
LLM_BACKEND_URL=http://127.0.0.1:8082
LLM_MODEL_NAME=mistral-7b-instruct-v0.2.Q4_0.gguf
LLM_START_COMMAND=C:\apps\llama.cpp-cuda\llama-server.exe --port 8082 --model C:\models\mistral-7b-instruct-v0.2.Q4_0.gguf --embeddings --pooling mean
LLM_STOP_COMMAND=taskkill /IM llama-server.exe /F

# === WHISPER (whisper.cpp) ===
WHISPER_BACKEND_URL=http://127.0.0.1:8081
WHISPER_MODEL_NAME=ggml-medium.bin
WHISPER_START_COMMAND=C:\apps\whisper.cpp\Release\whisper-server.exe --port 8081 --model C:\models\ggml-medium.bin
WHISPER_STOP_COMMAND=taskkill /IM whisper-server.exe /F

# === OPCIONES ===
AUTO_SWITCH_BACKEND=true          # Cambiar backend automáticamente según endpoint
RESPONSES_MODE=map                # "map" redirige /v1/responses → /v1/chat/completions
                                  # "proxy" reenvía directamente a /v1/responses del backend

# === MODELOS ===
MODELS_DIR=C:\models              # Carpeta donde se almacenan los .gguf
HF_TOKEN=                         # Token de Hugging Face (opcional, para repos privados)
MODELS_LIST_MODE=both             # "active" | "local" | "both"

# === HEALTH CHECKS ===
LLM_HEALTH_PATH=/v1/models
WHISPER_HEALTH_PATH=/v1/models
SWITCH_TIMEOUT_SECONDS=30
```

### 6. Verificar la instalación

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_check.ps1
```

Esto comprobará que existen todos los ejecutables, modelos y carpetas necesarias.

---

## ▶️ Iniciar y detener el servidor

**Con doble clic (más fácil):**
- Iniciar: doble clic en `scripts\start_server.bat`
- Detener: doble clic en `scripts\stop_server.bat`

**Desde PowerShell:**
```powershell
# Iniciar
powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1 -Action start

# Detener
powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1 -Action stop
```

**Desde terminal directamente:**
```powershell
py -3.12 -m uvicorn app.main:app --host 0.0.0.0 --port 3112
```

Una vez iniciado, el servidor estará disponible en: `http://127.0.0.1:3112`

---

## 📡 Endpoints — Referencia completa

### Endpoints compatibles con OpenAI (requieren backend LLM)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/v1/models` | Lista modelos disponibles (compatible OpenAI). Comportamiento según `MODELS_LIST_MODE`. |
| `POST` | `/v1/chat/completions` | Chat completions (formato OpenAI). Soporta campo `"model"` para cambio dinámico. |
| `POST` | `/v1/completions` | Text completions clásico. Soporta campo `"model"`. |
| `POST` | `/v1/embeddings` | Genera embeddings del texto (requiere `--embeddings` en llama-server). |
| `POST` | `/v1/responses` | Responses API. Se redirige a chat/completions (`RESPONSES_MODE=map`) o al backend directo (`proxy`). |

### Endpoints de audio (requieren backend Whisper)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/v1/audio/transcriptions` | Transcribe audio a texto (formato OpenAI). Parámetros: `file`, `model`, `language`, `prompt`, `response_format`, `temperature`. |
| `POST` | `/v1/audio/translations` | Traduce audio a texto en inglés. Mismos parámetros que transcriptions (sin `language`). |

### Endpoints del servidor (siempre disponibles)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/status` | Estado del servidor: backend activo, modelo cargado, VRAM, si está ocupado cambiando. |
| `GET` | `/ui/gpu` | Info de GPU NVIDIA: nombre, VRAM total/libre/usada (JSON). |
| `GET` | `/debug/routes` | Lista todas las rutas registradas en el servidor. |
| `GET/POST/PUT/PATCH/DELETE` | `/debug/echo` | Devuelve info de la petición recibida (para debug). |

### Endpoints de la interfaz de gestión de modelos

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/ui/models` | **Página web** del gestor de modelos GGUF (abrir en navegador). |
| `GET` | `/ui/models/search?q=mistral&only_gguf=1&limit=12` | Busca repos en Hugging Face. |
| `GET` | `/ui/models/files?repo=TheBloke/Mistral-7B-Instruct-v0.2-GGUF` | Lista archivos GGUF de un repo con tamaños. |
| `GET` | `/ui/models/local` | Lista modelos GGUF locales en `MODELS_DIR` con tamaños. |
| `DELETE` | `/ui/models/local` | Borra un modelo local. Body: `{"name": "archivo.gguf"}`. |
| `POST` | `/ui/models/download` | Inicia descarga de un GGUF. Body: `{"repo": "...", "file": "..."}`. Devuelve `{"id": "job-uuid"}`. |
| `GET` | `/ui/models/download/{job_id}` | Consulta progreso de descarga: `status`, `downloaded_bytes`, `total_bytes`. |

---

## 🖥️ Interfaz web — Gestor de modelos

Abre en tu navegador: **http://127.0.0.1:3112/ui/models**

La interfaz tiene tres pestañas:

| Pestaña | Función |
|---|---|
| 🔎 **Buscar** | Busca modelos en Hugging Face. Filtra por repos con archivos GGUF. Clic en un resultado para ir a descargar. |
| 📦 **Descargar** | Introduce un repo de HF, lista sus archivos GGUF, muestra tamaños y estimación de VRAM. El archivo recomendado (⭐) es el más grande que cabe en tu GPU. Barra de progreso en tiempo real. |
| 💾 **Locales** | Lista todos los modelos `.gguf` en tu carpeta `MODELS_DIR`. Muestra tamaño, VRAM estimada y permite borrar. |

La barra superior muestra:
- **Estado del backend** — cuál está activo (LLM/Whisper/ninguno) y qué modelo tiene cargado.
- **Info de GPU** — nombre de la tarjeta, VRAM total y libre.

---

## 🔄 Comportamiento del cambio de backend

```
Petición POST /v1/chat/completions
        │
        ▼
   ¿Backend LLM activo?
        │
   Sí ──┤──── No
   │         │
   │    ¿AUTO_SWITCH_BACKEND=true?
   │         │
   │    Sí ──┤──── No → Error 409
   │         │
   │    1. Detiene Whisper (libera VRAM)
   │    2. Inicia llama-server
   │    3. Espera health check OK
   │         │
   ▼         ▼
   Proxy → llama-server → Respuesta
```

- **Solo un backend activo a la vez** para maximizar VRAM disponible.
- El campo `"model"` en la petición permite cambiar de modelo LLM sin reiniciar el servidor.
- Si el backend ya está activo con el modelo correcto, la petición se reenvía inmediatamente.
- Timeout configurable con `SWITCH_TIMEOUT_SECONDS` (default: 30s).

---

## 📋 Ejemplos de uso

### Chat completions
```bash
curl http://127.0.0.1:3112/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mistral-7b-instruct-v0.2.Q4_0.gguf","messages":[{"role":"user","content":"Hola"}],"max_tokens":100}'
```

### Transcripción de audio
```bash
curl http://127.0.0.1:3112/v1/audio/transcriptions \
  -F file=@audio.wav \
  -F language=es
```

### Estado del servidor
```bash
curl http://127.0.0.1:3112/status
# {"backend":"llm","model":"mistral-7b-instruct-v0.2.Q4_0.gguf","vram":"","busy":false}
```

### Con Python (httpx)
```python
import httpx

r = httpx.post("http://127.0.0.1:3112/v1/chat/completions", json={
    "model": "mistral-7b-instruct-v0.2.Q4_0.gguf",
    "messages": [{"role": "user", "content": "¿Qué es Python?"}],
    "max_tokens": 200
}, timeout=120.0)
print(r.json())
```

### Con OpenAI SDK
```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:3112/v1", api_key="no-key")

response = client.chat.completions.create(
    model="mistral-7b-instruct-v0.2.Q4_0.gguf",
    messages=[{"role": "user", "content": "Hola"}],
    max_tokens=100,
)
print(response.choices[0].message.content)
```

---

## ⚙️ Referencia de variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | Host donde escucha el proxy |
| `SERVER_PORT` | `3112` | Puerto del proxy |
| `LLM_BACKEND_URL` | `http://127.0.0.1:8080` | URL donde corre llama-server |
| `LLM_MODEL_NAME` | *(vacío)* | Nombre del modelo LLM por defecto |
| `LLM_START_COMMAND` | *(vacío)* | Comando completo para arrancar llama-server |
| `LLM_STOP_COMMAND` | *(vacío)* | Comando para detener llama-server |
| `WHISPER_BACKEND_URL` | `http://127.0.0.1:8081` | URL donde corre whisper-server |
| `WHISPER_MODEL_NAME` | *(vacío)* | Nombre del modelo Whisper |
| `WHISPER_START_COMMAND` | *(vacío)* | Comando completo para arrancar whisper-server |
| `WHISPER_STOP_COMMAND` | *(vacío)* | Comando para detener whisper-server |
| `AUTO_SWITCH_BACKEND` | `true` | Cambiar backend automáticamente según endpoint |
| `RESPONSES_MODE` | `map` | `map` = redirige a chat/completions; `proxy` = reenvía directo |
| `MODELS_DIR` | `C:\models` | Carpeta de modelos GGUF |
| `HF_TOKEN` | *(vacío)* | Token de Hugging Face para repos privados |
| `MODELS_LIST_MODE` | `active` | `active` / `local` / `both` — qué devuelve `/v1/models` |
| `LLM_HEALTH_PATH` | `/v1/models` | Ruta para verificar que LLM está listo |
| `WHISPER_HEALTH_PATH` | `/v1/models` | Ruta para verificar que Whisper está listo |
| `SWITCH_TIMEOUT_SECONDS` | `30` | Segundos máximos esperando que un backend arranque |

---

## 🛠️ Scripts incluidos

| Script | Descripción |
|---|---|
| `scripts\start_server.bat` | Doble clic para iniciar (llama a PowerShell internamente) |
| `scripts\stop_server.bat` | Doble clic para detener todo (proxy + backends + liberar VRAM) |
| `scripts\start_server.ps1` | Script principal. Uso: `-Action start` o `-Action stop`. Mata procesos previos, busca Python, arranca llama-server si está configurado, e inicia uvicorn. |
| `scripts\stop_server.ps1` | Alias que llama a `start_server.ps1 -Action stop` |
| `scripts\setup_check.ps1` | Verifica que existen todos los ejecutables, modelos y carpetas del `.env` |
| `scripts\test_llm.py` | Smoke test: prueba `/status`, `/v1/chat/completions`, `/v1/completions` y `/v1/embeddings` |

---

## 🐛 Solución de problemas

| Problema | Solución |
|---|---|
| `backend no disponible` (502) | Verificar que `LLM_START_COMMAND` / `WHISPER_START_COMMAND` apuntan al ejecutable correcto y que el modelo existe. |
| El servidor arranca pero no responde | Comprobar el puerto con `netstat -ano \| findstr :3112` y que no haya otro proceso usándolo. |
| VRAM insuficiente | Usar un modelo con cuantización más agresiva (Q4_0 < Q4_K_M < Q6_K < Q8_0). La UI muestra estimación de VRAM. |
| `cambio automático deshabilitado` (409) | Establecer `AUTO_SWITCH_BACKEND=true` en `.env` o reiniciar manualmente el backend. |
| No detecta la GPU en la UI | Verificar que `nvidia-smi` está en el PATH. Instalar/actualizar drivers NVIDIA. |
| Error de timeout al cambiar backend | Aumentar `SWITCH_TIMEOUT_SECONDS` en `.env` (modelos grandes tardan más en cargar). |
| Puerto ocupado al iniciar | Ejecutar `scripts\stop_server.bat` primero, o usar `scripts\start_server.ps1` que limpia automáticamente. |

---

## 📦 Crear paquete instalable y distribuir

### Paso 1: Generar el paquete

Desde la raíz del proyecto, ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_package.ps1
```

Esto genera `dist\meigahub-server\` con todo lo necesario **excepto modelos y datos personales**:

| Incluido | No incluido (excluido) |
|---|---|
| `app\` — código del servidor | `.env` — se genera al instalar con rutas del usuario |
| `scripts\` — inicio/parada/test | `_gpu_test.txt` — info personal de GPU |
| `apps\` — llama.cpp + whisper.cpp | `__pycache__` — cache compilado |
| `.env.example` — plantilla | `models\*.gguf` — demasiado grandes (~2-10 GB c/u) |
| `installer.ps1` — instalador completo | |
| `INSTALAR.bat` — doble clic para instalar | |

Opcionalmente lo comprime en `dist\meigahub-server.zip`.

### Paso 2: El usuario final instala

El usuario copia la carpeta o descomprime el ZIP y hace doble clic en **`INSTALAR.bat`**.

El instalador hace todo automáticamente:

1. **Pregunta carpeta de instalación** (default: `C:\MeigaHub`)
2. **Detecta Python 3.10+** — si no lo encuentra, ofrece descargarlo e instalarlo automáticamente
3. **Copia todos los archivos** a la carpeta elegida (server, backends, scripts)
4. **Instala dependencias Python** (`pip install -r requirements.txt`)
5. **Genera `.env` configurado** — reemplaza `__INSTALL_DIR__` por la ruta real de instalación
6. **Detecta GPU NVIDIA** — si encuentra CUDA, configura llama.cpp-cuda automáticamente
7. **Verifica la instalación** — comprueba que todo está en su sitio
8. **Crea acceso directo** en el Escritorio (opcional)

> **Nota:** Los modelos GGUF no se incluyen por su tamaño. Tras instalar, el usuario los descarga desde la UI web en `/ui/models` o manualmente a la carpeta `models\`.

---

## 📄 Licencia

MIT

"""
API para mejora de audio con DeepFilterNet3. Uso: POST /enhance con multipart WAV.
"""
import io
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

# Lazy load del modelo en primer request
_model = None
_df_state = None
_MODEL_SR = 48000


def get_model():
    global _model, _df_state
    if _model is None:
        from df import init_df
        _model, _df_state, _, _ = init_df()
    return _model, _df_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Opcional: precargar modelo al arrancar (aumenta cold start pero primer request mas rapido)
    if os.environ.get("PRELOAD_MODEL", "0") == "1":
        get_model()
    yield


app = FastAPI(title="DeepFilterNet3 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok", "model": "DeepFilterNet3"}


@app.post("/enhance")
def enhance_audio(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".wav", ".wave")):
        raise HTTPException(400, "Envia un archivo WAV")
    try:
        content = file.file.read()
    except Exception as e:
        raise HTTPException(400, f"Error leyendo archivo: {e}") from e

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
        tmp_in.write(content)
        tmp_in.flush()
        path_in = tmp_in.name
    try:
        from df import enhance
        from df.io import load_audio, resample

        model, df_state = get_model()
        audio, meta = load_audio(path_in, _MODEL_SR, verbose=False)
        orig_sr = meta.sample_rate
        enhanced = enhance(model, df_state, audio, pad=True)
        enhanced = resample(enhanced.cpu(), _MODEL_SR, orig_sr)

        buf = io.BytesIO()
        import torch
        import torchaudio as ta
        if enhanced.dtype != torch.float32:
            enhanced = enhanced.float() / (1 << 15)
        ta.save(buf, enhanced, orig_sr, format="wav")
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=enhanced.wav"},
        )
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    finally:
        try:
            os.unlink(path_in)
        except OSError:
            pass

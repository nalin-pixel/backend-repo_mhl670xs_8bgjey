import os
import io
import json
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import db, create_document, get_documents

# Optional imports
try:
    from PIL import Image
except Exception:
    Image = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from gtts import gTTS
except Exception:
    gTTS = None

DATA_DIR = os.path.join(os.getcwd(), 'data')
MEDIA_DIR = os.path.join(os.getcwd(), 'media')
TTS_CACHE_DIR = os.path.join(MEDIA_DIR, 'tts')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TTS_CACHE_DIR, exist_ok=True)

RULES_PATH = os.path.join(DATA_DIR, 'rules.json')
CONTENT_PATH = os.path.join(DATA_DIR, 'content.json')

# Default rules and content if files don't exist
DEFAULT_RULES = {
    "red_flags": [
        "chest pain", "shortness of breath", "loss of consciousness", "severe bleeding",
        "stroke", "suicidal", "anaphylaxis", "blue lips", "severe allergic", "poison"
    ]
}

DEFAULT_CONTENT = {
    "self_care": "Based on your symptoms, home care may be sufficient. Rest, hydrate, and monitor your symptoms.",
    "consult": "Please consult a qualified healthcare professional for evaluation within 24-48 hours.",
    "emergency": "This may be an emergency. Seek immediate medical attention or call local emergency services.",
}

# Ensure files exist
if not os.path.exists(RULES_PATH):
    with open(RULES_PATH, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_RULES, f, ensure_ascii=False, indent=2)
if not os.path.exists(CONTENT_PATH):
    with open(CONTENT_PATH, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONTENT, f, ensure_ascii=False, indent=2)

SECRET_KEY = os.getenv('ADMIN_SECRET', 'change-me-secret')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'curesight')

app = FastAPI(title="CureSight API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


# Utility functions

def load_rules() -> Dict[str, Any]:
    with open(RULES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_rules(rules: Dict[str, Any]):
    with open(RULES_PATH, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)

def load_content() -> Dict[str, Any]:
    with open(CONTENT_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_content(content: Dict[str, Any]):
    with open(CONTENT_PATH, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=2)


def strip_pii(text: str) -> str:
    import re
    # Remove emails
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}", "[email removed]", text)
    # Remove phone numbers
    text = re.sub(r"(\\+?\\d[\\d\\-\\s]{7,}\\d)", "[phone removed]", text)
    # Remove addresses patterns (very naive)
    text = re.sub(r"\\b(Street|St\\.|Avenue|Ave\\.|Road|Rd\\.|Block|Apartment|Apt\\.|PO Box)\\b.*", "[address removed]", text, flags=re.IGNORECASE)
    # Remove dates of birth patterns
    text = re.sub(r"\\b(DOB|D.O.B|Date of Birth)[:\\- ]*\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{2,4}", "[dob removed]", text, flags=re.IGNORECASE)
    # Remove patient identifiers common tokens
    text = re.sub(r"\\b(Patient Name|Name|Guardian|Age|Sex|MRN|UHID|ID)[: ]+[^\\n]+", "[identifier removed]", text, flags=re.IGNORECASE)
    return text


def filter_medically_relevant(text: str) -> str:
    # Keep lines with common medical tokens
    keywords = [
        'tab', 'tablet', 'cap', 'capsule', 'syrup', 'ml', 'mg', 'mcg', 'bid', 'tid', 'qid', 'od',
        'diagnosis', 'dx', 'rx', 'bp', 'hr', 'temp', 'fever', 'cough', 'pain', 'infection', 'asthma', 'diabetes'
    ]
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    kept: List[str] = []
    for l in lines:
        lower = l.lower()
        if any(k in lower for k in keywords):
            kept.append(l)
    # If nothing kept, fallback to first 10 lines after PII stripping
    if not kept:
        kept = lines[:10]
    return "\n".join(kept)


def basic_transcribe(audio_bytes: bytes, lang: str = 'en') -> str:
    # Placeholder transcription. In production, wire up Whisper or Vosk
    return ""  # Return empty to indicate unavailable


def synthesize_speech_cached(text: str, lang: str) -> str:
    """Return filesystem path to cached TTS mp3 for given text+lang."""
    key = hashlib.sha256(f"{lang}:::{text}".encode('utf-8')).hexdigest()
    path = os.path.join(TTS_CACHE_DIR, f"{key}.mp3")
    if os.path.exists(path):
        return path
    if gTTS is None:
        raise HTTPException(status_code=500, detail="TTS engine not available. Install gTTS.")
    tts = gTTS(text=text, lang=lang.split('-')[0])
    tts.save(path)
    return path


def analyze_text_engine(text: str) -> Dict[str, Any]:
    """Simple rule-based analysis returning category, severity, recommendation, and reason."""
    content = load_content()
    t = text.lower()
    category = 'general'
    reason = ''

    if any(w in t for w in ['fever', 'cold', 'cough', 'sore throat']):
        category = 'respiratory'
    if any(w in t for w in ['chest', 'heart', 'palpitation']):
        category = 'cardiac'
    if any(w in t for w in ['rash', 'itch', 'allergy']):
        category = 'dermatology'

    severity = 'low'
    if any(w in t for w in ['moderate', 'severe', 'high', 'intense', 'cannot sleep']):
        severity = 'medium'
    if any(w in t for w in ['unbearable', 'fainted', 'bleeding', 'blue lips', 'not breathing']):
        severity = 'high'

    recommendation = content.get('self_care') if severity == 'low' else content.get('consult')

    # Red flag overrides
    rules = load_rules()
    for flag in rules.get('red_flags', []):
        if flag.lower() in t:
            severity = 'emergency'
            recommendation = content.get('emergency')
            reason = f"Red flag triggered: {flag}"
            break

    return {
        'category': category,
        'severity': severity,
        'recommendation': recommendation,
        'reason': reason or None
    }


# Auth utilities

def make_token(username: str) -> str:
    ts = str(int(datetime.now(timezone.utc).timestamp()))
    sig = hmac.new(SECRET_KEY.encode('utf-8'), f"{username}:{ts}".encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{username}.{ts}.{sig}"

def verify_token(token: str) -> bool:
    try:
        username, ts, sig = token.split('.')
        expected = hmac.new(SECRET_KEY.encode('utf-8'), f"{username}:{ts}".encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return False
        # Expire after 7 days
        ts_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return datetime.now(timezone.utc) - ts_dt < timedelta(days=7)
    except Exception:
        return False


def require_admin(token: str = Query(..., alias='token')):
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# Models
class AnalyzeTextIn(BaseModel):
    text: str
    language: Optional[str] = 'en-US'

class AnalyzeOut(BaseModel):
    category: str
    severity: str
    recommendation: str
    reason: Optional[str] = None
    query_id: Optional[str] = None

class LoginIn(BaseModel):
    username: str
    password: str

class NoteIn(BaseModel):
    query_id: str
    note: str
    author: Optional[str] = None


@app.get("/")
def read_root():
    return {"message": "CureSight Backend Running"}

@app.get("/test")
def test_database():
    status = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "collections": []
    }
    try:
        if db is not None:
            status["database"] = "✅ Connected"
            status["collections"] = db.list_collection_names()
    except Exception as e:
        status["database"] = f"⚠️ {str(e)[:60]}"
    return status


@app.post("/api/analyze/text", response_model=AnalyzeOut)
async def analyze_text(payload: AnalyzeTextIn):
    base_text = (payload.text or '').strip()
    if not base_text:
        raise HTTPException(status_code=400, detail="Text is required")
    pii_stripped = strip_pii(base_text)
    relevant = filter_medically_relevant(pii_stripped)
    combined = f"{relevant}"
    analysis = analyze_text_engine(combined)

    doc = {
        'patient_language': payload.language,
        'input_type': 'text',
        'symptom_text': base_text,
        'ocr_text': None,
        'combined_text': combined,
        'analysis': analysis,
    }
    try:
        qid = create_document('query', doc)
    except Exception:
        qid = None
    analysis['query_id'] = qid
    return analysis


# NOTE: Accept raw bytes to avoid python-multipart dependency
@app.post("/api/analyze/audio", response_model=AnalyzeOut)
async def analyze_audio(request: Request, language: str = Query('en-US'), symptoms: Optional[str] = Query(None)):
    data = await request.body()
    transcript = basic_transcribe(data, lang=language)
    base_text = (symptoms or '') + (' ' + transcript if transcript else '')
    base_text = base_text.strip()
    if not base_text:
        raise HTTPException(status_code=400, detail="No transcribed text available. Configure speech-to-text engine or provide symptoms text.")
    pii = strip_pii(base_text)
    relevant = filter_medically_relevant(pii)
    combined = relevant
    analysis = analyze_text_engine(combined)
    doc = {
        'patient_language': language,
        'input_type': 'audio',
        'symptom_text': symptoms,
        'ocr_text': None,
        'combined_text': combined,
        'analysis': analysis,
    }
    try:
        qid = create_document('query', doc)
    except Exception:
        qid = None
    analysis['query_id'] = qid
    return analysis


@app.post("/api/analyze/image", response_model=AnalyzeOut)
async def analyze_image(request: Request, language: str = Query('en-US'), symptoms: Optional[str] = Query(None)):
    content = await request.body()
    extracted = ""
    if Image is None:
        raise HTTPException(status_code=500, detail="Pillow not available to load images. Install Pillow or provide text input.")
    try:
        image = Image.open(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {str(e)}")

    if pytesseract is None:
        # Fallback: no OCR available
        extracted = ""
    else:
        try:
            extracted = pytesseract.image_to_string(image)
        except Exception:
            extracted = ""

    extracted = extracted.strip()
    pii = strip_pii(extracted)
    relevant_rx = filter_medically_relevant(pii)

    base_text = ((symptoms or '').strip() + '\n' + relevant_rx).strip()
    if not base_text:
        raise HTTPException(status_code=400, detail="No text available from image or symptoms. Install Tesseract/pytesseract or provide symptoms text.")

    analysis = analyze_text_engine(base_text)
    doc = {
        'patient_language': language,
        'input_type': 'image',
        'symptom_text': symptoms,
        'ocr_text': relevant_rx,
        'combined_text': base_text,
        'analysis': analysis,
    }
    try:
        qid = create_document('query', doc)
    except Exception:
        qid = None
    analysis['query_id'] = qid
    return analysis


@app.get("/api/tts")
async def tts_endpoint(text: str, lang: str = 'en-US'):
    if not text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    path = synthesize_speech_cached(text.strip(), lang)
    return FileResponse(path, media_type='audio/mpeg', filename='speech.mp3')


# Admin endpoints
@app.post("/api/admin/login")
async def admin_login(body: LoginIn):
    if body.username == ADMIN_USERNAME and body.password == ADMIN_PASSWORD:
        token = make_token(body.username)
        return {"token": token}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/admin/logs")
async def admin_logs(limit: int = 20, token: None = Depends(require_admin)):
    try:
        docs = get_documents('query', {}, limit=limit)
        # Convert ObjectId to str
        out = []
        for d in docs:
            d['_id'] = str(d.get('_id'))
            out.append(d)
        # show recent first
        out.reverse()
        return {"items": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/rules")
async def get_rules(token: None = Depends(require_admin)):
    return load_rules()

@app.put("/api/admin/rules")
async def update_rules(payload: Dict[str, Any], token: None = Depends(require_admin)):
    save_rules(payload)
    return {"status": "ok"}

@app.get("/api/admin/content")
async def get_content_route(token: None = Depends(require_admin)):
    return load_content()

@app.put("/api/admin/content")
async def update_content_route(payload: Dict[str, Any], token: None = Depends(require_admin)):
    save_content(payload)
    return {"status": "ok"}

@app.post("/api/admin/notes")
async def add_doctor_note(body: NoteIn, token: None = Depends(require_admin)):
    try:
        nid = create_document('doctornote', body.dict())
        return {"note_id": nid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

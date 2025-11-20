# CureSight

CureSight is a minimal, bilingual-friendly symptom analysis web app with two portals:
- Patient: enter symptoms as text, upload voice, or upload prescription image. The system extracts text, removes personal identifiers, keeps relevant medical information, and analyzes everything with rule-based overrides for dangerous keywords. Results include disease category, severity level, recommendation, and optional reason. Results can be spoken in English, Hindi, Telugu, or Kannada with audio caching.
- Doctor/Admin: password-protected dashboard to view recent queries, extracted prescription text, add doctor notes, and edit red-flag rules and guidance content stored as JSON.

## Features
- Text, audio (upload), and image (prescription) analysis
- OCR with pytesseract (optional) — stores only medically relevant text after PII removal
- Rule-based red flag overrides
- Multilingual TTS via gTTS with caching
- Minimal large-button UI with language selector and speech output
- Admin login with token, view logs, edit rules/content, add notes
- MongoDB persistence for all queries and notes

## Running Locally

### Prerequisites
- Node 18+
- Python 3.10+
- MongoDB database URL and name (DATABASE_URL, DATABASE_NAME). If not provided, data endpoints still work but persistence is disabled.
- Optional: Tesseract OCR installed in the OS if you want image OCR

### Environment
Create two `.env` files (already present in this template):
- Frontend: set `VITE_BACKEND_URL` to the backend URL (e.g., http://localhost:8000)
- Backend: set `DATABASE_URL`, `DATABASE_NAME` for MongoDB, and optionally `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_SECRET`

### Install and Start
The workspace tooling installs both and starts dev servers automatically. Manually:

Backend:
1. `pip install -r requirements.txt`
2. `uvicorn main:app --reload --port 8000`

Frontend:
1. `npm install`
2. `npm run dev` (opens on port 3000)

### OCR Models
- Install the system Tesseract binary. On macOS: `brew install tesseract`. On Ubuntu: `sudo apt-get install tesseract-ocr`.
- Language data files go to your Tesseract installation path. This project calls `pytesseract.image_to_string` directly.

### Speech
- TTS uses gTTS (Google Text-to-Speech). No extra model files needed. Audio files are cached under `backend/media/tts`.
- STT (speech-to-text) is left as a stub in the backend for portability. For full voice transcription, wire Whisper/Vosk and update `basic_transcribe` in backend.

### Admin Portal
Default credentials (override via env):
- Username: `admin`
- Password: `curesight`

Capabilities:
- View recent patient queries and OCR snippets
- Add doctor notes attached to a query
- Edit red-flag rules in `data/rules.json`
- Edit guidance content in `data/content.json`

### Endpoints Summary
- POST `/api/analyze/text` { text, language }
- POST `/api/analyze/audio` multipart (file, language, symptoms)
- POST `/api/analyze/image` multipart (file, language, symptoms)
- GET `/api/tts?text=...&lang=en-US` → mp3 stream
- POST `/api/admin/login` {username, password}
- GET `/api/admin/logs?token=...`
- GET/PUT `/api/admin/rules?token=...`
- GET/PUT `/api/admin/content?token=...`
- POST `/api/admin/notes?token=...` { query_id, note }

### Multilingual Testing
- Use the language selector on the patient page and click Speak on the result. The app sends the text to `/api/tts` and caches audio by hash to avoid regeneration.

### Spline Asset
The hero sections on both home and patient views use the provided Spline cover in an iframe, full-width.

### Notes
- This is not a medical device. Not for emergencies.
- PII scrubbing and medical relevance filtering are heuristic; review before production use.

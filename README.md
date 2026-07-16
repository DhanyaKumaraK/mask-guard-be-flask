# Mask Guard — PII Data Masking & Protection

A Flask-based REST API that detects and masks Personally Identifiable Information (PII) in plain text and JSON payloads using the Ollama `llama3` model running locally. Built with a RAG (Retrieval-Augmented Generation) workflow, session-based authentication, and configurable per-user masking policies.
<img width="1330" height="537" alt="{7EB99D0C-6C5D-4DE4-A13F-694F30B2CAEC}" src="https://github.com/user-attachments/assets/bfee84b8-7ba2-463e-844d-48d185f1694f" />
<img width="1366" height="674" alt="{F479514A-03B6-4BE2-B020-455C676B9F51}" src="https://github.com/user-attachments/assets/629f59e7-65a9-4b7d-8d99-94043c61dfa5" />
<img width="1366" height="682" alt="{3A438DB1-E77F-4378-BD16-E14B70E35EC8}" src="https://github.com/user-attachments/assets/ecacdab8-0f33-418f-bd4e-4e0b2215e445" />


---

## Problem & Target User

Organizations handling sensitive data — HR teams, support agents, developers debugging logs — frequently need to share or store documents without exposing personal details. Mask Guard provides a simple API that any front-end (e.g., a React app) can call to automatically detect and mask PII before the data is transmitted, displayed, or stored.

---

## Features

- **PII Detection & Masking** — Detects 9 PII types (name, phone, email, passport, SSN, address, DOB, credit card, IP address) in text or JSON
- **Three Masking Styles**
  - `placeholder` → `[name]`, `[phone_number]`
  - `redacted` → `[redacted name]`, `[redacted phone_number]`
  - `asterisk` → `[**** ****** *]`, `[**********]`
- **Masking Policies** — Users create and manage named policies that encode their preferred masking style (full CRUD, auth-protected)
- **Masking Logs** — Every masking request is logged with metadata (no PII stored)
- **RAG Workflow** — Prompts are constructed from an internal PII knowledge base, giving the LLM structured masking rules per PII type
- **Session Authentication** — Register, login, and logout with bcrypt-hashed passwords
- **Swagger UI** — Interactive API docs at `/apidocs/`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Framework | Flask 3.x |
| Database | SQLite (via `sqlite3`) |
| AI Model | Ollama `llama3` (local) |
| Auth | Flask session cookies + Werkzeug password hashing |
| API Docs | Flasgger (Swagger 2.0) |
| CORS | Flask-CORS |

---

## Data Model Description

```
users
  ├── id           INTEGER PK
  ├── username     TEXT UNIQUE
  ├── password     TEXT (bcrypt hash)
  └── created_at   TEXT

masking_policies  (user-owned, CRUD-protected)
  ├── id           INTEGER PK
  ├── user_id      INTEGER FK → users.id
  ├── name         TEXT
  ├── masking_style INTEGER  (1=placeholder, 2=redacted, 3=asterisk)
  ├── description  TEXT
  ├── is_default   INTEGER
  ├── created_at   TEXT
  └── updated_at   TEXT

masking_logs  (tracking metadata — NO PII stored)
  ├── id                 INTEGER PK
  ├── user_id            INTEGER FK → users.id
  ├── policy_id          INTEGER FK → masking_policies.id (nullable)
  ├── format_type        TEXT  (text | json)
  ├── masking_style      INTEGER
  ├── pii_types_detected TEXT  (comma-separated type names)
  ├── char_count_input   INTEGER
  ├── char_count_output  INTEGER
  └── created_at         TEXT
```

**Relationships:**
- `masking_policies.user_id → users.id` — a user owns their policies
- `masking_logs.user_id → users.id` — a user owns their log history
- `masking_logs.policy_id → masking_policies.id` — each log records which policy was applied

---

## Auth Flow

1. `POST /api/register` — create account (password stored as bcrypt hash)
2. `POST /api/login` — validates credentials, stores `user_id` + `username` in Flask session cookie
3. All protected routes check `session['user_id']` before proceeding
4. `POST /api/logout` — clears the session

---

## AI / RAG Workflow

```
React App
   │  POST /api/generate { input_data, format_type, masking_style }
   ▼
Flask API
   │
   ├─ 1. Auth check (session)
   │
   ├─ 2. RETRIEVAL — retrieve_pii_context()
   │      Returns all 9 PII type entries from the internal PII_KNOWLEDGE_BASE Which is PII_REGISTRY
   │      (each entry has: pii_type, description, examples, masking_guide per style)
   │
   ├─ 3. PROMPT CONSTRUCTION — build_rag_prompt()
   │      Assembles: masking style rules + per-PII-type guidance + user input
   │      into a structured prompt for the LLM
   │
   ├─ 4. MODEL CALL — ollama.generate(model='llama3', prompt=prompt)
   │
   ├─ 5. RESPONSE PARSING — parse_llm_response()
   │      Splits output into: masked_content | DETECTED_PII_TYPES
   │      If no PII found → returns input unchanged + notice field (§4.7)
   │
   ├─ 6. LOG metadata (no PII stored) → masking_logs table
   │
   └─ 7. RETURN to client:
          masked_output, detected_pii_types, sources (PII KB entries used), masking_style_name
```

**Sources displayed to user (`sources` field in response):** every response includes the list of PII knowledge base entries that were used to build the prompt, satisfying the requirement to show supporting sources (§4.6).

**Weak/missing context strategy (§4.7):** if the LLM reports no PII was detected, the response returns the original input unchanged and includes a `"notice": "No PII detected in the provided input."` field so the client can display appropriate feedback.

---

## Setup Instructions

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10 or higher |
| pip | latest |
| Ollama | latest ([install](https://ollama.com/download)) |

### 1 — Clone the repository

```bash
git clone <your-repo-url>
cd mask-guard-be-flask
```

### 2 — Create and activate a virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python -m venv venv
source venv/bin/activate
```

### 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### 4 — Pull the Ollama model

```bash
ollama pull llama3
```

Verify it works:

```bash
ollama run llama3 "Say hello"
```

> The Ollama server must be running whenever you use the `/api/generate` endpoint.
> It starts automatically on most systems after installation, or run `ollama serve`.

---

## Run Instructions

```bash
python app.py
```

The server starts at: **`http://127.0.0.1:5000`**

Interactive Swagger docs: **`http://127.0.0.1:5000/apidocs/`**

---

## Required Environment Variables

No `.env` file is required for local development. The `app.secret_key` is generated randomly at startup. For production, set a **fixed** secret key:

```bash
# Windows PowerShell
$env:SECRET_KEY = "your-long-random-secret-key"

# macOS / Linux
export SECRET_KEY="your-long-random-secret-key"
```

Then update `app.py`:

```python
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
```

---

## API Route Descriptions

| Method | Route | Auth | Description |
|---|---|---|---|
| GET | `/` | No | Health check |
| POST | `/api/register` | No | Create a new user account |
| POST | `/api/login` | No | Login and start a session |
| POST | `/api/logout` | Yes | Clear the current session |
| POST | `/api/generate` | Yes | **Mask PII** in text or JSON (main feature) |
| GET | `/api/pii-types` | No | List all supported PII types and masking rules |
| GET | `/api/policies` | Yes | List all masking policies for the current user |
| POST | `/api/policies` | Yes | Create a new masking policy |
| GET | `/api/policies/<id>` | Yes | Get a single masking policy |
| PUT | `/api/policies/<id>` | Yes | Update a masking policy |
| DELETE | `/api/policies/<id>` | Yes | Delete a masking policy |
| GET | `/api/logs` | Yes | List masking history (metadata only, no PII) |

---

## Example Requests & Tasks

### Mask plain text (Style 1 — placeholder)

```http
POST /api/generate
Content-Type: application/json

{
  "input_data": "Name: Dhanya Kumara K\nPhone Number: 4545789889\nPassport Number: 8787-8788-989",
  "format_type": "text",
  "masking_style": 1
}
```

**Response:**
```json
{
  "masked_output": "Name: [name]\nPhone Number: [phone_number]\nPassport Number: [passport_number]",
  "detected_pii_types": ["name", "phone_number", "passport_number"],
  "masking_style": 1,
  "masking_style_name": "placeholder",
  "sources": [...]
}
```

---

### Mask JSON (Style 2 — redacted)

```http
POST /api/generate
Content-Type: application/json

{
  "input_data": "{\"name\": \"Dhanya Kumara K\", \"phone_number\": \"4545789889\", \"email\": \"Dhanya@gmail.com\", \"passport_number\": \"8787-8788-989\"}",
  "format_type": "json",
  "masking_style": 2
}
```

**Response:**
```json
{
  "masked_output": "{\n  \"name\": \"[redacted name]\",\n  \"phone_number\": \"[redacted phone_number]\",\n  \"email\": \"[redacted email]\",\n  \"passport_number\": \"[redacted passport_number]\"\n}",
  "detected_pii_types": ["name", "phone_number", "email", "passport_number"],
  "masking_style": 2,
  "masking_style_name": "redacted",
  "sources": [...]
}
```

---

### Use a saved policy

```http
POST /api/generate
Content-Type: application/json

{
  "input_data": "Contact: Alice, 555-0100",
  "format_type": "text",
  "policy_id": 3
}
```

---

### Create a masking policy

```http
POST /api/policies
Content-Type: application/json

{
  "name": "Audit Redaction Policy",
  "masking_style": 2,
  "description": "Used for generating audit-safe reports",
  "is_default": false
}
```

---

## Seed Data

On first run, the database is automatically seeded with:

- **User:** `admin` / `password123`
- **Three masking policies** for the admin user (one per masking style)

---

## Deployment Notes

> **Important:** This app is designed for local development. Production deployment requires the following changes:

| Concern | Local | Production |
|---|---|---|
| Secret key | `os.urandom(24)` (random per restart) | Fixed env variable (`SECRET_KEY`) |
| Session storage | Flask cookie session | Redis or database-backed session |
| Ollama model | Runs locally on `localhost:11434` | Must run on same server or via secured internal network |
| Database | SQLite file (`project.db`) | PostgreSQL or MySQL |
| HTTPS | Not configured | Required (use nginx + Let's Encrypt) |
| CORS | Open (`*`) | Restrict to known front-end origin |

**Ollama in production:** The `llama3` model requires ~8 GB RAM. Cloud deployment is possible but requires a GPU-enabled instance (e.g., AWS g4dn, GCP A2) with Ollama installed. Alternatively, swap `ollama.generate` for a cloud LLM API (OpenAI, Anthropic) for hosted deployments.

---

## Known Limitations

- Currently restricted to masking **text and JSON** formats only
- Uses only the **Ollama llama3 model running locally** — requires Ollama to be installed and running
- Session cookies are not persistent across server restarts (random `secret_key`)
- SQLite is not suitable for concurrent production traffic
- Masking accuracy depends on LLM output quality; complex or ambiguous PII may not be detected

---

## Future Improvements

- **File upload support:** Accept `.txt`, `.json`, `.pdf`, `.doc`, `.ppt`, `.xlsx`, `.csv` files and return a masked downloadable version
- **Persistent sessions:** Redis-backed sessions so sessions survive restarts
- **Organization accounts:** Multi-tenant support with org-level default policies
- **Audit export:** Export masking logs as CSV/PDF for compliance reporting
- **Custom PII patterns:** Let users define their own regex-based PII types
- **Cloud LLM option:** Switch between local Ollama and cloud APIs (OpenAI, Anthropic)
- **Confidence scoring:** Report per-field confidence that a value is PII

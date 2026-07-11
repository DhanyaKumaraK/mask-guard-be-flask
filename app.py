import sqlite3
import os
import logging
from flask import Flask, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import ollama
from flask_cors import CORS
from flasgger import Swagger
from pii_rules import PII_REGISTRY
from masking_styles import MASKING_STYLES

# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------
app = Flask(__name__)

# Allow the React dev server to send session cookies cross-origin.
# In production, replace "*" with your exact front-end origin, e.g.:
#   CORS(app, supports_credentials=True, origins=["https://yourapp.com"])
CORS(app, supports_credentials=True, origins=["http://localhost:5173", "http://127.0.0.1:5173"])

swagger = Swagger(app)

# Secret key required to securely sign session cookies
app.secret_key = os.urandom(24)

# Required for cross-origin cookies (React on :3000 → Flask on :5000)
# SameSite=None + Secure=True is needed for cross-site; during local dev
# we use Lax + Secure=False so it works over plain HTTP.
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False    # Set True in production (HTTPS only)
app.config['SESSION_COOKIE_HTTPONLY'] = True

DATABASE = 'project.db'

# ---------------------------------------------------------------------------
# Logging (tracking only — NO PII is ever written to logs)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('maskguard.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Creates all required tables if they do not exist and seeds initial data.

    Tables:
      - users              : Auth model (§3.1)
      - masking_policies   : User-owned masking config, CRUD-protected (§3.2, §3.3, §3.5)
      - masking_logs       : Per-request tracking log — NO PII stored (§3.2, §3.4)

    Relationships:
      masking_policies.user_id  → users.id
      masking_logs.user_id      → users.id
      masking_logs.policy_id    → masking_policies.id
    """
    with get_db() as conn:
        # --- Users table ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT UNIQUE NOT NULL,
                password   TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        ''')

        # --- Masking Policies table (user-owned resource with CRUD) ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS masking_policies (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                name          TEXT NOT NULL,
                masking_style INTEGER NOT NULL DEFAULT 1,
                description   TEXT,
                is_default    INTEGER DEFAULT 0,
                created_at    TEXT DEFAULT (datetime('now')),
                updated_at    TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        # --- Masking Logs table (tracking metadata only — zero PII stored) ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS masking_logs (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id            INTEGER NOT NULL,
                policy_id          INTEGER,
                format_type        TEXT NOT NULL,
                masking_style      INTEGER NOT NULL,
                pii_types_detected TEXT,
                char_count_input   INTEGER,
                char_count_output  INTEGER,
                created_at         TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id)   REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (policy_id) REFERENCES masking_policies(id) ON DELETE SET NULL
            )
        ''')

        conn.commit()

        # --- Seed: admin user (§3.6) ---
        try:
            hashed_pw = generate_password_hash('password123')
            conn.execute(
                'INSERT INTO users (username, password) VALUES (?, ?)',
                ('admin', hashed_pw)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # Already seeded

        # --- Seed: default masking policies for admin ---
        try:
            admin = conn.execute(
                'SELECT id FROM users WHERE username = ?', ('admin',)
            ).fetchone()
            if admin:
                admin_id = admin['id']
                existing = conn.execute(
                    'SELECT id FROM masking_policies WHERE user_id = ?', (admin_id,)
                ).fetchone()
                if not existing:
                    for style_id, style_info in MASKING_STYLES.items():
                        conn.execute(
                            '''INSERT INTO masking_policies
                               (user_id, name, masking_style, description, is_default)
                               VALUES (?, ?, ?, ?, ?)''',
                            (
                                admin_id,
                                f"{style_info['name'].title()} Masking Policy",
                                style_id,
                                style_info['description'],
                                1 if style_id == 1 else 0
                            )
                        )
                    conn.commit()
        except Exception as e:
            logger.warning(f"Seed policies skipped: {e}")


# Run database initialisation on startup
init_db()


# ---------------------------------------------------------------------------
# RAG Helpers  (Rubric §4.2 – §4.3)
# ---------------------------------------------------------------------------

def retrieve_pii_context(format_type: str) -> list:
    """
    Retrieves relevant PII knowledge base entries.  (§4.2 — Retrieval step)
    Currently returns the full knowledge base; future versions may filter by
    domain/format for faster, more targeted prompts.
    """
    return PII_REGISTRY  # all 9 PII types are always relevant


def build_rag_prompt(input_data: str, format_type: str, masking_style: int) -> tuple:
    """
    Constructs a RAG-enhanced prompt from retrieved PII knowledge base context.
    (§4.3 — Prompt construction using retrieved context)

    Returns:
        prompt  (str)  — the fully built prompt for the LLM
        sources (list) — the PII knowledge base entries used as context
    """
    style_info = MASKING_STYLES[masking_style]
    sources = retrieve_pii_context(format_type)  # §4.2

    # Build knowledge base context block
    kb_context = "\n".join([
        f"  • {entry['pii_type']}: {entry['description']}\n"
        f"    Rule ({style_info['name']}): {entry['masking_guide'][style_info['name']]}"
        for entry in sources
    ])

    style_examples = {
        1: 'Name: [name]\nPhone Number: [phone_number]\nEmail: [email]\nPassport: [passport_number]',
        2: 'Name: [redacted name]\nPhone Number: [redacted phone_number]\nEmail: [redacted email]',
        3: 'Name: [**** ****** *]\nPhone Number: [**********]\nEmail: [*****@*****.***]'
    }

    if format_type == 'json':
        task_instruction = (
            "The input is a JSON object. Inspect each VALUE for PII. "
            "Return ONLY the masked JSON with the exact same keys and structure — no extra text before or after the JSON block. "
            "After the JSON block, on a new line output: DETECTED_PII_TYPES: <comma-separated list of detected PII type names>"
        )
    else:
        task_instruction = (
            "The input is plain text. Identify and mask all PII values inline. "
            "You MUST preserve the exact structure, layout, and labels of the original text. "
            "Return ONLY the masked text — no explanation, no preamble. "
            "After the masked text, on a new line output: DETECTED_PII_TYPES: <comma-separated list of detected PII type names>"
        )

    prompt = f"""You are a PII (Personally Identifiable Information) masking engine for Mask Guard.

═══════════════════════════════════════════
MASKING STYLE: {style_info['name'].upper()} — {style_info['description']}
═══════════════════════════════════════════

MASKING EXAMPLE (style {masking_style}):
{style_examples[masking_style]}

═══════════════════════════════════════════
PII KNOWLEDGE BASE — MASKING RULES
═══════════════════════════════════════════
{kb_context}

═══════════════════════════════════════════
INPUT ({format_type.upper()}):
═══════════════════════════════════════════
{input_data}

═══════════════════════════════════════════
TASK:
═══════════════════════════════════════════
{task_instruction}

CRITICAL RULES:
1. ONLY modify the PII values. You MUST PRESERVE all original text, labels (e.g. 'Name:', 'Email:'), spaces, newlines, and punctuation EXACTLY.
2. For style 3 (asterisk): match the character count of the original PII value with * characters and wrap in [ ].
3. If you detect no PII, return the input unchanged and output DETECTED_PII_TYPES: none
4. Do NOT output separator lines like ═══════════════════════════════════════════.
5. Do NOT add commentary, disclaimers, or any text beyond the masked output and DETECTED_PII_TYPES line.
"""
    return prompt, sources


def parse_llm_response(raw_response: str) -> tuple:
    """
    Parses the LLM output into (masked_content, detected_pii_types).
    Handles the case where no PII was found.  (§4.7 — Strategy for weak/missing context)
    """
    parts = raw_response.strip().split('DETECTED_PII_TYPES:')
    masked_content = parts[0].strip()
    
    # Remove any stray prompt separator lines the model might have copied
    masked_content = masked_content.replace('═══════════════════════════════════════════', '').strip()
    
    detected_types = []

    if len(parts) > 1:
        raw_types = parts[1].strip()
        if raw_types.lower() not in ('none', ''):
            detected_types = [t.strip() for t in raw_types.split(',') if t.strip()]

    return masked_content, detected_types


# ===========================================================================
# API ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    """
    Backend Homepage
    ---
    tags:
      - Health
    summary: Check that the API is running
    responses:
      200:
        description: API is running successfully
        schema:
          type: object
          properties:
            message:
              type: string
              example: Mask Guard API is running successfully!
    """
    return jsonify({"message": "Mask Guard API is running successfully!"})


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@app.route('/api/register', methods=['POST'])
def register():
    """
    Register a New User
    ---
    tags:
      - Authentication
    summary: Create a new user account
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        description: Credentials for the new account
        schema:
          type: object
          required:
            - username
            - password
          properties:
            username:
              type: string
              example: alice
              description: Unique username
            password:
              type: string
              example: supersecurepassword
              description: Plain-text password (stored as bcrypt hash)
    responses:
      201:
        description: User registered successfully
        schema:
          type: object
          properties:
            message:
              type: string
              example: "User 'alice' registered successfully!"
      400:
        description: Missing or empty fields
        schema:
          type: object
          properties:
            error:
              type: string
              example: Missing username or password
      409:
        description: Username already exists
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Username 'alice' is already taken"
    """
    data = request.get_json()

    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"error": "Missing username or password"}), 400

    username = data['username'].strip()
    password = data['password']

    if not username or not password:
        return jsonify({"error": "Username and password cannot be empty"}), 400

    hashed_pw = generate_password_hash(password)

    try:
        with get_db() as conn:
            conn.execute(
                'INSERT INTO users (username, password) VALUES (?, ?)',
                (username, hashed_pw)
            )
            conn.commit()
        return jsonify({"message": f"User '{username}' registered successfully!"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Username '{username}' is already taken"}), 409


@app.route('/api/login', methods=['POST'])
def login():
    """
    User Login
    ---
    tags:
      - Authentication
    summary: Authenticate a user and start a session
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        description: User credentials
        schema:
          type: object
          required:
            - username
            - password
          properties:
            username:
              type: string
              example: admin
            password:
              type: string
              example: password123
    responses:
      200:
        description: Login successful
        schema:
          type: object
          properties:
            message:
              type: string
              example: Login successful
            user:
              type: string
              example: admin
      400:
        description: Missing username or password
        schema:
          type: object
          properties:
            error:
              type: string
              example: Missing username or password
      401:
        description: Invalid credentials
        schema:
          type: object
          properties:
            error:
              type: string
              example: Invalid credentials
    """
    data = request.get_json()

    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"error": "Missing username or password"}), 400

    username = data['username']
    password = data['password']

    with get_db() as conn:
        user = conn.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()

    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({"message": "Login successful", "user": username}), 200

    return jsonify({"error": "Invalid credentials"}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    """
    User Logout
    ---
    tags:
      - Authentication
    summary: Clear the current user session
    responses:
      200:
        description: Logout successful
        schema:
          type: object
          properties:
            message:
              type: string
              example: Logged out successfully
    """
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


# ---------------------------------------------------------------------------
# PII Masking  (AI / RAG — Rubric §4)
# ---------------------------------------------------------------------------

@app.route('/api/generate', methods=['POST'])
def generate_text():
    """
    Mask PII Data (Text or JSON)
    ---
    tags:
      - PII Masking
    summary: Detect and mask PII in plain text or JSON using Ollama llama3
    description: >-
      Protected endpoint. Accepts plain text or a JSON string containing PII and
      returns a masked version. Uses a RAG-enhanced prompt built from the internal
      PII knowledge base (9 PII types). The Ollama llama3 model runs locally.
      No PII data is stored — only request metadata is logged for tracking.
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - input_data
            - format_type
          properties:
            input_data:
              type: string
              description: Raw text or JSON string containing PII to be masked
              example: "Name: Dhanya Kumara K\nPhone Number: 4545789889\nPassport Number: 8787-8788-989"
            format_type:
              type: string
              enum: [text, json]
              description: Format of the input — either plain text or JSON
              example: text
            masking_style:
              type: integer
              enum: [1, 2, 3]
              description: >
                Masking output style.
                1 = placeholder ([name], [phone_number]),
                2 = redacted ([redacted name], [redacted phone_number]),
                3 = asterisk ([**** ****** *], [**********])
              default: 1
              example: 1
            policy_id:
              type: integer
              description: >
                Optional. ID of a saved MaskingPolicy owned by the current user.
                When provided, masking_style is taken from the policy.
              example: 1
    responses:
      200:
        description: PII masked successfully
        schema:
          type: object
          properties:
            masked_output:
              type: string
              description: The input with all PII replaced according to the masking style
              example: "Name: [name]\nPhone Number: [phone_number]\nPassport Number: [passport_number]"
            detected_pii_types:
              type: array
              description: List of PII types detected in the input
              items:
                type: string
              example: [name, phone_number, passport_number]
            format_type:
              type: string
              example: text
            masking_style:
              type: integer
              example: 1
            masking_style_name:
              type: string
              example: placeholder
            sources:
              type: array
              description: PII knowledge base entries used to construct the prompt (RAG sources)
              items:
                type: object
                properties:
                  pii_type:
                    type: string
                    example: name
                  description:
                    type: string
                    example: Full name, first name, last name
            notice:
              type: string
              description: Present when no PII was detected in the input
              example: No PII detected in the provided input.
      400:
        description: Missing or invalid request fields
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Invalid 'format_type'. Must be 'text' or 'json'"
      401:
        description: Unauthorized — user must be logged in
        schema:
          type: object
          properties:
            error:
              type: string
              example: Unauthorized. Please log in first.
      404:
        description: Policy not found or not owned by the current user
        schema:
          type: object
          properties:
            error:
              type: string
              example: Policy ID 5 not found or not owned by you
      500:
        description: Ollama model error
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Ollama error: connection refused"
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    input_data   = data.get('input_data', '').strip()
    format_type  = data.get('format_type', 'text').lower()
    policy_id    = data.get('policy_id')

    if not input_data:
        return jsonify({"error": "Missing 'input_data' in request body"}), 400

    if format_type not in ('text', 'json'):
        return jsonify({"error": "Invalid 'format_type'. Must be 'text' or 'json'"}), 400

    # Use masking_style from payload if provided, otherwise fallback to policy_id, then default to 1
    if 'masking_style' in data:
        masking_style = int(data['masking_style'])
    elif policy_id:
        with get_db() as conn:
            policy = conn.execute(
                'SELECT * FROM masking_policies WHERE id = ? AND user_id = ?',
                (policy_id, session['user_id'])
            ).fetchone()
        if not policy:
            return jsonify({"error": f"Policy ID {policy_id} not found or not owned by you"}), 404
        masking_style = policy['masking_style']
    else:
        masking_style = 1

    if masking_style not in (1, 2, 3):
        return jsonify({"error": "Invalid 'masking_style'. Must be 1, 2, or 3"}), 400

    # --- RAG: build context-aware prompt from PII knowledge base (§4.3) ---
    prompt, sources = build_rag_prompt(input_data, format_type, masking_style)

    try:
        # --- Model call (§4.4) ---
        response = ollama.generate(model='llama3', prompt=prompt)
        raw_output = response['response']

        # --- Parse generated response (§4.5) ---
        masked_output, detected_pii_types = parse_llm_response(raw_output)

        # --- Log metadata — no PII stored ---
        with get_db() as conn:
            conn.execute(
                '''INSERT INTO masking_logs
                   (user_id, policy_id, format_type, masking_style,
                    pii_types_detected, char_count_input, char_count_output)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    session['user_id'],
                    policy_id,
                    format_type,
                    masking_style,
                    ','.join(detected_pii_types),
                    len(input_data),
                    len(masked_output)
                )
            )
            conn.commit()

        logger.info(
            f"[MASK] user_id={session['user_id']} format={format_type} "
            f"style={masking_style} pii_detected={detected_pii_types}"
        )

        style_info = MASKING_STYLES[masking_style]

        response_body = {
            "masked_output":       masked_output,
            "detected_pii_types":  detected_pii_types,
            "format_type":         format_type,
            "masking_style":       masking_style,
            "masking_style_name":  style_info['name'],
            # §4.6 — Supporting sources displayed to the user
            "sources": [
                {"pii_type": s["pii_type"], "description": s["description"]}
                for s in sources
            ]
        }

        # §4.7 — Strategy for weak / missing context
        if not detected_pii_types:
            response_body["notice"] = "No PII detected in the provided input."

        return jsonify(response_body), 200

    except Exception as e:
        logger.error(f"[MASK_ERROR] user_id={session['user_id']} error={str(e)}")
        return jsonify({"error": f"Ollama error: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Masking Policies — CRUD (Rubric §3.3, §3.5)
# ---------------------------------------------------------------------------

@app.route('/api/policies', methods=['GET'])
def list_policies():
    """
    List Masking Policies
    ---
    tags:
      - Masking Policies
    summary: Retrieve all masking policies belonging to the logged-in user
    responses:
      200:
        description: List of the user's masking policies
        schema:
          type: object
          properties:
            policies:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    example: 1
                  name:
                    type: string
                    example: Placeholder Masking Policy
                  masking_style:
                    type: integer
                    example: 1
                  masking_style_name:
                    type: string
                    example: placeholder
                  description:
                    type: string
                    example: Replace PII with label placeholders
                  is_default:
                    type: boolean
                    example: true
                  created_at:
                    type: string
                    example: "2024-01-15 10:30:00"
                  updated_at:
                    type: string
                    example: "2024-01-15 10:30:00"
      401:
        description: Unauthorized
        schema:
          type: object
          properties:
            error:
              type: string
              example: Unauthorized. Please log in first.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM masking_policies WHERE user_id = ? ORDER BY masking_style',
            (session['user_id'],)
        ).fetchall()

    policies = []
    for row in rows:
        style_name = MASKING_STYLES.get(row['masking_style'], {}).get('name', 'unknown')
        policies.append({
            "id":                row['id'],
            "name":              row['name'],
            "masking_style":     row['masking_style'],
            "masking_style_name": style_name,
            "description":       row['description'],
            "is_default":        bool(row['is_default']),
            "created_at":        row['created_at'],
            "updated_at":        row['updated_at']
        })

    return jsonify({"policies": policies}), 200


@app.route('/api/policies', methods=['POST'])
def create_policy():
    """
    Create a Masking Policy
    ---
    tags:
      - Masking Policies
    summary: Create a new masking policy for the logged-in user
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - name
            - masking_style
          properties:
            name:
              type: string
              example: My Custom Policy
            masking_style:
              type: integer
              enum: [1, 2, 3]
              example: 2
              description: >
                1=placeholder, 2=redacted, 3=asterisk
            description:
              type: string
              example: Redact all PII for audit reports
            is_default:
              type: boolean
              example: false
    responses:
      201:
        description: Policy created successfully
        schema:
          type: object
          properties:
            message:
              type: string
              example: Policy created successfully
            policy_id:
              type: integer
              example: 4
      400:
        description: Missing or invalid fields
        schema:
          type: object
          properties:
            error:
              type: string
              example: Missing required fields name and masking_style
      401:
        description: Unauthorized
        schema:
          type: object
          properties:
            error:
              type: string
              example: Unauthorized. Please log in first.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    data = request.get_json()
    if not data or 'name' not in data or 'masking_style' not in data:
        return jsonify({"error": "Missing required fields: name and masking_style"}), 400

    name          = data['name'].strip()
    masking_style = int(data['masking_style'])
    description   = data.get('description', '').strip()
    is_default    = int(bool(data.get('is_default', False)))

    if not name:
        return jsonify({"error": "Policy name cannot be empty"}), 400

    if masking_style not in (1, 2, 3):
        return jsonify({"error": "Invalid masking_style. Must be 1, 2, or 3"}), 400

    with get_db() as conn:
        cursor = conn.execute(
            '''INSERT INTO masking_policies
               (user_id, name, masking_style, description, is_default)
               VALUES (?, ?, ?, ?, ?)''',
            (session['user_id'], name, masking_style, description, is_default)
        )
        conn.commit()
        policy_id = cursor.lastrowid

    return jsonify({"message": "Policy created successfully", "policy_id": policy_id}), 201


@app.route('/api/policies/<int:policy_id>', methods=['GET'])
def get_policy(policy_id):
    """
    Get a Single Masking Policy
    ---
    tags:
      - Masking Policies
    summary: Retrieve a specific masking policy by ID (must belong to the logged-in user)
    parameters:
      - in: path
        name: policy_id
        required: true
        type: integer
        example: 1
    responses:
      200:
        description: Policy details
        schema:
          type: object
          properties:
            id:
              type: integer
              example: 1
            name:
              type: string
              example: Placeholder Masking Policy
            masking_style:
              type: integer
              example: 1
            masking_style_name:
              type: string
              example: placeholder
            description:
              type: string
            is_default:
              type: boolean
            created_at:
              type: string
            updated_at:
              type: string
      401:
        description: Unauthorized
      404:
        description: Policy not found
        schema:
          type: object
          properties:
            error:
              type: string
              example: Policy not found
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    with get_db() as conn:
        row = conn.execute(
            'SELECT * FROM masking_policies WHERE id = ? AND user_id = ?',
            (policy_id, session['user_id'])
        ).fetchone()

    if not row:
        return jsonify({"error": "Policy not found"}), 404

    style_name = MASKING_STYLES.get(row['masking_style'], {}).get('name', 'unknown')
    return jsonify({
        "id":                row['id'],
        "name":              row['name'],
        "masking_style":     row['masking_style'],
        "masking_style_name": style_name,
        "description":       row['description'],
        "is_default":        bool(row['is_default']),
        "created_at":        row['created_at'],
        "updated_at":        row['updated_at']
    }), 200


@app.route('/api/policies/<int:policy_id>', methods=['PUT'])
def update_policy(policy_id):
    """
    Update a Masking Policy
    ---
    tags:
      - Masking Policies
    summary: Update an existing masking policy (must belong to the logged-in user)
    consumes:
      - application/json
    parameters:
      - in: path
        name: policy_id
        required: true
        type: integer
        example: 1
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              example: Updated Policy Name
            masking_style:
              type: integer
              enum: [1, 2, 3]
              example: 3
            description:
              type: string
              example: Updated description
            is_default:
              type: boolean
              example: true
    responses:
      200:
        description: Policy updated successfully
        schema:
          type: object
          properties:
            message:
              type: string
              example: Policy updated successfully
      400:
        description: Invalid masking_style
      401:
        description: Unauthorized
      404:
        description: Policy not found
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    data = request.get_json() or {}

    with get_db() as conn:
        row = conn.execute(
            'SELECT * FROM masking_policies WHERE id = ? AND user_id = ?',
            (policy_id, session['user_id'])
        ).fetchone()

        if not row:
            return jsonify({"error": "Policy not found"}), 404

        name          = data.get('name', row['name']).strip()
        masking_style = int(data.get('masking_style', row['masking_style']))
        description   = data.get('description', row['description'])
        is_default    = int(bool(data.get('is_default', row['is_default'])))

        if masking_style not in (1, 2, 3):
            return jsonify({"error": "Invalid masking_style. Must be 1, 2, or 3"}), 400

        conn.execute(
            '''UPDATE masking_policies
               SET name=?, masking_style=?, description=?, is_default=?,
                   updated_at=datetime('now')
               WHERE id=? AND user_id=?''',
            (name, masking_style, description, is_default, policy_id, session['user_id'])
        )
        conn.commit()

    return jsonify({"message": "Policy updated successfully"}), 200


@app.route('/api/policies/<int:policy_id>', methods=['DELETE'])
def delete_policy(policy_id):
    """
    Delete a Masking Policy
    ---
    tags:
      - Masking Policies
    summary: Delete a masking policy (must belong to the logged-in user)
    parameters:
      - in: path
        name: policy_id
        required: true
        type: integer
        example: 1
    responses:
      200:
        description: Policy deleted successfully
        schema:
          type: object
          properties:
            message:
              type: string
              example: Policy deleted successfully
      401:
        description: Unauthorized
      404:
        description: Policy not found
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    with get_db() as conn:
        row = conn.execute(
            'SELECT id FROM masking_policies WHERE id = ? AND user_id = ?',
            (policy_id, session['user_id'])
        ).fetchone()

        if not row:
            return jsonify({"error": "Policy not found"}), 404

        conn.execute(
            'DELETE FROM masking_policies WHERE id = ? AND user_id = ?',
            (policy_id, session['user_id'])
        )
        conn.commit()

    return jsonify({"message": "Policy deleted successfully"}), 200


# ---------------------------------------------------------------------------
# Masking Logs  (tracking metadata — no PII stored)
# ---------------------------------------------------------------------------

@app.route('/api/logs', methods=['GET'])
def list_logs():
    """
    List Masking Logs
    ---
    tags:
      - Logs
    summary: Retrieve masking request history for the logged-in user (metadata only, no PII)
    parameters:
      - in: query
        name: limit
        type: integer
        default: 50
        description: Maximum number of log records to return
        example: 20
    responses:
      200:
        description: List of masking log entries (no PII stored)
        schema:
          type: object
          properties:
            logs:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    example: 1
                  format_type:
                    type: string
                    example: text
                  masking_style:
                    type: integer
                    example: 1
                  masking_style_name:
                    type: string
                    example: placeholder
                  pii_types_detected:
                    type: array
                    items:
                      type: string
                    example: [name, phone_number]
                  char_count_input:
                    type: integer
                    example: 120
                  char_count_output:
                    type: integer
                    example: 95
                  policy_id:
                    type: integer
                    example: 1
                  created_at:
                    type: string
                    example: "2024-01-15 11:00:00"
      401:
        description: Unauthorized
        schema:
          type: object
          properties:
            error:
              type: string
              example: Unauthorized. Please log in first.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    limit = request.args.get('limit', 50, type=int)

    with get_db() as conn:
        rows = conn.execute(
            '''SELECT * FROM masking_logs WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?''',
            (session['user_id'], limit)
        ).fetchall()

    logs = []
    for row in rows:
        style_name = MASKING_STYLES.get(row['masking_style'], {}).get('name', 'unknown')
        pii_types = [t for t in (row['pii_types_detected'] or '').split(',') if t]
        logs.append({
            "id":                row['id'],
            "format_type":       row['format_type'],
            "masking_style":     row['masking_style'],
            "masking_style_name": style_name,
            "pii_types_detected": pii_types,
            "char_count_input":  row['char_count_input'],
            "char_count_output": row['char_count_output'],
            "policy_id":         row['policy_id'],
            "created_at":        row['created_at']
        })

    return jsonify({"logs": logs}), 200


# ---------------------------------------------------------------------------
# PII Knowledge Base Reference
# ---------------------------------------------------------------------------

@app.route('/api/pii-types', methods=['GET'])
def list_pii_types():
    """
    List Supported PII Types
    ---
    tags:
      - PII Masking
    summary: Returns all PII types supported by the masking engine with descriptions and masking rules
    responses:
      200:
        description: Full PII knowledge base
        schema:
          type: object
          properties:
            pii_types:
              type: array
              items:
                type: object
                properties:
                  pii_type:
                    type: string
                    example: name
                  description:
                    type: string
                    example: Full name, first name, last name
                  examples:
                    type: array
                    items:
                      type: string
                    example: [John Doe, Alice Smith]
                  masking_guide:
                    type: object
                    properties:
                      placeholder:
                        type: string
                        example: Replace with [name]
                      redacted:
                        type: string
                        example: Replace with [redacted name]
                      asterisk:
                        type: string
                        example: Replace each character with *, wrap in brackets
            masking_styles:
              type: object
              description: Available masking style options
    """
    return jsonify({
        "pii_types":     PII_REGISTRY,
        "masking_styles": MASKING_STYLES
    }), 200


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
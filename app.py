import sqlite3
import os
from flask import Flask, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import ollama
from flask_cors import CORS
from flasgger import Swagger

app = Flask(__name__)
CORS(app)
swagger = Swagger(app)

# Secret key is required to securely sign session cookies
app.secret_key = os.urandom(24) 

DATABASE = 'project.db'

def get_db():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Creates a basic users table if it doesn't exist and seeds a dummy user."""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        
        # Seed a test user (username: admin, password: password123)
        try:
            hashed_pw = generate_password_hash('password123')
            conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', ('admin', hashed_pw))
            conn.commit()
        except sqlite3.IntegrityError:
            # User already exists
            pass

# Initialize the database when the script runs
init_db()

# --- API ENDPOINTS ---
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

@app.route('/api/register', methods=['POST'])
def register():
    """
    Handles new user registration.
    ---
    tags:
      - Authentication
    parameters:
      - in: body
        name: body
        required: true
        description: User credentials for creating a new account.
        schema:
          type: object
          required:
            - username
            - password
          properties:
            username:
              type: string
              example: alice
              description: Unique username for the account.
            password:
              type: string
              example: supersecurepassword
              description: Plain text password to be hashed.
    responses:
      201:
        description: User registered successfully.
        schema:
          type: object
          properties:
            message:
              type: string
              example: User 'alice' registered successfully!
      400:
        description: Bad Request (missing or empty fields).
        schema:
          type: object
          properties:
            error:
              type: string
              example: Missing username or password
      409:
        description: Conflict (username already exists).
        schema:
          type: object
          properties:
            error:
              type: string
              example: Username 'alice' is already taken
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
            conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_pw))
            conn.commit()
        return jsonify({"message": f"User '{username}' registered successfully!"}), 201
    except sqlite3.IntegrityError:
        # This triggers if the username unique constraint is violated
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
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    
    if user and check_password_hash(user['password'], password):
        # Store user info in the Flask session cookie
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


@app.route('/api/generate', methods=['POST'])
def generate_text():
    """
    Generate AI Text
    ---
    tags:
      - AI
    summary: Send a prompt to the Ollama LLM and receive a generated response
    description: >-
      Protected endpoint. The user must be logged in (active session) before
      calling this route. Internally calls the locally-running Ollama model
      (llama3) with the provided prompt.
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        description: Prompt to send to the AI model
        schema:
          type: object
          required:
            - prompt
          properties:
            prompt:
              type: string
              example: What is mask guard used for?
    responses:
      200:
        description: AI-generated response returned successfully
        schema:
          type: object
          properties:
            author:
              type: string
              example: admin
            response:
              type: string
              example: Mask Guard is a safety tool that...
      400:
        description: Missing prompt in the request body
        schema:
          type: object
          properties:
            error:
              type: string
              example: Missing 'prompt' in request body
      401:
        description: User is not authenticated
        schema:
          type: object
          properties:
            error:
              type: string
              example: Unauthorized. Please log in first.
      500:
        description: Ollama model error
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Ollama error: connection refused"
    """
    # Check if user session exists
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401
    
    data = request.get_json()
    prompt = data.get('prompt') if data else None
    
    if not prompt:
        return jsonify({"error": "Missing 'prompt' in request body"}), 400
    
    try:
        # Make sure you have the model pulled locally (e.g., `ollama pull llama3`)
        response = ollama.generate(model='llama3', prompt=prompt)
        return jsonify({
            "author": session['username'],
            "response": response['response']
        }), 200
    except Exception as e:
        return jsonify({"error": f"Ollama error: {str(e)}"}), 500


if __name__ == '__main__':
    # Run the server on localhost:5000
    app.run(host='127.0.0.1', port=5000, debug=True)
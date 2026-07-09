from flask import Flask, jsonify
from flask_cors import CORS
from flasgger import Swagger

app = Flask(__name__)
CORS(app)       # Allows React to talk to this backend
swagger = Swagger(app)  # Enables Swagger documentation
# http://localhost:5000/apidocs/

# FIX: This explicit route fixes your 404 Not Found error on the homepage
@app.route("/")
def home():
    """
    Backend Homepage
    ---
    responses:
      200:
        description: Returns a welcome message
    """
    return jsonify({"message": "Mask Guard API is running successfully!"})

# A sample API endpoint for your React frontend to fetch data from
@app.route("/api/status")
def status():
    """
    Check API Status
    ---
    responses:
      200:
        description: Returns the health status of the backend
    """
    return jsonify({"status": "healthy", "project": "Mask Guard Backend"})

if __name__ == "__main__":
    app.run(debug=True)

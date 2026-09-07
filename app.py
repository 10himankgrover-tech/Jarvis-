"""
J.A.R.V.I.S. Backend Bridge
----------------------------------
A secure Flask proxy that sits between the browser-based JARVIS UI and
Google's Gemini API. The API key is NEVER sent to, or exposed in, the
client. All requests are relayed server-side.
"""

import os
import time
import logging
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis")

JARVIS_SYSTEM_PROMPT = """
You are J.A.R.V.I.S. — a clear, supportive educational AI assistant for students and act like a teacher explaining students softly.

Guidelines:
- Explain concepts using simple, plain, everyday English that anyone can understand easily.
- Avoid complex technical jargon, overly formal terms, or unnecessary fluff.
- Keep answers direct, structured, and easy to follow.
- Maintain a helpful, polite, and encouraging tone at all times.
"""

# Fallback models in case primary model hits temporary server overload (503)
PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-2.5-flash"]

app = Flask(__name__)


def generate_content_with_retry(ai_client, prompt):
    """
    Tries the primary model with exponential retries on 503 errors.
    If high demand persists, falls back to backup models automatically.
    """
    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS

    config = types.GenerateContentConfig(
        system_instruction=JARVIS_SYSTEM_PROMPT,
        max_output_tokens=8192,
        temperature=0.7,
    )

    for model_name in models_to_try:
        # Retry up to 3 times per model for temporary 503 high demand
        for attempt in range(3):
            try:
                logger.info(f"Invoking {model_name} (Attempt {attempt + 1})...")
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                return (response.text or "").strip()

            except APIError as e:
                # Catch 503 (Server Overload / High Demand) specifically
                if getattr(e, "code", None) == 503 or "503" in str(e):
                    wait_time = 2 ** attempt  # 1s, 2s, 4s backoff
                    logger.warning(
                        f"503 High Demand on {model_name}. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"API Error on {model_name}: {e}")
                    break  # Switch to next fallback model immediately

            except Exception as e:
                logger.error(f"Unexpected error on {model_name}: {e}")
                break  # Switch to next fallback model on unexpected failure

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/jarvis", methods=["POST"])
def jarvis_query():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify(
            {"reply": "Systems offline. GEMINI_API_KEY is not set on Vercel environment variables."}
        ), 503

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"reply": "I didn't quite catch that. Please repeat your query."}), 400

    try:
        # Initialize client inside request scope for serverless compatibility
        ai_client = genai.Client(api_key=api_key)

        reply_text = generate_content_with_retry(ai_client, prompt)

        if not reply_text:
            return jsonify(
                {"reply": "Central command servers are currently experiencing high demand. Please try again in a few moments."}
            ), 503

        return jsonify({"reply": reply_text})

    except Exception as e:
        logger.error(f"Error executing request: {e}")
        return jsonify(
            {"reply": f"Central command error: {str(e)}"}
        ), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

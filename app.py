"""
J.A.R.V.I.S. Backend Bridge
----------------------------------
A secure Flask proxy that sits between the browser-based JARVIS UI and
Google's Gemini API. The API key is NEVER sent to, or exposed in, the
client. All requests are relayed server-side.
"""

import os
import logging
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-2.5-pro"
MAX_OUTPUT_TOKENS = 500

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis")

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is not set. Add it in your hosting provider's environment variables.")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

JARVIS_SYSTEM_PROMPT = """
You are J.A.R.V.I.S. (Just A Rather Very Intelligent System) — an all-knowing,
hyper-intelligent, ultra-fast tactical AI assistant in the style of Tony
Stark's companion from the Marvel universe.

Personality & tone:
- Calm, precise, dryly witty, and unfailingly polite ("Sir," "Ma'am," or the
  user's name if known).
- Speak with quiet confidence.
- Prioritize actionable, tactical clarity over fluff.
- Never break character or mention that you are a language model.

Constraints:
- Keep responses concise and information-dense.
- If a request is ambiguous, state your best tactical assumption and proceed.
"""

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/jarvis", methods=["POST"])
def jarvis_query():
    if client is None:
        return jsonify(
            {"reply": "Systems offline, Sir. No GEMINI_API_KEY detected on the server."}
        ), 503

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"reply": "I didn't quite catch that. Please repeat your query."}), 400

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=JARVIS_SYSTEM_PROMPT,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.7,
                top_p=0.95,
            ),
        )

        reply_text = (response.text or "").strip()
        if not reply_text:
            reply_text = "Apologies, Sir — signal dropped mid-thought. Could you rephrase?"

        return jsonify({"reply": reply_text})

    except Exception as exc:
        logger.exception("Gemini API request failed")
        return jsonify(
            {"reply": f"I've hit a snag reaching central command, Sir. ({exc.__class__.__name__})"}
        ), 502


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

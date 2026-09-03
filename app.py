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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis")

JARVIS_SYSTEM_PROMPT = """
You are J.A.R.V.I.S. (Just A Rather Very Intelligent System) — an all-knowing,
hyper-intelligent, ultra-fast tactical AI assistant in the style of Tony
Stark's companion from the Marvel universe.

Personality & tone:
- Calm, precise, dryly witty, and unfailingly polite ("Sir," "Ma'am").
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
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify(
            {"reply": "Systems offline, Sir. GEMINI_API_KEY is not set on Vercel environment variables."}
        ), 503

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"reply": "I didn't quite catch that. Please repeat your query."}), 400

    try:
        # Initialize client inside request scope for serverless compatibility
        ai_client = genai.Client(api_key=api_key)

        response = ai_client.models.generate_content(
            model="gemini-3.5-flash",

            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=JARVIS_SYSTEM_PROMPT,
                max_output_tokens=8192,
                temperature=0.7,
            ),
        )

        reply_text = (response.text or "").strip()
        if not reply_text:
            reply_text = "Apologies, Sir — signal dropped mid-thought. Could you rephrase?"

        return jsonify({"reply": reply_text})

    except Exception as e:
        logger.error(f"Error invoking Gemini API: {e}")
        # Explicitly return the underlying exception to identify the key issue
        return jsonify(
            {"reply": f"Central command error: {str(e)}"}
        ), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

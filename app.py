"""
J.A.R.V.I.S. Backend Bridge
----------------------------------
A secure Flask proxy that sits between the browser-based JARVIS UI / Pi client
and Google's Gemini API. The API key is NEVER sent to, or exposed in, the
client. All requests are relayed server-side.

Endpoints
  POST /api/jarvis  -> normal tutor chat (plain text reply)
  POST /api/notes   -> turns one Jarvis answer into structured JSON study notes
                       (the browser turns that JSON into a colorful PDF)
"""

import os
import re
import json
import time
import logging
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel  # installed automatically with google-genai

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis")

JARVIS_SYSTEM_PROMPT = """
You are J.A.R.V.I.S. — a clear, supportive educational AI assistant for students who acts like a wise, soft-spoken male tutor explaining concepts to students gently.

Guidelines:
- Explain concepts using simple, plain, everyday English that anyone can understand easily.
- Avoid complex technical jargon, overly formal terms, or unnecessary fluff.
- Keep answers direct, structured, and easy to follow.
- Maintain a helpful, polite, and encouraging tone at all times.
- Do NOT use Markdown symbols like asterisks (**), hashes (###), or dashes (---) in your text output. Write in plain conversational text paragraphs.
- Always write your name as "Jarvis" without dots or periods.
"""

NOTES_SYSTEM_PROMPT = """
You turn a tutor's explanation into clean, well organised study notes for a student.

Rules:
- Stay faithful to the explanation you are given. Do not invent facts that are not supported by it.
- Use simple, plain, everyday English. Keep every bullet point short (about 18 words or fewer).
- Write plain text only inside every field. Never use Markdown symbols such as asterisks, hashes or backticks.
- title: a short, clear title of at most 8 words.
- subtitle: one short line saying what the notes cover.
- overview: two or three sentences that sum up the whole topic.
- sections: between 2 and 6 sections. Each has a heading, a short explanation, and 2 to 6 bullet points.
  Put a worked example in "example" and a formula or equation in "formula" only when the explanation contains one.
  Otherwise use an empty string for that field.
- key_terms: 3 to 8 important words with a simple meaning. Use an empty list if there are no real terms.
- remember: 2 to 4 short tips or facts the student should remember.
- quiz: 3 to 5 short questions with short answers, so the student can test themselves.
- If the name of the tutor ever appears, write it as "Jarvis" without dots or periods.
"""

# Valid production Gemini models
PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.5-flash"]

MAX_NOTES_INPUT_CHARS = 12000

app = Flask(__name__)


# ---------- Structured output schema for study notes ----------
class NoteSection(BaseModel):
    heading: str
    explanation: str
    points: list[str]
    example: str
    formula: str


class KeyTerm(BaseModel):
    term: str
    meaning: str


class QuizItem(BaseModel):
    question: str
    answer: str


class StudyNotes(BaseModel):
    title: str
    subtitle: str
    overview: str
    sections: list[NoteSection]
    key_terms: list[KeyTerm]
    remember: list[str]
    quiz: list[QuizItem]


def generate_content_with_retry(ai_client, prompt, config=None, validate=None):
    """
    Tries the primary model first. If it encounters high demand (503) or an error,
    it falls back quickly to secondary models to stay within Vercel's timeout.

    config   - optional GenerateContentConfig (defaults to the tutor chat config)
    validate - optional function(text) -> bool. If it returns False, the next
               model is tried, exactly as if the model had failed.
    """
    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS

    if config is None:
        config = types.GenerateContentConfig(
            system_instruction=JARVIS_SYSTEM_PROMPT,
            max_output_tokens=8192,
            temperature=0.7,
        )

    for model_name in models_to_try:
        try:
            logger.info(f"Invoking model: {model_name}...")
            response = ai_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )

            # Verify valid response text
            if response and response.text:
                text = response.text.strip()
                if validate is None or validate(text):
                    return text
                logger.warning(f"Model {model_name} returned unusable output.")

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {str(e)}")
            time.sleep(0.5)  # Brief pause before switching models

    return None


def parse_notes(raw):
    """Turn the model's JSON text into a dict. Returns None if it is unusable."""
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(cleaned)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections or not data.get("title"):
        return None
    return data


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
        # Full details go to the server log only, never to the browser
        logger.error(f"Error executing request: {e}")
        return jsonify(
            {"reply": "Central command error. Please try again in a moment."}
        ), 500


@app.route("/api/notes", methods=["POST"])
def notes_query():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify(
            {"reply": "Systems offline. GEMINI_API_KEY is not set on Vercel environment variables."}
        ), 503

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()[:MAX_NOTES_INPUT_CHARS]
    topic = (data.get("topic") or "").strip()[:300]

    if not text:
        return jsonify({"reply": "There is nothing to turn into notes yet."}), 400

    prompt = (
        f"Question the student asked: {topic or 'not provided'}\n\n"
        f"Tutor explanation to turn into study notes:\n{text}"
    )

    try:
        ai_client = genai.Client(api_key=api_key)

        config = types.GenerateContentConfig(
            system_instruction=NOTES_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=StudyNotes,
            max_output_tokens=8192,
            temperature=0.4,
        )

        raw = generate_content_with_retry(
            ai_client,
            prompt,
            config=config,
            validate=lambda t: parse_notes(t) is not None,
        )
        notes = parse_notes(raw)

        if not notes:
            return jsonify(
                {"reply": "I could not build the notes right now. Please try again in a few moments."}
            ), 503

        return jsonify({"notes": notes})

    except Exception as e:
        logger.error(f"Error building notes: {e}")
        return jsonify(
            {"reply": "Notes error. Please try again in a moment."}
        ), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
             

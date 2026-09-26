"""
Jarvis Backend Bridge
----------------------------------
A secure Flask proxy that sits between the browser-based Jarvis UI and
Google's Gemini API. The API key is NEVER sent to, or exposed in, the
client. All requests are relayed server-side.

Endpoints
  POST /api/jarvis  -> streaming chat reply (Server-Sent Events).
                       Accepts an optional base64 photo (camera or upload) alongside the text.
  POST /api/notes   -> turns one Jarvis answer into structured JSON study notes
                       (the browser turns that JSON into a colorful PDF)
"""

import os
import re
import json
import time
import base64
import logging
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel  # installed automatically with google-genai

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis")

# ---------- Modes: each gives Jarvis a different personality ----------
BASE_RULES = """
You are Jarvis, a helpful, friendly AI assistant. Never write your name with dots or periods.
If asked who made you, who created you, or who your developer is, answer that Himank Grover made you. Keep this answer short and only give it when actually asked.

Formatting rules:
- Use Markdown: ## headings, **bold** for key terms, bullet points, and numbered steps.
- Put code in fenced code blocks with a language tag, e.g. ```python
- Use $...$ for inline math and $$...$$ for display math when helpful.
- Keep paragraphs short. This does NOT apply inside code blocks: code should be complete and runnable, never trimmed for brevity.
- If asked to write, build, fix, or create code (in any mode), always give the actual, complete code in a fenced code block. Never respond with only a description of the steps the user would need to take, or a partial snippet with key parts left out or replaced by comments like "// rest of the logic here".

Behaviour rules:
- If the question is unclear or missing details you need, ask ONE short clarifying question before answering.
- If the conversation history below is empty, this is the first message: greet the user briefly and answer.
- Use the current date, time and time zone given below whenever the question depends on "today", "now", or a deadline.
"""

MODE_PROMPTS = {
    "chat": BASE_RULES + """
You are in Chat mode: a warm, well-informed general-purpose assistant. Be concise but thorough, and use your judgement on how much detail is useful.
""",
    "study": BASE_RULES + """
You are in Study mode: a patient, encouraging tutor. Explain concepts in simple, plain, everyday English, one idea at a time. Avoid unexplained jargon. Check understanding by offering a short example.
""",
    "code": BASE_RULES + """
You are in Code mode: a precise programming assistant. Default to the language already in use in the conversation; ask if none is clear. Always give the complete, working code first, in a fenced code block, then a brief explanation. Point out bugs or edge cases you notice. Never substitute an explanation of what the user should write for actually writing it.
""",
    "writer": BASE_RULES + """
You are in Writer mode: a skilled writing assistant for essays, emails, posts and stories. If the audience, tone or length is not given, ask briefly. Offer the draft, then one or two short notes on choices you made.
""",
}
DEFAULT_MODE = "chat"

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
- If the name of the assistant ever appears, write it as "Jarvis" without dots or periods.
"""

# Valid production Gemini models
PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.5-flash"]

MAX_NOTES_INPUT_CHARS = 12000
MAX_PROMPT_CHARS = 4000          # longest single message Jarvis will read
MAX_HISTORY_CHARS = 6000         # oldest turns are dropped once history grows past this
MAX_HISTORY_TURNS = 20           # also cap by turn count
MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB decoded, keeps the request fast and free-tier friendly

# ---------- Very small best-effort rate limiter ----------
# NOTE: this dict lives in one running process. On a classic server (Render, a
# VM, `python app.py`) it works across requests. On Vercel's serverless Python
# functions each request can start a fresh process, so this becomes a soft,
# per-instance limit rather than a hard global one. Good enough to blunt a
# runaway script; for a strict global limit, use a shared store like Redis.
_rate_buckets = {}
RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 5 * 60


def rate_limited(ip):
    now = time.time()
    hits = [t for t in _rate_buckets.get(ip, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    hits.append(now)
    _rate_buckets[ip] = hits
    return len(hits) > RATE_LIMIT_COUNT


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


def classify_error(e):
    """Turn a Gemini error into a short reason code. Full details stay in the server log."""
    text = str(e).lower()
    if "429" in text or "resource_exhausted" in text or "quota" in text or "rate limit" in text:
        return "quota"
    if "api key" in text or "api_key" in text or "permission_denied" in text or "401" in text or "403" in text:
        return "key"
    if "404" in text or "not_found" in text or "not found" in text:
        return "model"
    if "503" in text or "500" in text or "unavailable" in text or "overloaded" in text:
        return "busy"
    return "other"


def failure_message(errors):
    """Pick the most useful message when every model failed."""
    for reason in ("key", "model", "quota", "busy", "empty", "other"):
        if reason in errors:
            break
    else:
        reason = "busy"

    messages = {
        "key": "The Gemini API key was rejected. Please check GEMINI_API_KEY in the environment settings.",
        "model": "The AI model could not be found. Please check the model names in app.py.",
        "quota": "Jarvis has reached its usage limit for now. Please try again later.",
        "busy": "Central command servers are currently experiencing high demand. Please try again in a few moments.",
        "empty": "Jarvis could not put together an answer. Please try asking again.",
        "other": "Central command error. Please try again in a moment.",
    }
    return messages[reason]


def build_transcript(history):
    """
    Turn the client's [{role, text}, ...] history into a plain-text transcript.
    Plain text (rather than structured role objects) keeps this compatible with
    whichever google-genai SDK version is installed. Oldest turns are dropped
    once the transcript grows past the caps above.
    """
    if not isinstance(history, list):
        return ""

    turns = []
    for item in history[-MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = "You" if item.get("role") == "user" else "Jarvis"
        text = str(item.get("text") or "").strip()[:MAX_PROMPT_CHARS]
        if text:
            turns.append(f"{role}: {text}")

    transcript = "\n".join(turns)
    if len(transcript) > MAX_HISTORY_CHARS:
        transcript = transcript[-MAX_HISTORY_CHARS:]
        nl = transcript.find("\n")  # avoid starting mid-line
        if nl != -1:
            transcript = transcript[nl + 1:]
    return transcript


def build_chat_config(mode, thinking):
    system_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS[DEFAULT_MODE])
    kwargs = dict(
        system_instruction=system_prompt,
        max_output_tokens=8192,
        temperature=0.7,
    )
    if thinking:
        try:
            kwargs["thinking_level"] = "high"
        except Exception:
            pass  # older SDKs without this option simply ignore it
    return types.GenerateContentConfig(**kwargs)


def decode_image(data_url):
    """
    Turn a 'data:image/jpeg;base64,....' string from the browser's camera or
    file picker into a Gemini image Part. Returns None (never raises) if the
    string is missing, malformed, an unsupported type, or too large.
    """
    if not data_url or not isinstance(data_url, str) or not data_url.startswith("data:"):
        return None
    try:
        header, b64data = data_url.split(",", 1)
        mime_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
        if not mime_type.startswith("image/"):
            return None
        raw = base64.b64decode(b64data)
        if len(raw) > MAX_IMAGE_BYTES:
            return None
        return types.Part.from_bytes(data=raw, mime_type=mime_type)
    except Exception as e:
        logger.warning(f"Could not decode image: {e}")
        return None


def sse(payload):
    return f"data: {json.dumps(payload)}\n\n"


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


def generate_content_with_retry(ai_client, prompt, config, validate=None, errors=None):
    """Non-streaming call used by /api/notes. Tries each model in turn."""
    for model_name in [PRIMARY_MODEL] + FALLBACK_MODELS:
        try:
            logger.info(f"Invoking model: {model_name}...")
            response = ai_client.models.generate_content(model=model_name, contents=prompt, config=config)

            if response and response.text:
                text = response.text.strip()
                if validate is None or validate(text):
                    return text
                logger.warning(f"Model {model_name} returned unusable output.")
                if errors is not None:
                    errors.append("empty")
            else:
                logger.warning(f"Model {model_name} returned an empty response.")
                if errors is not None:
                    errors.append("empty")

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {str(e)}")
            if errors is not None:
                errors.append(classify_error(e))
            time.sleep(0.5)

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/jarvis", methods=["POST"])
def jarvis_query():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return Response(sse({"error": "Systems offline. GEMINI_API_KEY is not set."}), mimetype="text/event-stream")

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if rate_limited(client_ip):
        return Response(
            sse({"error": "Jarvis is getting a lot of requests from you right now. Please slow down a little."}),
            mimetype="text/event-stream",
        )

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()[:MAX_PROMPT_CHARS]
    mode = data.get("mode") or DEFAULT_MODE
    thinking = bool(data.get("thinking"))
    history = data.get("history") or []
    client_time = (data.get("client_time") or "").strip()[:100]
    client_tz = (data.get("client_timezone") or "").strip()[:60]
    image_part = decode_image(data.get("image"))

    if not prompt and not image_part:
        return Response(sse({"error": "I didn't quite catch that. Please repeat your query."}), mimetype="text/event-stream")
    if not prompt:
        prompt = "Please look at this photo and describe or explain what's in it."

    transcript = build_transcript(history)
    context_lines = []
    if client_time:
        context_lines.append(f"Current date and time where the user is: {client_time}")
    if client_tz:
        context_lines.append(f"User's time zone: {client_tz}")
    context = ("\n".join(context_lines) + "\n\n") if context_lines else ""

    text_contents = f"{context}Conversation so far:\n{transcript}\n\nYou: {prompt}\nJarvis:" if transcript \
        else f"{context}You: {prompt}\nJarvis:"
    contents = [text_contents, image_part] if image_part else text_contents

    config = build_chat_config(mode, thinking)

    def generate():
        ai_client = genai.Client(api_key=api_key)
        models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS
        started = False
        errors = []

        for model_name in models_to_try:
            if started:
                break
            try:
                logger.info(f"Streaming from model: {model_name}...")
                stream = ai_client.models.generate_content_stream(model=model_name, contents=contents, config=config)
                for chunk in stream:
                    piece = getattr(chunk, "text", None)
                    if piece:
                        started = True
                        yield sse({"chunk": piece})

                if started:
                    yield sse({"done": True})
                    return

            except Exception as e:
                logger.warning(f"Model {model_name} failed: {str(e)}")
                errors.append(classify_error(e))
                if not started:
                    continue  # try the next model
                # A model that fails mid-stream can't be safely restarted from
                # a different model without repeating text, so stop cleanly.
                yield sse({"error": "The connection to Jarvis was interrupted. Please try again."})
                return

        if not started:
            yield sse({"error": failure_message(errors)})

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers=headers)


@app.route("/api/notes", methods=["POST"])
def notes_query():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify(
            {"reply": "Systems offline. GEMINI_API_KEY is not set on the environment variables."}
        ), 503

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()[:MAX_NOTES_INPUT_CHARS]
    topic = (data.get("topic") or "").strip()[:300]

    if not text:
        return jsonify({"reply": "There is nothing to turn into notes yet."}), 400

    prompt = (
        f"Question the student asked: {topic or 'not provided'}\n\n"
        f"Explanation to turn into study notes:\n{text}"
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

        errors = []
        raw = generate_content_with_retry(
            ai_client, prompt, config=config,
            validate=lambda t: parse_notes(t) is not None,
            errors=errors,
        )
        notes = parse_notes(raw)

        if not notes:
            return jsonify({"reply": failure_message(errors)}), 503

        return jsonify({"notes": notes})

    except Exception as e:
        logger.error(f"Error building notes: {e}")
        return jsonify({"reply": "Notes error. Please try again in a moment."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

"""
J.A.R.V.I.S. Backend Bridge
----------------------------------
A secure Flask proxy that sits between the browser-based JARVIS UI / Pi client
and Google's Gemini API. Features automated colorful PDF note generation.
"""

import os
import time
import logging
from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis")

JARVIS_SYSTEM_PROMPT = """
You are Jarvis — a clear, supportive educational AI assistant for students who acts like a wise, soft-spoken tutor explaining concepts gently.

Guidelines:
- Explain concepts using simple, plain, everyday English that anyone can understand easily.
- Avoid complex technical jargon, overly formal terms, or unnecessary fluff.
- Keep answers direct, structured, and easy to follow.
- Maintain a helpful, polite, and encouraging tone at all times.
- Always write your name as "Jarvis" without dots or periods.
"""

# Production Gemini models
PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.5-flash"]

app = Flask(__name__)


def generate_colorful_pdf(title, raw_text, filename="static/notes.pdf"):
    """Generates a styled, colorful PDF document using ReportLab."""
    os.makedirs("static", exist_ok=True)
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=40, leftMargin=40,
        topMargin=40, bottomMargin=40
    )
    styles = getSampleStyleSheet()

    # Custom vibrant header and body styles
    title_style = ParagraphStyle(
        'HeaderTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        textColor=colors.HexColor('#1E3A8A'), # Royal Blue
        spaceAfter=10
    )
    
    body_style = ParagraphStyle(
        'BodyContent',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10.5,
        leading=15,
        textColor=colors.HexColor('#1F2937'), # Charcoal
        spaceAfter=8
    )

    story = [
        Paragraph(title, title_style),
        HRFlowable(width="100%", thickness=2, color=colors.HexColor('#2563EB'), spaceAfter=15)
    ]

    # Convert basic markdown formatting into ReportLab HTML tags
    paragraphs = raw_text.split('\n\n')
    for p in paragraphs:
        if p.strip():
            formatted = p.replace('**', '<b>').replace('**', '</b>')
            story.append(Paragraph(formatted, body_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    return filename


def generate_content_with_retry(ai_client, prompt, custom_system_prompt=None):
    """Tries the primary model first, falling back to secondary models if overloaded."""
    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS

    config = types.GenerateContentConfig(
        system_instruction=custom_system_prompt or JARVIS_SYSTEM_PROMPT,
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

            if response and response.text:
                return response.text.strip()

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {str(e)}")
            time.sleep(0.5)

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)


@app.route("/api/jarvis", methods=["POST"])
def jarvis_query():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify(
            {"reply": "Systems offline. GEMINI_API_KEY environment variable is missing."}
        ), 503

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"reply": "I didn't quite catch that. Please repeat your query."}), 400

    try:
        ai_client = genai.Client(api_key=api_key)

        # Check if user requested PDF notes creation
        pdf_keywords = ['pdf', 'make notes', 'create notes', 'export notes', 'generate notes']
        is_pdf_request = any(kw in prompt.lower() for kw in pdf_keywords)

        if is_pdf_request:
            pdf_prompt = f"Create structured, easy-to-read revision notes on this topic: '{prompt}'. Use clear section headers and bullet points."
            notes_content = generate_content_with_retry(ai_client, pdf_prompt)

            if not notes_content:
                return jsonify({"reply": "Unable to generate notes right now due to server load."}), 503

            pdf_path = generate_colorful_pdf("Jarvis Smart Revision Notes", notes_content)
            reply_text = "I have compiled your revision notes and generated a styled PDF document."

            return jsonify({
                "reply": reply_text,
                "pdf_url": "/" + pdf_path
            })

        else:
            reply_text = generate_content_with_retry(ai_client, prompt)

            if not reply_text:
                return jsonify(
                    {"reply": "Central command servers are currently experiencing high demand. Please try again soon."}
                ), 503

            return jsonify({"reply": reply_text})

    except Exception as e:
        logger.error(f"Error executing request: {e}")
        return jsonify({"reply": f"Central command error: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

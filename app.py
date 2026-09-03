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
MAX_OUTPUT_TOKENS = 8192

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

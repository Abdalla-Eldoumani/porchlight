"""Turns an alert's facts into a short message for a volunteer, in their
language. The rules already decided who to ask and how urgent it is; Gemini
only writes the words. Without a key, or if Gemini fails, a template is used."""
import json

from . import settings

DEFAULT_MODEL = "gemini-3.6-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LANGUAGES = {"en": "English", "ar": "Arabic", "zh": "Simplified Chinese", "fr": "French"}

SYSTEM = (
    "You write a short check-in request to a neighbourhood volunteer in Calgary. "
    "Use only the facts given; never add a medical guess or a cause. "
    "At most two short sentences, plain words, no emoji. "
    "Say what happened and what we are asking them to do. "
    "If the rule is help, end with: if it looks like an emergency, call 911."
)

ASK = {
    "help": "Please call or go over now.",
    "missed_checkin": "Please give them a call or knock on their door today.",
    "no_motion": "Please give them a call or knock on their door.",
    "no_reply_cold": "Please check on them in the next hour.",
    "box_offline": "Please give them a call or knock on their door.",
}


def template(rule, reason, facts):
    weather = ""
    if facts.get("outdoor_c") is not None:
        weather = f" It is {facts['outdoor_c']:.0f} °C outside"
        weather += " and the grid is strained." if facts.get("grid") in ("alert", "emergency") else "."
    text = f"{facts['name']} in {facts['community']}. {reason} ({facts['time']}).{weather} {ASK[rule]}"
    if rule == "help":
        text += " If it looks like an emergency, call 911."
    return text


async def ask(client, key, prompt, system=SYSTEM):
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    model = settings.get("GEMINI_MODEL", DEFAULT_MODEL)
    r = await client.post(GEMINI_URL.format(model=model), json=body,
                          headers={"x-goog-api-key": key}, timeout=8)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


async def write(client, rule, reason, facts, language):
    key = settings.get("GEMINI_API_KEY")
    if not key:
        return template(rule, reason, facts), "template"
    prompt = (f"Write the message in {LANGUAGES.get(language, 'English')}.\n"
              f"Rule that fired: {rule} ({reason}).\nFacts: {json.dumps(facts)}\n"
              f"What we ask: {ASK[rule]}")
    try:
        return await ask(client, key, prompt), "gemini"
    except Exception:
        return template(rule, reason, facts), "template"

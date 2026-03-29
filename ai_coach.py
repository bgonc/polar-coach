"""AI-powered training coach using OpenRouter API — optimized for token efficiency."""

import os
import requests
from datetime import datetime
from openai import OpenAI


# Model registry — switchable from profile
AI_MODELS = {
    "gpt-5.4-nano": {"id": "openai/gpt-5.4-nano", "name": "GPT-5.4 Nano", "tier": "Best value"},
    "gemini-3-flash": {"id": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash", "tier": "Good value"},
    "claude-sonnet": {"id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "tier": "Best quality"},
    "gemini-2.5-flash": {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "tier": "Budget"},
    "grok-4-fast": {"id": "x-ai/grok-4-fast", "name": "Grok 4 Fast", "tier": "Cheap"},
    "deepseek-v3": {"id": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2", "tier": "Cheap"},
}

DEFAULT_MODEL = "gpt-5.4-nano"
PREMIUM_MODEL = "claude-sonnet"  # For 3rd column AI chat, monthly reports, deep analysis


def _get_model_id(task="default"):
    """Get model ID based on task type. Premium tasks use Claude, quick tasks use profile default."""
    from local_data import get_profile
    if task == "premium":
        return AI_MODELS.get(PREMIUM_MODEL, AI_MODELS[DEFAULT_MODEL])["id"]
    p = get_profile()
    key = p.get("ai_model", DEFAULT_MODEL)
    return AI_MODELS.get(key, AI_MODELS[DEFAULT_MODEL])["id"]


def _get_client():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


# ========== Athlete Profile (compact) ==========

def _get_athlete_profile():
    from local_data import get_profile
    p = get_profile()

    age = ""
    if p.get("date_of_birth"):
        try:
            dob = datetime.strptime(p["date_of_birth"], "%Y-%m-%d")
            age = str((datetime.now() - dob).days // 365)
        except ValueError:
            pass

    lines = []
    # One-line identity
    identity = [p.get("name", ""), f"{age}y" if age else "", p.get("gender", ""), f"{p.get('height_cm','')}cm/{p.get('weight_kg','')}kg" if p.get("height_cm") else ""]
    lines.append("Athlete: " + ", ".join(x for x in identity if x))

    if p.get("work_schedule"): lines.append(f"Schedule: {p['work_schedule']}. {p.get('lifestyle', '')}")
    if p.get("sports"): lines.append(f"Sports: {p['sports']}. Equipment: {p.get('equipment', 'bodyweight')}")
    if p.get("training_background"): lines.append(f"Background: {p['training_background']}. Goals: {p.get('goals', 'general fitness')}")

    # Physiology — compact single line
    physio = []
    for key, label in [("vo2max", "VO2max"), ("max_hr", "MaxHR"), ("resting_hr", "RestHR"), ("aerobic_threshold", "AeT"), ("anaerobic_threshold", "AnT"), ("mas_pace", "MAS")]:
        if p.get(key): physio.append(f"{label}:{p[key]}")
    if physio: lines.append("Physio: " + ", ".join(physio))

    # HR zones — one line
    zones = [p.get(f"hr_zone_{i}", "") for i in range(1, 6)]
    if any(zones): lines.append("Zones: " + " | ".join(f"Z{i+1}:{z}" for i, z in enumerate(zones) if z))

    if p.get("injuries"): lines.append(f"Injuries: {p['injuries']}")
    if p.get("notes"): lines.append(f"Notes: {p['notes']}")

    return "\n".join(lines)


# ========== System Prompts (lean) ==========

COACH_RULES = """You are a conservative endurance coach analyzing Polar watch data.

Rules:
- Match workout to ACTUAL training volume, not recovery. Low volume (0-2/week) = easy only.
- Never increase intensity without 3+ weeks of consistent base.
- Recovery = permission to train, not permission to train hard.
- Prioritize injury prevention. Default to easier if uncertain.
- Be precise: use HR zones, paces, sets/reps from athlete data.
- Factor in weather for indoor/outdoor decisions.
- Respect work schedule and family time.
- Keep responses to 3-4 paragraphs. No fluff.
- Week starts Monday (European format)."""


def _system_prompt():
    return f"{COACH_RULES}\n\n{_get_athlete_profile()}"


def _plan_prompt():
    return f"""{COACH_RULES}

Plan rules:
- Start from athlete's CURRENT volume, not potential.
- Increase max 10%/week. Low volume = base building first.
- Running: easy Z1-2 for base, intensity only after 3+ weeks consistent.
- Strength: bodyweight/dumbbell matching equipment.
- 2-3 rest days/week for low volume, 1-2 for established.
- Monday-to-Sunday format. Suggest training times around work.

{_get_athlete_profile()}"""


# ========== Context (optimized — summaries not raw data) ==========

def _build_context(sleep_data, recharge_data, exercises, hr_data, coaching_analysis, training_summary=None, location=""):
    parts = []

    # Weather — 1 line
    weather = _get_weather_for_location(location)
    if weather:
        parts.append(f"Weather: {weather['description']}, {weather['temp_c']}°C (feels {weather['feels_like_c']}°C), wind {weather['wind_kmh']}km/h")

    # Coaching insights — already computed, just pass warnings
    if coaching_analysis:
        items = coaching_analysis.get("warnings", []) + coaching_analysis.get("recommendations", []) + coaching_analysis.get("info", [])
        if items:
            parts.append("Insights: " + " | ".join(items[:5]))

    # Training volume — 2 lines max
    if training_summary:
        tw = training_summary.get("week", {})
        tm = training_summary.get("month", {})
        if tw.get("sessions", 0) > 0 or tm.get("sessions", 0) > 0:
            parts.append(f"Week: {tw['sessions']}sess, {tw['duration_min']}min, {tw['distance_km']:.1f}km")
            parts.append(f"Month: {tm['sessions']}sess, {tm['duration_min']}min, {tm['distance_km']:.1f}km")

    # Sleep — summarize last 3 nights only (not 7 individual lines)
    if sleep_data:
        nights = sleep_data if isinstance(sleep_data, list) else sleep_data.get("nights", [])
        recent = nights[-3:] if len(nights) > 3 else nights
        if recent:
            scores = [n.get("sleep_score", 0) for n in recent if n.get("sleep_score")]
            hours = [(n.get("light_sleep", 0) + n.get("deep_sleep", 0) + n.get("rem_sleep", 0)) / 3600 for n in recent]
            if scores:
                parts.append(f"Sleep(3d): scores {','.join(str(s) for s in scores)}, hours {','.join(f'{h:.1f}' for h in hours)}")

    # Recharge — summarize last 3 nights
    if recharge_data:
        recharges = recharge_data if isinstance(recharge_data, list) else recharge_data.get("recharges", [])
        recent = recharges[-3:] if len(recharges) > 3 else recharges
        if recent:
            ans = [f"{r.get('ans_charge', 0):.1f}" for r in recent]
            hrv = [str(r.get("heart_rate_variability_avg", 0)) for r in recent]
            rhr = [str(r.get("heart_rate_avg", 0)) for r in recent]
            parts.append(f"Recovery(3d): ANS [{','.join(ans)}], HRV [{','.join(hrv)}]ms, RHR [{','.join(rhr)}]bpm")

    # Recent exercises — compact, last 5
    if exercises:
        items = exercises if isinstance(exercises, list) else exercises.get("exercises", [])
        if items:
            ex_lines = []
            for e in items[:5]:
                sport = e.get("sport", e.get("detailed-sport-info", "?"))
                if isinstance(sport, dict): sport = sport.get("name", "?")
                date = str(e.get("date", e.get("start-time", "?")))[:10]
                dur = e.get("duration_min", e.get("duration", "?"))
                ex_lines.append(f"{date}:{sport},{dur}min")
            parts.append(f"Exercises: {' | '.join(ex_lines)}")

    return "\n".join(parts) if parts else "No data."


def _build_full_context(sleep_data, recharge_data, exercises, hr_data, coaching_analysis, training_summary=None, location=""):
    """Full context for deep tasks (plans, weekly reports). More detail than daily advice."""
    parts = []

    weather = _get_weather_for_location(location)
    if weather:
        parts.append(f"Weather: {weather['description']}, {weather['temp_c']}°C (feels {weather['feels_like_c']}°C), range {weather['min_temp_c']}-{weather['max_temp_c']}°C, wind {weather['wind_kmh']}km/h, UV {weather['uv_index']}")

    if coaching_analysis:
        items = coaching_analysis.get("warnings", []) + coaching_analysis.get("recommendations", []) + coaching_analysis.get("info", [])
        if items:
            parts.append("Insights:\n" + "\n".join(f"- {i}" for i in items))

    if training_summary:
        tw = training_summary.get("week", {})
        tm = training_summary.get("month", {})
        parts.append(f"Training - Week: {tw['sessions']}sess, {tw['duration_min']}min, {tw['distance_km']:.1f}km, {tw['calories']}cal")
        parts.append(f"Training - Month: {tm['sessions']}sess, {tm['duration_min']}min, {tm['distance_km']:.1f}km, {tm['calories']}cal")

    if sleep_data:
        nights = sleep_data if isinstance(sleep_data, list) else sleep_data.get("nights", [])
        recent = nights[-7:] if len(nights) > 7 else nights
        if recent:
            parts.append("Sleep (7d):")
            for n in recent:
                h = (n.get("light_sleep", 0) + n.get("deep_sleep", 0) + n.get("rem_sleep", 0)) / 3600
                parts.append(f"  {n.get('date','?')}: {h:.1f}h, score:{n.get('sleep_score','?')}")

    if recharge_data:
        recharges = recharge_data if isinstance(recharge_data, list) else recharge_data.get("recharges", [])
        recent = recharges[-7:] if len(recharges) > 7 else recharges
        if recent:
            parts.append("Recovery (7d):")
            for r in recent:
                parts.append(f"  {r.get('date','?')}: ANS:{r.get('ans_charge','?')}, HRV:{r.get('heart_rate_variability_avg','?')}ms, RHR:{r.get('heart_rate_avg','?')}bpm")

    if exercises:
        items = exercises if isinstance(exercises, list) else exercises.get("exercises", [])
        if items:
            parts.append("Exercises:")
            for e in items[:10]:
                sport = e.get("sport", e.get("detailed-sport-info", "?"))
                if isinstance(sport, dict): sport = sport.get("name", "?")
                date = str(e.get("date", e.get("start-time", "?")))[:10]
                dur = e.get("duration_min", e.get("duration", "?"))
                dist = e.get("distance_km", "")
                line = f"  {date}: {sport}, {dur}min"
                if dist: line += f", {dist}km"
                parts.append(line)

    return "\n".join(parts) if parts else "No data."


# ========== API Functions ==========

def get_session_insight(exercise_data):
    """Quick AI insight for a specific exercise session. Uses cheap model."""
    client = _get_client()
    if not client: return None

    profile = _get_athlete_profile()
    ex = exercise_data
    prompt = f"""{profile}

Session: {ex.get('sport','?')}, {ex.get('duration','?')}, {ex.get('date','?')}
Distance: {ex.get('distance_km','')}km, Calories: {ex.get('calories','')}, Avg HR: {ex.get('avg_hr','')}bpm
Benefit: {ex.get('training_benefit','')}

Give a 2-3 sentence analysis of this session: was it effective? What did it train? Suggestion for next similar session."""

    response = client.chat.completions.create(
        model=_get_model_id("default"),
        messages=[
            {"role": "system", "content": "You are a concise running/fitness coach. Analyze the session in 2-3 sentences."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def get_ai_advice(sleep_data, recharge_data, exercises, hr_data, coaching_analysis, prompt=None, training_summary=None, location=""):
    """AI chat in the 3rd column — uses premium model."""
    client = _get_client()
    if not client: return None

    context = _build_context(sleep_data, recharge_data, exercises, hr_data, coaching_analysis, training_summary, location)
    user_prompt = prompt or "What should I do today? Give me a specific workout or rest recommendation."

    response = client.chat.completions.create(
        model=_get_model_id("premium"),
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": f"{datetime.now().strftime('%A %d.%m.%Y')}\n{context}\n\n{user_prompt}"},
        ],
    )
    return response.choices[0].message.content


def generate_training_plan(sleep_data, recharge_data, exercises, coaching_analysis, goal=None, training_summary=None, location=""):
    client = _get_client()
    if not client: return None

    context = _build_context(sleep_data, recharge_data, exercises, None, coaching_analysis, training_summary, location)
    goal_text = goal or "running endurance and home gym strength"

    response = client.chat.completions.create(
        model=_get_model_id(),
        messages=[
            {"role": "system", "content": _plan_prompt()},
            {"role": "user", "content": f"{datetime.now().strftime('%A %d.%m.%Y')}\n{context}\n\nWeekly plan for: {goal_text}"},
        ],
    )
    return response.choices[0].message.content


def create_training_plan(sleep_data, recharge_data, exercises, coaching, training_sum, events, plan_type, race_date, race_distance, notes, location=""):
    client = _get_client()
    if not client: return None

    context = _build_full_context(sleep_data, recharge_data, exercises, None, coaching, training_sum, location)

    event_text = ""
    if events:
        event_text = "Orienteering events: " + ", ".join(f"{e['date']}:{e['type']}@{e['location']}" for e in events[:8])

    if plan_type == "race":
        goal = f"{race_distance} race on {race_date}. Periodized plan with taper."
    elif plan_type == "orienteering":
        goal = "Orienteering fitness. Include Iltarastit events."
    elif plan_type == "running":
        goal = "Running endurance and speed improvement."
    else:
        goal = "General fitness — running + home gym."

    if notes: goal += f" {notes}"

    response = client.chat.completions.create(
        model=_get_model_id(),
        messages=[
            {"role": "system", "content": _plan_prompt()},
            {"role": "user", "content": f"{datetime.now().strftime('%A %d.%m.%Y')}\n{context}\n{event_text}\n\nCreate plan: {goal}\nFormat: Overview, then Mon-Sun weekly schedule with specific workouts."},
        ],
    )
    plan_text = response.choices[0].message.content
    schedule = _extract_schedule(client, plan_text)
    return plan_text, schedule


def _extract_schedule(client, plan_text):
    try:
        response = client.chat.completions.create(
            model=_get_model_id(),
            messages=[
                {"role": "system", "content": "Extract training schedule as JSON array. Each: {date:YYYY-MM-DD, type:run/strength/rest/orienteering, title:2-4 words, duration:e.g.45min}. JSON only."},
                {"role": "user", "content": plan_text},
            ],
        )
        import json
        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        return json.loads(text.strip())
    except Exception:
        return []


def adjust_daily_plan(sleep_data, recharge_data, exercises, coaching, training_sum, active_plan, reason, location=""):
    client = _get_client()
    if not client: return None

    context = _build_context(sleep_data, recharge_data, exercises, None, coaching, training_sum, location)

    plan_ref = ""
    if active_plan:
        plan_ref = f"Active plan ({active_plan.get('type','general')}, created {active_plan.get('created','?')[:10]})"

    prompt = f"""{datetime.now().strftime('%A %d.%m.%Y')}
{context}
{plan_ref}

Should I follow today's plan, modify it, or skip? Give adjusted workout."""
    if reason: prompt += f"\nReason: {reason}"

    response = client.chat.completions.create(
        model=_get_model_id(),
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def generate_weekly_report(sleep_data, recharge_data, exercises, coaching, training_sum, location=""):
    """Weekly report — uses cheap default model."""
    client = _get_client()
    if not client: return None

    context = _build_context(sleep_data, recharge_data, exercises, None, coaching, training_sum, location)

    response = client.chat.completions.create(
        model=_get_model_id("default"),
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": f"{datetime.now().strftime('%A %d.%m.%Y')}\n{context}\n\nWeekly report: training done, recovery trends, what went well, what to improve. 3-4 paragraphs."},
        ],
    )
    return response.choices[0].message.content


def generate_monthly_report(sleep_data, recharge_data, exercises, coaching, training_sum, location=""):
    """Monthly report — uses premium model for deep analysis."""
    client = _get_client()
    if not client: return None

    context = _build_full_context(sleep_data, recharge_data, exercises, None, coaching, training_sum, location)

    response = client.chat.completions.create(
        model=_get_model_id("premium"),
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": f"{datetime.now().strftime('%A %d.%m.%Y')}\n{context}\n\nMonthly report: training volume trends, fitness progression, recovery patterns, sleep quality trends, key achievements, areas to improve, recommendations for next month. Be thorough and analytical."},
        ],
    )
    return response.choices[0].message.content


# ========== Weather ==========

def _get_weather():
    return _get_weather_for_location("")


def _get_weather_for_location(location=""):
    try:
        query = location.strip() if location else ""
        url = f"https://wttr.in/{query}?format=j1" if query else "https://wttr.in/?format=j1"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200: return None
        data = resp.json()
        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        api_city = area.get("areaName", [{}])[0].get("value", "Unknown")
        country = area.get("country", [{}])[0].get("value", "")
        forecast = data.get("weather", [{}])[0]

        is_postal = query and sum(c.isdigit() for c in query) > len(query) / 2
        city = api_city if (not query or is_postal) else query.split(",")[0].strip().title()

        code = int(current.get("weatherCode", 0))
        return {
            "location": f"{city}, {country}", "city": city,
            "temp_c": current.get("temp_C", "?"), "feels_like_c": current.get("FeelsLikeC", "?"),
            "humidity": current.get("humidity", "?"),
            "description": current.get("weatherDesc", [{}])[0].get("value", "?"),
            "wind_kmh": current.get("windspeedKmph", "?"),
            "max_temp_c": forecast.get("maxtempC", "?"), "min_temp_c": forecast.get("mintempC", "?"),
            "uv_index": current.get("uvIndex", "?"), "emoji": _weather_emoji(code),
        }
    except Exception:
        return None


def _weather_emoji(code):
    if code == 113: return "sun"
    if code == 116: return "cloud-sun"
    if code in (119, 122): return "cloud"
    if code in (143, 248, 260): return "smog"
    if code in (176, 263, 266, 293, 296, 299, 302, 305, 308, 311, 314, 353, 356, 359): return "cloud-rain"
    if code in (179, 182, 185, 227, 230, 323, 326, 329, 332, 335, 338, 362, 365, 368, 371, 374, 377): return "snowflake"
    if code in (200, 386, 389, 392, 395): return "bolt"
    return "cloud"

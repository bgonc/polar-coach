"""AI-powered training coach using OpenRouter API with weather and athlete context."""

import os
import requests
from datetime import datetime
from openai import OpenAI


def _get_athlete_profile():
    """Load athlete profile and format for AI context."""
    from local_data import get_profile
    p = get_profile()

    # Calculate age from DOB
    age = ""
    if p.get("date_of_birth"):
        try:
            dob = datetime.strptime(p["date_of_birth"], "%Y-%m-%d")
            age = str((datetime.now() - dob).days // 365)
        except ValueError:
            pass

    sections = []

    # Identity
    identity = []
    if p.get("name"): identity.append(f"Name: {p['name']}")
    if age: identity.append(f"Age: {age}")
    if p.get("gender"): identity.append(f"Gender: {p['gender']}")
    if p.get("height_cm"): identity.append(f"Height: {p['height_cm']}cm")
    if p.get("weight_kg"): identity.append(f"Weight: {p['weight_kg']}kg")
    if p.get("bmi"): identity.append(f"BMI: {p['bmi']}")
    if p.get("location"): identity.append(f"Location: {p['location']}")
    if identity:
        sections.append("Personal: " + ", ".join(identity))

    # Lifestyle
    lifestyle = []
    if p.get("work_schedule"): lifestyle.append(f"Work: {p['work_schedule']}")
    if p.get("lifestyle"): lifestyle.append(p["lifestyle"])
    if p.get("activity_level"): lifestyle.append(f"Activity level: {p['activity_level']}")
    if p.get("sleep_goal"): lifestyle.append(f"Sleep goal: {p['sleep_goal']}")
    if lifestyle:
        sections.append("Lifestyle: " + ". ".join(lifestyle))

    # Training
    training = []
    if p.get("sports"): training.append(f"Sports: {p['sports']}")
    if p.get("training_background"): training.append(f"Background: {p['training_background']}")
    if p.get("equipment"): training.append(f"Equipment: {p['equipment']}")
    if p.get("goals"): training.append(f"Goals: {p['goals']}")
    if training:
        sections.append("Training: " + ". ".join(training))

    # Physiology — critical for prescribing intensity
    physio = []
    if p.get("vo2max"): physio.append(f"VO2max: {p['vo2max']}")
    if p.get("max_hr"): physio.append(f"Max HR: {p['max_hr']}bpm")
    if p.get("resting_hr"): physio.append(f"Resting HR: {p['resting_hr']}bpm")
    if p.get("aerobic_threshold"): physio.append(f"Aerobic threshold: {p['aerobic_threshold']}bpm")
    if p.get("anaerobic_threshold"): physio.append(f"Anaerobic threshold: {p['anaerobic_threshold']}bpm")
    if p.get("mas_pace"): physio.append(f"MAS: {p['mas_pace']}")
    if p.get("map_watts"): physio.append(f"MAP: {p['map_watts']}W")
    if p.get("ftp_watts"): physio.append(f"FTP: {p['ftp_watts']}W")
    if physio:
        sections.append("Physiology: " + ", ".join(physio))

    # HR Zones — so AI can prescribe exact zones
    zones = []
    for i in range(1, 6):
        z = p.get(f"hr_zone_{i}", "")
        if z: zones.append(f"Z{i}: {z}")
    if zones:
        sections.append("HR Zones: " + " | ".join(zones))

    # Injuries & notes
    if p.get("injuries"):
        sections.append(f"Injuries/limitations: {p['injuries']}")
    if p.get("notes"):
        sections.append(f"Coach notes: {p['notes']}")

    sections.append("Tracking: Polar Vantage V3 (continuous HR, sleep, nightly recharge, ANS charge)")

    return "Athlete profile:\n" + "\n".join(f"- {s}" for s in sections)


def _system_prompt():
    profile = _get_athlete_profile()
    return f"""You are an elite sports performance coach analyzing data from a Polar watch.
You give concise, actionable daily training advice based on recovery metrics, sleep quality, heart rate variability, training history, and current weather conditions.

{profile}

Critical rules:
- ALWAYS check the Training Volume section first. If weekly volume is low (0-2 sessions, under 2h), the athlete is in a base-building or returning phase — prescribe EASY, SHORT sessions only. No intervals, no tempo, no 8-10km runs.
- Good recovery numbers (high readiness, good sleep) do NOT mean the athlete is fit enough for hard sessions. Recovery = permission to train, not permission to train hard. Fitness comes from consistent training history.
- Match workout difficulty to ACTUAL recent training volume, not recovery status. Someone doing 30min once a week should not be told to do VO2max intervals.
- For low-volume athletes: easy runs of 20-30min, walks, bodyweight circuits. Build volume 10% per week max.
- Only suggest tempo/interval/long runs when weekly volume has been consistently 3+ sessions for 3+ weeks.

Your style:
- Supportive and realistic, like a coach who knows the athlete's actual level
- Lead with the recommendation (train / easy / rest)
- Back it up with specific numbers from the data
- Factor in weather: suggest indoor workouts on bad weather days, outdoor runs on good days
- Consider the athlete's work schedule and family life when suggesting training times
- If suggesting a workout, give practical structure appropriate to their level
- Keep it to 3-5 paragraphs max
- Be honest about fitness level — don't overhype readiness when training volume is low"""


def _plan_prompt():
    profile = _get_athlete_profile()
    return f"""You are an elite sports performance coach creating personalized weekly training plans.

{profile}

Critical rules:
- ALWAYS check Training Volume first. Start the plan from WHERE THE ATHLETE ACTUALLY IS, not where they want to be.
- If current volume is low (0-2 sessions/week, under 2h), the first 2-4 weeks must be base building: short easy runs (20-30min), basic bodyweight, lots of rest days.
- Increase volume max 10% per week. No jumps from 1h/week to 5h/week.
- Only introduce intervals/tempo after 3+ weeks of consistent 3+ sessions/week.
- For race goals: be realistic about timeline. If athlete runs 30min/week, they need 12+ weeks to prepare for a 10km.

Your plans must:
- Start from the athlete's CURRENT fitness level, not their potential
- Work around work schedule and family commitments
- Factor in weather for outdoor vs indoor decisions
- Follow progressive overload: build volume first, then intensity
- Running: mostly easy runs in Zone 1-2 for base building, minimal intensity work early on
- Strength: bodyweight and dumbbell work matching available equipment
- Include 2-3 rest days per week for low-volume athletes, 1-2 for established athletes
- Suggest realistic training times (early morning, lunch break, or after work)
- IMPORTANT: Week starts on MONDAY and ends on SUNDAY (European format)
- Format as a clean Monday-to-Sunday schedule with session details
- Add a weekly focus note and total volume target"""


def _get_client():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def _get_weather():
    """Fetch weather for stored location or auto-detect."""
    return _get_weather_for_location("")


def _get_weather_for_location(location=""):
    """Fetch current weather using wttr.in. If location is empty, auto-detects via IP."""
    try:
        query = location.strip() if location else ""
        url = f"https://wttr.in/{query}?format=j1" if query else "https://wttr.in/?format=j1"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        api_city = area.get("areaName", [{}])[0].get("value", "Unknown")
        country = area.get("country", [{}])[0].get("value", "")

        # If user entered a postal code (mostly digits), use the API-resolved city name
        # Otherwise use what the user typed as the display name
        is_postal = query and sum(c.isdigit() for c in query) > len(query) / 2
        if not query:
            city = api_city
        elif is_postal:
            city = api_city
        else:
            city = query.split(",")[0].strip().title()

        forecast = data.get("weather", [{}])[0]

        # Map weather codes to emoji
        code = int(current.get("weatherCode", 0))
        emoji = _weather_emoji(code)

        return {
            "location": f"{city}, {country}",
            "city": city,
            "temp_c": current.get("temp_C", "?"),
            "feels_like_c": current.get("FeelsLikeC", "?"),
            "humidity": current.get("humidity", "?"),
            "description": current.get("weatherDesc", [{}])[0].get("value", "?"),
            "wind_kmh": current.get("windspeedKmph", "?"),
            "max_temp_c": forecast.get("maxtempC", "?"),
            "min_temp_c": forecast.get("mintempC", "?"),
            "uv_index": current.get("uvIndex", "?"),
            "emoji": emoji,
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


def get_ai_advice(sleep_data, recharge_data, exercises, hr_data, coaching_analysis, prompt=None, training_summary=None, location=""):
    """Get AI coaching advice based on Polar data + weather."""
    client = _get_client()
    if not client:
        return None

    context = _build_context(sleep_data, recharge_data, exercises, hr_data, coaching_analysis, training_summary, location)
    user_prompt = prompt or "Based on all my data and today's weather, give me today's training recommendation. Should I train hard, go moderate, easy, or rest? Give me a specific workout."

    response = client.chat.completions.create(
        model="google/gemini-2.0-flash-001",
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": f"Today is {datetime.now().strftime('%A, %B %d, %Y')}.\n\n{context}\n\n{user_prompt}"},
        ],
    )
    return response.choices[0].message.content


def generate_training_plan(sleep_data, recharge_data, exercises, coaching_analysis, goal=None, training_summary=None, location=""):
    """Generate a weekly training plan."""
    client = _get_client()
    if not client:
        return None

    context = _build_context(sleep_data, recharge_data, exercises, None, coaching_analysis, training_summary, location)
    goal_text = goal or "running endurance and home gym strength"

    response = client.chat.completions.create(
        model="google/gemini-2.0-flash-001",
        messages=[
            {"role": "system", "content": _plan_prompt()},
            {"role": "user", "content": f"Today is {datetime.now().strftime('%A, %B %d, %Y')}.\n\n{context}\n\nCreate a weekly training plan starting today. Goal: {goal_text}."},
        ],
    )
    return response.choices[0].message.content


def create_training_plan(sleep_data, recharge_data, exercises, coaching, training_sum, events, plan_type, race_date, race_distance, notes, location=""):
    """Create a structured, multi-week training plan."""
    client = _get_client()
    if not client:
        return None

    context = _build_context(sleep_data, recharge_data, exercises, None, coaching, training_sum, location)
    profile = _get_athlete_profile()

    # Build event context
    event_text = ""
    if events:
        event_text = "\n## Upcoming Orienteering Events (Helsingin Suunnistajat Iltarastit)\n"
        for e in events[:10]:
            event_text += f"- {e['date']}: {e['type']} at {e['location']} ({e['address']})\n"

    # Build plan request
    if plan_type == "race":
        goal = f"Prepare for a {race_distance} race on {race_date}. Build a periodized plan from today to race day with taper."
    elif plan_type == "orienteering":
        goal = "Improve orienteering fitness. Include the upcoming Iltarastit events in the schedule."
    elif plan_type == "running":
        goal = "Improve running endurance and speed. No specific race target, just progressive improvement."
    else:
        goal = "General fitness — mix of running and home gym strength training."

    if notes:
        goal += f" Additional notes: {notes}"

    prompt = f"""Today is {datetime.now().strftime('%A, %B %d, %Y')}.

{profile}

{context}

{event_text}

Create a detailed training plan.
Goal: {goal}

Format the plan as:
1. **Plan Overview** (goal, duration, weekly structure philosophy)
2. **Week-by-week schedule** (Monday to Sunday, week starts on MONDAY) with specific daily workouts:
   - For running: type, duration, pace/HR zone, distance target
   - For strength: exercises, sets x reps, rest
   - For orienteering events: mark them and plan around them
   - Include rest days
   - Suggest best training time based on work schedule
3. **Key principles** (when to adjust, warning signs to back off)

Be specific with HR zones, paces, and progressions based on the athlete's physiology data."""

    response = client.chat.completions.create(
        model="google/gemini-2.0-flash-001",
        messages=[
            {"role": "system", "content": _plan_prompt()},
            {"role": "user", "content": prompt},
        ],
    )
    plan_text = response.choices[0].message.content

    # Extract structured schedule for calendar display
    schedule = _extract_schedule(client, plan_text)

    return plan_text, schedule


def _extract_schedule(client, plan_text):
    """Ask AI to extract a JSON schedule from the plan text."""
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.0-flash-001",
            messages=[
                {"role": "system", "content": "Extract the training schedule from the plan into a JSON array. Each item must have: date (YYYY-MM-DD), type (run/strength/rest/orienteering), title (short 2-4 word summary), duration (e.g. '45min'). Output ONLY valid JSON, no markdown, no explanation."},
                {"role": "user", "content": plan_text},
            ],
        )
        import json
        text = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        return json.loads(text.strip())
    except Exception:
        return []


def adjust_daily_plan(sleep_data, recharge_data, exercises, coaching, training_sum, active_plan, reason, location=""):
    """Adjust today's workout based on current recovery and any user input."""
    client = _get_client()
    if not client:
        return None

    context = _build_context(sleep_data, recharge_data, exercises, None, coaching, training_sum, location)
    profile = _get_athlete_profile()

    plan_text = ""
    if active_plan:
        plan_text = f"\n## Active Training Plan\nType: {active_plan.get('type', 'general')}\nCreated: {active_plan.get('created', '?')}\n\n{active_plan.get('plan_text', 'No plan details.')}"

    prompt = f"""Today is {datetime.now().strftime('%A, %B %d, %Y')}.

{profile}

{context}

{plan_text}

Based on today's recovery data (sleep, HRV, ANS charge, stress) and the active training plan, tell me:
1. What was planned for today?
2. Should I follow the plan as-is, modify it, or skip it entirely?
3. Give me the adjusted workout with specific details.
"""
    if reason:
        prompt += f"\nAdditional context from the athlete: {reason}"

    prompt += "\nBe concise — 2-3 paragraphs max. Lead with the decision."

    response = client.chat.completions.create(
        model="google/gemini-2.0-flash-001",
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def generate_weekly_report(sleep_data, recharge_data, exercises, coaching, training_sum, location=""):
    """Ask the AI to summarize the past week of training and recovery."""
    client = _get_client()
    if not client:
        return None

    context = _build_context(sleep_data, recharge_data, exercises, None, coaching, training_sum, location)
    profile = _get_athlete_profile()

    prompt = f"""Today is {datetime.now().strftime('%A, %B %d, %Y')}.

{profile}

{context}

Write a concise weekly training report for the past 7 days. Include:
1. **Training Summary** — sessions completed, total volume, sport breakdown
2. **Recovery & Sleep** — average sleep score, HRV trend, ANS charge pattern, stress levels
3. **Key Observations** — what went well, what needs attention
4. **Recommendations for Next Week** — adjust volume, focus areas, recovery priorities

Keep it to 4-6 paragraphs. Use specific numbers from the data. Be honest and constructive."""

    response = client.chat.completions.create(
        model="google/gemini-2.0-flash-001",
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def _build_context(sleep_data, recharge_data, exercises, hr_data, coaching_analysis, training_summary=None, location=""):
    """Build comprehensive context for the AI."""
    parts = []

    # Weather
    weather = _get_weather_for_location(location)
    if weather:
        parts.append(f"## Current Weather ({weather['location']})")
        parts.append(f"- Conditions: {weather['description']}")
        parts.append(f"- Temperature: {weather['temp_c']}°C (feels like {weather['feels_like_c']}°C)")
        parts.append(f"- Today's range: {weather['min_temp_c']}°C to {weather['max_temp_c']}°C")
        parts.append(f"- Humidity: {weather['humidity']}%, Wind: {weather['wind_kmh']} km/h, UV: {weather['uv_index']}")

    # Coaching insights
    if coaching_analysis:
        warnings = coaching_analysis.get("warnings", [])
        recs = coaching_analysis.get("recommendations", [])
        info = coaching_analysis.get("info", [])
        if warnings or recs or info:
            parts.append("\n## Today's Insights")
            for w in warnings:
                parts.append(f"- ⚠ {w}")
            for r in recs:
                parts.append(f"- ✓ {r}")
            for i in info:
                parts.append(f"- ℹ {i}")

    # Training summary
    if training_summary:
        tw = training_summary.get("week", {})
        tm = training_summary.get("month", {})
        if tw.get("sessions", 0) > 0 or tm.get("sessions", 0) > 0:
            parts.append("\n## Training Volume")
            parts.append(f"- This week: {tw['sessions']} sessions, {tw['duration_min']}min, {tw['distance_km']:.1f}km, {tw['calories']} cal")
            parts.append(f"- This month: {tm['sessions']} sessions, {tm['duration_min']}min, {tm['distance_km']:.1f}km, {tm['calories']} cal")
            if tw.get("sports"):
                parts.append(f"- Sports breakdown (week): {', '.join(f'{k}: {v}' for k, v in tw['sports'].items())}")

    # Sleep (last 7 nights)
    if sleep_data:
        nights = sleep_data if isinstance(sleep_data, list) else sleep_data.get("nights", [])
        recent = nights[-7:] if len(nights) > 7 else nights
        if recent:
            parts.append("\n## Sleep (last 7 nights)")
            for n in recent:
                light = n.get("light_sleep", 0) / 60
                deep = n.get("deep_sleep", 0) / 60
                rem = n.get("rem_sleep", 0) / 60
                total = (light + deep + rem) / 60
                score = n.get("sleep_score", "N/A")
                parts.append(
                    f"- {n.get('date', '?')}: {total:.1f}h "
                    f"(score: {score}, deep: {deep:.0f}m, REM: {rem:.0f}m)"
                )

    # Nightly recharge (last 7)
    if recharge_data:
        recharges = recharge_data if isinstance(recharge_data, list) else recharge_data.get("recharges", [])
        recent = recharges[-7:] if len(recharges) > 7 else recharges
        if recent:
            parts.append("\n## Nightly Recharge (last 7 nights)")
            for r in recent:
                parts.append(
                    f"- {r.get('date', '?')}: ANS charge {r.get('ans_charge', 'N/A')}, "
                    f"HRV {r.get('heart_rate_variability_avg', 'N/A')}ms, "
                    f"resting HR {r.get('heart_rate_avg', 'N/A')}bpm, "
                    f"breathing {r.get('breathing_rate_avg', 'N/A')}/min"
                )

    # Recent exercises
    if exercises:
        items = exercises if isinstance(exercises, list) else exercises.get("exercises", [])
        if items:
            parts.append("\n## Recent Exercises")
            for e in items[:10]:
                sport = e.get("detailed-sport-info", e.get("sport", "Unknown"))
                if isinstance(sport, dict):
                    sport = sport.get("name", "Unknown")
                date = e.get("start-time", e.get("date", "?"))
                if isinstance(date, str) and len(date) > 10:
                    date = date[:10]
                dur = e.get("duration", e.get("duration_min", "?"))
                dist = e.get("distance_km", "")
                cal = e.get("calories", "")
                line = f"- {date}: {sport}, duration: {dur}"
                if dist:
                    line += f", {dist}km"
                if cal:
                    line += f", {cal} cal"
                parts.append(line)

    return "\n".join(parts) if parts else "No data available."

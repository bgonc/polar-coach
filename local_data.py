"""Local JSON storage for manual exercises, training plans, and user profile."""

import json
import os
from datetime import datetime, timedelta


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
EXERCISES_FILE = os.path.join(DATA_DIR, "exercises.json")
PROFILE_FILE = os.path.join(DATA_DIR, "profile.json")
PLAN_FILE = os.path.join(DATA_DIR, "training_plan.json")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal.json")

DEFAULT_PROFILE = {
    "name": "Bruno Goncalves",
    "date_of_birth": "1978-03-16",
    "gender": "Male",
    "height_cm": "177",
    "weight_kg": "73.6",
    "location": "Vantaa, Finland",
    "work_schedule": "8:00-16:00 or 9:00-18:00",
    "lifestyle": "Family, dog, work full-time, online university student (UAb)",
    "sports": "Orienteering, Running, Strength training",
    "equipment": "Dumbbells, pull-up bar, resistance bands (no commercial gym)",
    "goals": "General fitness, running endurance, strength",
    "training_background": "Regular (1-3h/week)",
    "vo2max": "40",
    "max_hr": "176",
    "resting_hr": "50",
    "aerobic_threshold": "132",
    "anaerobic_threshold": "158",
    "mas_pace": "05:14 min/km",
    "map_watts": "305",
    "ftp_watts": "176",
    "bmi": "23",
    "sleep_goal": "8h",
    "activity_level": "Level 2 (moderately active)",
    "hr_zone_1": "99-115 bpm (50-65%)",
    "hr_zone_2": "115-132 bpm (65-75%)",
    "hr_zone_3": "132-149 bpm (75-85%)",
    "hr_zone_4": "149-167 bpm (85-95%)",
    "hr_zone_5": "167-176 bpm (95-100%)",
    "injuries": "",
    "notes": "",
}


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ========== Profile ==========

def get_profile():
    if not os.path.exists(PROFILE_FILE):
        save_profile(DEFAULT_PROFILE)
        return DEFAULT_PROFILE.copy()
    with open(PROFILE_FILE) as f:
        stored = json.load(f)
    # Merge with defaults for any new fields
    merged = DEFAULT_PROFILE.copy()
    merged.update(stored)
    return merged


def save_profile(data):
    _ensure_dir()
    with open(PROFILE_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ========== Exercises ==========

def _load():
    if not os.path.exists(EXERCISES_FILE):
        return []
    with open(EXERCISES_FILE) as f:
        return json.load(f)


def _save(data):
    _ensure_dir()
    with open(EXERCISES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_exercise(date, sport, duration_min, calories=0, avg_hr=0, distance_km=0, notes=""):
    exercises = _load()
    exercise = {
        "id": f"local-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "date": date,
        "sport": sport,
        "duration_min": duration_min,
        "calories": calories,
        "avg_hr": avg_hr,
        "distance_km": distance_km,
        "notes": notes,
        "source": "manual",
        "created": datetime.now().isoformat(),
    }
    exercises.append(exercise)
    _save(exercises)
    return exercise


def get_exercises():
    return _load()


def delete_exercise(exercise_id):
    exercises = _load()
    exercises = [e for e in exercises if e["id"] != exercise_id]
    _save(exercises)


def get_training_summary(exercises):
    """Compute weekly and monthly training summaries."""
    now = datetime.now().date()
    week_cutoff = now - timedelta(days=7)
    month_cutoff = now - timedelta(days=30)

    week = {"sessions": 0, "duration_min": 0, "distance_km": 0, "calories": 0, "sports": {}}
    month = {"sessions": 0, "duration_min": 0, "distance_km": 0, "calories": 0, "sports": {}}

    for e in exercises:
        try:
            d = datetime.strptime(e.get("date", "")[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        dur = e.get("duration_min", 0) or 0
        dist = e.get("distance_km", 0) or 0
        cal = e.get("calories", 0) or 0
        sport = e.get("sport", "Other")

        if d >= month_cutoff:
            month["sessions"] += 1
            month["duration_min"] += dur
            month["distance_km"] += dist
            month["calories"] += cal
            month["sports"][sport] = month["sports"].get(sport, 0) + 1

        if d >= week_cutoff:
            week["sessions"] += 1
            week["duration_min"] += dur
            week["distance_km"] += dist
            week["calories"] += cal
            week["sports"][sport] = week["sports"].get(sport, 0) + 1

    return {"week": week, "month": month}


# ========== Training Plans ==========

def get_active_plan():
    if not os.path.exists(PLAN_FILE):
        return None
    with open(PLAN_FILE) as f:
        return json.load(f)


def save_plan(plan):
    _ensure_dir()
    with open(PLAN_FILE, "w") as f:
        json.dump(plan, f, indent=2)


def delete_plan():
    if os.path.exists(PLAN_FILE):
        os.remove(PLAN_FILE)


# ========== Journal ==========

def _load_journals():
    if not os.path.exists(JOURNAL_FILE):
        return []
    with open(JOURNAL_FILE) as f:
        return json.load(f)


def _save_journals(data):
    _ensure_dir()
    with open(JOURNAL_FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_journal(date, mood, fatigue, nutrition, notes=""):
    """Add a journal entry. mood/fatigue are 1-5, nutrition is good/ok/poor."""
    journals = _load_journals()
    entry = {
        "date": date,
        "mood": max(1, min(5, int(mood))),
        "fatigue": max(1, min(5, int(fatigue))),
        "nutrition": nutrition if nutrition in ("good", "ok", "poor") else "ok",
        "notes": notes,
        "created": datetime.now().isoformat(),
    }
    # Replace existing entry for the same date
    journals = [j for j in journals if j["date"] != date]
    journals.append(entry)
    journals.sort(key=lambda j: j["date"], reverse=True)
    _save_journals(journals)
    return entry


def get_journals():
    return _load_journals()


def get_journal(date):
    for j in _load_journals():
        if j["date"] == date:
            return j
    return None


# ========== Weekly Volumes ==========

def get_weekly_volumes(exercises, weeks=8):
    """Return a list of {week_start, sessions, duration_min, distance_km} for the last N weeks."""
    now = datetime.now().date()
    # Find the Monday of the current week
    current_monday = now - timedelta(days=now.weekday())

    result = []
    for i in range(weeks):
        week_start = current_monday - timedelta(weeks=i)
        week_end = week_start + timedelta(days=7)
        sessions = 0
        duration_min = 0
        distance_km = 0.0

        for e in exercises:
            try:
                d = datetime.strptime(e.get("date", "")[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if week_start <= d < week_end:
                sessions += 1
                duration_min += e.get("duration_min", 0) or 0
                distance_km += e.get("distance_km", 0) or 0

        result.append({
            "week_start": week_start.isoformat(),
            "sessions": sessions,
            "duration_min": duration_min,
            "distance_km": round(distance_km, 1),
        })

    result.reverse()  # oldest first
    return result


# ========== Orienteering Events ==========

def get_orienteering_events():
    """Fetch upcoming events from iltarastit.fi."""
    import requests
    from bs4 import BeautifulSoup

    try:
        resp = requests.get("https://iltarastit.fi/tulokset/", timeout=8)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        events = []
        today = datetime.now().date()

        for row in table.find_all("tr")[1:]:  # skip header
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            date_str = cells[0].get_text(strip=True)
            event_type = cells[2].get_text(strip=True)
            location = cells[3].get_text(strip=True)
            address = cells[4].get_text(strip=True)

            # Parse Finnish date (d.m.yyyy)
            try:
                parts = date_str.split(".")
                d = datetime(int(parts[2]), int(parts[1]), int(parts[0])).date()
            except (ValueError, IndexError):
                continue

            if d >= today:
                events.append({
                    "date": d.isoformat(),
                    "date_display": date_str,
                    "type": event_type,
                    "location": location,
                    "address": address,
                })

        return events[:15]  # Next 15 events

    except Exception:
        return []

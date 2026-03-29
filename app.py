"""Polar AI Training Coach — Flask app."""

import json
import os
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for, jsonify

from coach import analyze_training, compute_daily_scores, compute_summaries, classify_session
from ai_coach import get_ai_advice, generate_training_plan
from polar_client import PolarClient
from local_data import (
    add_exercise as local_add_exercise, get_exercises as local_get_exercises,
    delete_exercise as local_delete_exercise, get_training_summary,
    get_profile, save_profile,
    get_active_plan, save_plan, delete_plan, get_orienteering_events,
    add_journal, get_journals, get_journal, get_weekly_volumes,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

# Use filesystem sessions instead of cookies to avoid 4KB cookie limit
from cachelib import FileSystemCache
from flask.sessions import SessionInterface, SessionMixin
import uuid

SESSION_DIR = os.path.join(os.path.dirname(__file__), "data", "sessions")
os.makedirs(SESSION_DIR, exist_ok=True)
_session_cache = FileSystemCache(SESSION_DIR, threshold=50, default_timeout=86400)


class ServerSession(dict, SessionMixin):
    def __init__(self, sid, data=None):
        self.sid = sid
        self.modified = False
        if data:
            self.update(data)


class ServerSessionInterface(SessionInterface):
    def open_session(self, app, request):
        sid = request.cookies.get('session_id')
        if sid:
            data = _session_cache.get(sid)
            if data is not None:
                return ServerSession(sid, data)
        sid = str(uuid.uuid4())
        return ServerSession(sid)

    def save_session(self, app, session, response):
        _session_cache.set(session.sid, dict(session))
        response.set_cookie('session_id', session.sid, httponly=True, samesite='Lax', max_age=86400)


app.session_interface = ServerSessionInterface()

CLIENT_ID = os.getenv("POLAR_CLIENT_ID")
CLIENT_SECRET = os.getenv("POLAR_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:5000/callback")

CACHE_TTL = 300  # 5 minutes


def get_client():
    client = PolarClient(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)
    if "access_token" in session:
        client.access_token = session["access_token"]
        client.user_id = session.get("user_id")
    return client


def _get_cached(key):
    """Get cached data from session if still fresh."""
    cache = session.get("_cache", {})
    entry = cache.get(key)
    if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
        return entry["data"]
    return None


def _set_cached(key, data):
    """Cache data in session."""
    if "_cache" not in session:
        session["_cache"] = {}
    session["_cache"][key] = {"data": data, "ts": time.time()}
    session.modified = True


def _fetch_with_cache(key, fn, errors, label):
    """Fetch data with caching."""
    cached = _get_cached(key)
    if cached is not None:
        return cached
    try:
        data = fn()
        _set_cached(key, data)
        return data
    except Exception as e:
        errors.append(f"Could not fetch {label}: {e}")
        return None


@app.route("/")
def index():
    if "access_token" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/login")
def login():
    client = get_client()
    return redirect(client.get_auth_url())


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Authorization failed — no code received.", 400

    client = get_client()
    token_data = client.exchange_code(code)
    session["access_token"] = token_data["access_token"]
    session["user_id"] = token_data.get("x_user_id")

    client.register_user()

    # Pull notifications to make new data available
    try:
        client.pull_notifications()
    except Exception as e:
        app.logger.warning(f"Pull notifications failed: {e}")

    # Sync exercises via transactional flow
    try:
        synced = client.sync_exercises()
        if synced:
            _set_cached("synced_exercises", synced)
    except Exception as e:
        app.logger.warning(f"Sync exercises failed: {e}")

    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@app.route("/dashboard/<date>")
def dashboard(date=None):
    if "access_token" not in session:
        return redirect(url_for("index"))

    if date:
        try:
            selected_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return redirect(url_for("dashboard"))
    else:
        selected_date = datetime.now()

    date_str = selected_date.strftime("%Y-%m-%d")
    prev_date = (selected_date - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (selected_date + timedelta(days=1)).strftime("%Y-%m-%d")
    is_today = date_str == datetime.now().strftime("%Y-%m-%d")

    client = get_client()
    errors = []

    # Fetch bulk data with caching (these return 28-30 days, no need to refetch per date)
    exercises = _fetch_with_cache("exercises", client.get_exercises, errors, "exercises")
    sleep_data = _fetch_with_cache("sleep", client.get_sleep, errors, "sleep")
    recharge_data = _fetch_with_cache("recharge", client.get_nightly_recharge, errors, "recharge")

    # Merge synced exercises from transactional flow
    synced = _get_cached("synced_exercises")
    if synced:
        if isinstance(exercises, list):
            existing_ids = {e.get("id") for e in exercises}
            for ex in synced:
                if ex.get("id") not in existing_ids:
                    exercises.append(ex)
        elif not exercises:
            exercises = synced

    # Additional bulk data
    activities = _fetch_with_cache("activities", client.get_activities, errors, "activities")
    cardio_load = _fetch_with_cache("cardio_load", client.get_cardio_load_history, errors, "cardio load")
    alertness = _fetch_with_cache("alertness", client.get_alertness, errors, "alertness")
    bedtime = _fetch_with_cache("bedtime", client.get_circadian_bedtime, errors, "bedtime")

    # Per-date data
    hr_data = _fetch_with_cache(f"hr_{date_str}", lambda: client.get_heart_rate(date_str), errors, "heart rate")
    body_temp = _fetch_with_cache(f"temp_{date_str}", lambda: client.get_body_temperature(date_str), errors, "temperature")
    sleep_temp = _fetch_with_cache(f"stemp_{date_str}", lambda: client.get_sleep_temperature(date_str), errors, "sleep temp")
    spo2 = _fetch_with_cache(f"spo2_{date_str}", lambda: client.get_spo2(date_str), errors, "spo2")

    # Find data for selected date
    selected_sleep = None
    if sleep_data:
        nights = sleep_data.get("nights", []) if isinstance(sleep_data, dict) else sleep_data
        for n in nights:
            if n.get("date") == date_str:
                selected_sleep = n
                break

    selected_recharge = None
    if recharge_data:
        recharges = recharge_data.get("recharges", []) if isinstance(recharge_data, dict) else recharge_data
        for r in recharges:
            if r.get("date") == date_str:
                selected_recharge = r
                break

    daily_scores = compute_daily_scores(sleep_data, recharge_data)
    summaries = compute_summaries(sleep_data, recharge_data)
    exercise_list = _format_exercises(exercises)

    # Merge local (manual) exercises
    local_exercises = local_get_exercises()
    for le in local_exercises:
        h = le.get("duration_min", 0) // 60
        m = le.get("duration_min", 0) % 60
        exercise_list.append({
            "id": le["id"],
            "date": le["date"],
            "time": "",
            "sport": le["sport"],
            "duration": f"{h}h {m}m" if h else f"{m}m",
            "calories": le.get("calories", 0),
            "avg_hr": le.get("avg_hr") or "-",
            "distance_km": le.get("distance_km", 0),
            "source": "manual",
            "notes": le.get("notes", ""),
        })

    # Sort all exercises by date descending
    exercise_list.sort(key=lambda e: e.get("date", ""), reverse=True)

    # Attach training benefit tags
    profile = get_profile()
    for ex in exercise_list:
        dur = 0
        d_str = ex.get("duration", "")
        if "h" in d_str:
            parts = d_str.replace("m", "").split("h")
            dur = int(parts[0].strip()) * 60 + int(parts[1].strip()) if len(parts) == 2 and parts[1].strip() else int(parts[0].strip()) * 60
        elif "m" in d_str:
            dur = int(d_str.replace("m", "").strip())
        avg = ex.get("avg_hr", 0)
        avg = int(avg) if str(avg).isdigit() else 0
        ex["training_benefit"] = classify_session(dur, avg, 0, ex.get("sport", ""), profile)

    training_summary = get_training_summary(local_exercises)
    coaching = analyze_training(exercises, sleep_data, recharge_data, training_summary)

    has_ai = bool(os.getenv("OPENROUTER_API_KEY"))

    # Build lookup dicts for client-side date switching
    all_sleep = {}
    if sleep_data:
        nights = sleep_data.get("nights", []) if isinstance(sleep_data, dict) else sleep_data
        for n in nights:
            all_sleep[n.get("date", "")] = {
                "sleep_score": n.get("sleep_score", 0),
                "light_sleep": n.get("light_sleep", 0),
                "deep_sleep": n.get("deep_sleep", 0),
                "rem_sleep": n.get("rem_sleep", 0),
                "sleep_start_time": n.get("sleep_start_time", ""),
                "sleep_end_time": n.get("sleep_end_time", ""),
            }

    all_recharge = {}
    if recharge_data:
        recharges = recharge_data.get("recharges", []) if isinstance(recharge_data, dict) else recharge_data
        for r in recharges:
            all_recharge[r.get("date", "")] = {
                "ans_charge": r.get("ans_charge", 0),
                "heart_rate_variability_avg": r.get("heart_rate_variability_avg", 0),
                "heart_rate_avg": r.get("heart_rate_avg", 0),
                "breathing_rate_avg": r.get("breathing_rate_avg", 0),
                "hrv_samples": r.get("hrv_samples", {}),
            }

    # Build activity data for template
    all_activity = {}
    if activities:
        act_list = activities if isinstance(activities, list) else activities.get("activity-log", activities.get("activities", []))
        if isinstance(act_list, list):
            for a in act_list:
                all_activity[a.get("date", "")] = {
                    "steps": a.get("steps", 0),
                    "calories": a.get("calories", 0),
                    "active_calories": a.get("active_calories", a.get("active-calories", 0)),
                    "distance": a.get("distance_from_steps", a.get("distance", 0)),
                    "active_duration": a.get("active_duration", a.get("active-duration", 0)),
                }

    return render_template(
        "dashboard.html",
        coaching=coaching,
        exercises=exercise_list,
        hr_data=hr_data,
        sleep_data=sleep_data,
        selected_sleep=selected_sleep,
        selected_recharge=selected_recharge,
        all_sleep_json=json.dumps(all_sleep),
        all_recharge_json=json.dumps(all_recharge),
        all_activity_json=json.dumps(all_activity),
        daily_scores_json=json.dumps(daily_scores),
        body_temp=body_temp,
        sleep_temp=sleep_temp,
        spo2=spo2,
        alertness=alertness,
        bedtime=bedtime,
        summaries=summaries,
        training_summary=training_summary,
        events_json=json.dumps(_get_cached_events()),
        profile=get_profile(),
        errors=errors,
        selected_date=date_str,
        is_today=date_str == datetime.now().strftime("%Y-%m-%d"),
        has_ai=has_ai,
    )


@app.route("/api/hr/<date>")
def get_hr_data(date):
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    client = get_client()
    errors = []
    hr = _fetch_with_cache(f"hr_{date}", lambda: client.get_heart_rate(date), errors, "hr")
    if hr:
        return jsonify(hr)
    return jsonify(None)


@app.route("/api/weather")
def api_weather():
    """Get weather for stored or auto-detected location."""
    from ai_coach import _get_weather_for_location
    location = session.get("location", "")
    weather = _get_weather_for_location(location)
    if weather:
        return jsonify(weather)
    return jsonify(None)


@app.route("/api/location", methods=["POST"])
def set_location():
    """Set location manually."""
    data = request.json
    loc = data.get("location", "")
    session["location"] = loc
    return jsonify({"status": "ok", "location": loc})


@app.route("/api/sync", methods=["POST"])
def sync_data():
    """Force sync: pull notifications and fetch new exercises."""
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    client = get_client()
    results = {}

    # Pull notifications
    try:
        notifs = client.pull_notifications()
        results["notifications"] = len(notifs)
    except Exception as e:
        results["notifications_error"] = str(e)

    # Sync exercises
    try:
        synced = client.sync_exercises()
        results["synced_exercises"] = len(synced)
        if synced:
            _set_cached("synced_exercises", synced)
    except Exception as e:
        results["sync_error"] = str(e)

    # Clear cache to force refetch
    session.pop("_cache", None)
    session.modified = True

    results["status"] = "ok"
    return jsonify(results)


@app.route("/api/ai-advice", methods=["POST"])
def ai_advice():
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    client = get_client()
    errors = []

    exercises = _fetch_with_cache("exercises", client.get_exercises, errors, "exercises")
    sleep_data = _fetch_with_cache("sleep", client.get_sleep, errors, "sleep")
    recharge_data = _fetch_with_cache("recharge", client.get_nightly_recharge, errors, "recharge")
    today = datetime.now().strftime("%Y-%m-%d")
    hr_data = _fetch_with_cache(f"hr_{today}", lambda: client.get_heart_rate(today), errors, "heart rate")

    local_exercises = local_get_exercises()
    training_sum = get_training_summary(local_exercises)
    coaching = analyze_training(exercises, sleep_data, recharge_data, training_sum)
    prompt = request.json.get("prompt") if request.is_json else None

    try:
        all_exercises = (exercises or []) + local_exercises
        loc = session.get("location", "")
        advice = get_ai_advice(sleep_data, recharge_data, all_exercises, hr_data, coaching, prompt, training_sum, loc)
        if advice is None:
            return jsonify({"error": "OPENROUTER_API_KEY not set. Add it to .env"}), 500
        return jsonify({"advice": advice})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/training-plan", methods=["POST"])
def training_plan():
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    client = get_client()
    errors = []

    exercises = _fetch_with_cache("exercises", client.get_exercises, errors, "exercises")
    sleep_data = _fetch_with_cache("sleep", client.get_sleep, errors, "sleep")
    recharge_data = _fetch_with_cache("recharge", client.get_nightly_recharge, errors, "recharge")

    local_exercises = local_get_exercises()
    training_sum = get_training_summary(local_exercises)
    coaching = analyze_training(exercises, sleep_data, recharge_data, training_sum)
    goal = request.json.get("goal") if request.is_json else None

    try:
        all_exercises = (exercises or []) + local_exercises
        loc = session.get("location", "")
        plan = generate_training_plan(sleep_data, recharge_data, all_exercises, coaching, goal, training_sum, loc)
        if plan is None:
            return jsonify({"error": "OPENROUTER_API_KEY not set. Add it to .env"}), 500
        return jsonify({"plan": plan})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/exercise/<exercise_id>")
def exercise_detail(exercise_id):
    if "access_token" not in session:
        return redirect(url_for("index"))

    client = get_client()
    exercise = client.get_exercise(exercise_id)
    return render_template("session.html", exercise=exercise)


@app.route("/api/exercises", methods=["POST"])
def add_manual_exercise():
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.json
    exercise = local_add_exercise(
        date=data.get("date", datetime.now().strftime("%Y-%m-%d")),
        sport=data.get("sport", "Other"),
        duration_min=data.get("duration_min", 30),
        calories=data.get("calories", 0),
        avg_hr=data.get("avg_hr", 0),
        distance_km=data.get("distance_km", 0),
        notes=data.get("notes", ""),
    )
    return jsonify(exercise)


@app.route("/api/exercises/<exercise_id>", methods=["DELETE"])
def delete_manual_exercise(exercise_id):
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    local_delete_exercise(exercise_id)
    return jsonify({"status": "ok"})


@app.route("/profile", methods=["GET"])
def profile_page():
    if "access_token" not in session:
        return redirect(url_for("index"))
    return render_template("profile.html", profile=get_profile())


@app.route("/api/profile", methods=["GET"])
def api_get_profile():
    return jsonify(get_profile())


@app.route("/api/profile", methods=["POST"])
def api_save_profile():
    data = request.json
    save_profile(data)
    return jsonify({"status": "ok"})


@app.route("/api/plan", methods=["GET"])
def api_get_plan():
    return jsonify(get_active_plan())


@app.route("/api/plan", methods=["POST"])
def api_save_plan():
    data = request.json
    save_plan(data)
    return jsonify({"status": "ok"})


@app.route("/api/plan", methods=["DELETE"])
def api_delete_plan():
    delete_plan()
    return jsonify({"status": "ok"})


@app.route("/api/events")
def api_events():
    return jsonify(get_orienteering_events())


@app.route("/api/create-plan", methods=["POST"])
def api_create_plan():
    """Use AI to create a structured training plan."""
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    from ai_coach import create_training_plan

    client = get_client()
    errors = []
    sleep_data = _fetch_with_cache("sleep", client.get_sleep, errors, "sleep")
    recharge_data = _fetch_with_cache("recharge", client.get_nightly_recharge, errors, "recharge")
    local_exercises = local_get_exercises()
    training_sum = get_training_summary(local_exercises)
    coaching = analyze_training(None, sleep_data, recharge_data, training_sum)
    events = get_orienteering_events()

    data = request.json
    plan_type = data.get("type", "general")
    race_date = data.get("race_date", "")
    race_distance = data.get("race_distance", "")
    notes = data.get("notes", "")
    loc = session.get("location", "")

    try:
        result = create_training_plan(
            sleep_data, recharge_data, local_exercises, coaching,
            training_sum, events, plan_type, race_date, race_distance, notes, loc
        )
        if result is None:
            return jsonify({"error": "API key not set"}), 500

        plan_text, schedule = result

        plan_data = {
            "type": plan_type,
            "race_date": race_date,
            "race_distance": race_distance,
            "created": datetime.now().isoformat(),
            "plan_text": plan_text,
            "schedule": schedule,
            "notes": notes,
        }
        save_plan(plan_data)
        return jsonify(plan_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/adjust-plan", methods=["POST"])
def api_adjust_plan():
    """Ask AI to adjust today's plan based on current state."""
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    from ai_coach import adjust_daily_plan

    client = get_client()
    errors = []
    sleep_data = _fetch_with_cache("sleep", client.get_sleep, errors, "sleep")
    recharge_data = _fetch_with_cache("recharge", client.get_nightly_recharge, errors, "recharge")
    local_exercises = local_get_exercises()
    training_sum = get_training_summary(local_exercises)
    coaching = analyze_training(None, sleep_data, recharge_data, training_sum)
    active_plan = get_active_plan()
    reason = request.json.get("reason", "") if request.is_json else ""
    loc = session.get("location", "")

    try:
        adjustment = adjust_daily_plan(
            sleep_data, recharge_data, local_exercises, coaching,
            training_sum, active_plan, reason, loc
        )
        if adjustment is None:
            return jsonify({"error": "API key not set"}), 500
        return jsonify({"adjustment": adjustment})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/journal", methods=["GET"])
def api_get_journals():
    return jsonify(get_journals())


@app.route("/api/journal", methods=["POST"])
def api_add_journal():
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.json
    entry = add_journal(
        date=data.get("date", datetime.now().strftime("%Y-%m-%d")),
        mood=data.get("mood", 3),
        fatigue=data.get("fatigue", 3),
        nutrition=data.get("nutrition", "ok"),
        notes=data.get("notes", ""),
    )
    return jsonify(entry)


@app.route("/api/journal/<date>")
def api_get_journal(date):
    entry = get_journal(date)
    if entry:
        return jsonify(entry)
    return jsonify(None)


@app.route("/api/race-predictions")
def api_race_predictions():
    from coach import predict_race_times
    profile = get_profile()
    return jsonify(predict_race_times(profile))


@app.route("/api/pace-zones")
def api_pace_zones():
    from coach import get_pace_zones
    profile = get_profile()
    return jsonify(get_pace_zones(profile))


@app.route("/api/weekly-volumes")
def api_weekly_volumes():
    local_exercises = local_get_exercises()
    return jsonify(get_weekly_volumes(local_exercises))


@app.route("/api/weekly-report", methods=["POST"])
def api_weekly_report():
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    from ai_coach import generate_weekly_report

    client = get_client()
    errors = []
    sleep_data = _fetch_with_cache("sleep", client.get_sleep, errors, "sleep")
    recharge_data = _fetch_with_cache("recharge", client.get_nightly_recharge, errors, "recharge")
    local_exercises = local_get_exercises()
    training_sum = get_training_summary(local_exercises)
    all_exercises = (_fetch_with_cache("exercises", client.get_exercises, errors, "exercises") or []) + local_exercises
    coaching = analyze_training(all_exercises, sleep_data, recharge_data, training_sum)
    loc = session.get("location", "")

    try:
        report = generate_weekly_report(sleep_data, recharge_data, all_exercises, coaching, training_sum, loc)
        if report is None:
            return jsonify({"error": "OPENROUTER_API_KEY not set. Add it to .env"}), 500
        return jsonify({"report": report})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/monthly-report", methods=["POST"])
def api_monthly_report():
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    from ai_coach import generate_monthly_report

    client = get_client()
    errors = []
    sleep_data = _fetch_with_cache("sleep", client.get_sleep, errors, "sleep")
    recharge_data = _fetch_with_cache("recharge", client.get_nightly_recharge, errors, "recharge")
    local_exercises = local_get_exercises()
    training_sum = get_training_summary(local_exercises)
    all_exercises = (_fetch_with_cache("exercises", client.get_exercises, errors, "exercises") or []) + local_exercises
    coaching = analyze_training(all_exercises, sleep_data, recharge_data, training_sum)
    loc = session.get("location", "")

    try:
        report = generate_monthly_report(sleep_data, recharge_data, all_exercises, coaching, training_sum, loc)
        if report is None:
            return jsonify({"error": "API key not set"}), 500
        return jsonify({"report": report})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/session-insight", methods=["POST"])
def api_session_insight():
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    from ai_coach import get_session_insight

    data = request.json
    try:
        insight = get_session_insight(data)
        if insight is None:
            return jsonify({"error": "API key not set"}), 500
        return jsonify({"insight": insight})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/debug")
def debug_data():
    if "access_token" not in session:
        return redirect(url_for("index"))

    client = get_client()
    data = {}

    today = datetime.now().strftime("%Y-%m-%d")
    for label, fn in [
        ("exercises", client.get_exercises),
        ("activities", client.get_activities),
        ("activity_today", lambda: client.get_activity(today)),
        ("cardio_load", client.get_cardio_load_history),
        ("alertness", client.get_alertness),
        ("bedtime", client.get_circadian_bedtime),
        ("body_temp", lambda: client.get_body_temperature(today)),
        ("sleep_temp", lambda: client.get_sleep_temperature(today)),
        ("spo2", lambda: client.get_spo2(today)),
        ("ecg", lambda: client.get_ecg(today)),
        ("sleep", client.get_sleep),
        ("recharge", client.get_nightly_recharge),
        ("hr", lambda: client.get_heart_rate(today)),
    ]:
        try:
            result = fn()
            # Trim large lists for readability
            if isinstance(result, dict):
                trimmed = {}
                for k, v in result.items():
                    trimmed[k] = v[:2] if isinstance(v, list) and len(v) > 2 else v
                data[label] = trimmed
            elif isinstance(result, list):
                data[label] = result[:2] if len(result) > 2 else result
            else:
                data[label] = result
        except Exception as e:
            data[label] = {"error": str(e)}

    return app.response_class(
        json.dumps(data, indent=2, default=str),
        mimetype="application/json",
    )


_events_cache = {"data": None, "ts": 0}

def _get_cached_events():
    import time
    if time.time() - _events_cache["ts"] < 3600:
        return _events_cache["data"] or []
    try:
        events = get_orienteering_events()
        _events_cache["data"] = events
        _events_cache["ts"] = time.time()
        return events
    except Exception:
        return _events_cache["data"] or []


def _safe_fetch(fn, errors, label):
    try:
        return fn()
    except Exception as e:
        errors.append(f"Could not fetch {label}: {e}")
        return None


def _format_exercises(exercises):
    if not exercises:
        return []

    items = exercises if isinstance(exercises, list) else exercises.get("exercises", [])
    formatted = []
    for e in items:
        start = e.get("start-time", e.get("startTime", ""))
        duration = e.get("duration", "")
        sport = e.get("detailed-sport-info", e.get("sport", "Unknown"))
        if isinstance(sport, dict):
            sport = sport.get("name", "Unknown")

        calories = e.get("calories", e.get("kiloCalories", 0))
        avg_hr = e.get("heart-rate", {}).get("average", "-")
        if isinstance(avg_hr, dict):
            avg_hr = avg_hr.get("value", "-")

        formatted.append({
            "id": e.get("id", ""),
            "date": start[:10] if start else "-",
            "time": start[11:16] if len(start) > 15 else "-",
            "sport": sport,
            "duration": _format_duration(duration),
            "calories": calories,
            "avg_hr": avg_hr,
        })
    return formatted


def _format_duration(duration):
    if isinstance(duration, (int, float)):
        mins = int(duration / 60)
        return f"{mins // 60}h {mins % 60}m"
    if isinstance(duration, str) and ":" in duration:
        parts = duration.replace("PT", "").split(":")
        try:
            h, m = int(parts[0]), int(parts[1])
            return f"{h}h {m}m" if h else f"{m}m"
        except (ValueError, IndexError):
            return duration
    return str(duration)


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", port=5000)

"""Rules-based training coach with holistic scoring."""

from datetime import datetime, timedelta
import math


# ========== Thresholds ==========

SLEEP_THRESHOLDS = [(80, "Excellent", "green"), (60, "Good", "blue"), (40, "Fair", "yellow"), (0, "Poor", "red")]
RECOVERY_THRESHOLDS = [(2.0, "Excellent", "green"), (0.0, "Good", "blue"), (-2.0, "Fair", "yellow"), (-999, "Poor", "red")]
STRESS_THRESHOLDS = [(0, "Low", "green"), (26, "Moderate", "blue"), (51, "Elevated", "yellow"), (76, "High", "red")]
READINESS_THRESHOLDS = [(80, "Peak", "green"), (60, "Ready", "blue"), (40, "Moderate", "yellow"), (0, "Rest", "red")]


def _classify(value, thresholds, higher_is_better=True):
    if higher_is_better:
        for thresh, label, color in thresholds:
            if value >= thresh:
                return label, color
    else:
        for thresh, label, color in thresholds:
            if value <= thresh:
                return label, color
    return thresholds[-1][1], thresholds[-1][2]


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def _fmt_hours(h):
    """Format decimal hours as 'Xh Ym'."""
    hrs = int(h)
    mins = round((h - hrs) * 60)
    return f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"


# ========== Stress Score ==========

def compute_stress_scores(recharge_data):
    """Compute stress score per date from recharge data."""
    if not recharge_data:
        return {}

    recharges = recharge_data.get("recharges", []) if isinstance(recharge_data, dict) else recharge_data
    if not recharges:
        return {}

    # Compute baselines
    all_hrv = [r["heart_rate_variability_avg"] for r in recharges if r.get("heart_rate_variability_avg")]
    all_hr = [r["heart_rate_avg"] for r in recharges if r.get("heart_rate_avg")]

    hrv_mean = sum(all_hrv) / len(all_hrv) if all_hrv else 0
    hrv_std = _std(all_hrv) if len(all_hrv) >= 7 else 0
    hr_mean = sum(all_hr) / len(all_hr) if all_hr else 0
    hr_std = _std(all_hr) if len(all_hr) >= 7 else 0

    results = {}
    for r in recharges:
        date = r.get("date", "")
        ans = r.get("ans_charge", 0)
        hrv = r.get("heart_rate_variability_avg", 0)
        hr = r.get("heart_rate_avg", 0)

        # ANS stress (40%)
        ans_stress = _clamp((5 - ans) / 10 * 100)

        # HRV stress (35%)
        if hrv_std > 0 and hrv:
            hrv_z = (hrv_mean - hrv) / hrv_std
            hrv_stress = _clamp(hrv_z * 25 + 50)
        elif hrv:
            hrv_stress = 20 if hrv >= 60 else 50 if hrv >= 40 else 75 if hrv >= 20 else 95
        else:
            hrv_stress = 50

        # HR stress (25%)
        if hr_std > 0 and hr:
            hr_z = (hr - hr_mean) / hr_std
            hr_stress = _clamp(hr_z * 25 + 50)
        elif hr:
            hr_stress = 15 if hr <= 55 else 35 if hr <= 65 else 60 if hr <= 75 else 85
        else:
            hr_stress = 50

        score = round(0.40 * ans_stress + 0.35 * hrv_stress + 0.25 * hr_stress)
        label, color = _classify_stress(score)

        results[date] = {
            "stress_score": score,
            "ans_stress": round(ans_stress),
            "hrv_stress": round(hrv_stress),
            "hr_stress": round(hr_stress),
            "label": label,
            "color": color,
        }

    return results


def _classify_stress(score):
    if score <= 25:
        return "Low", "green"
    if score <= 50:
        return "Moderate", "blue"
    if score <= 75:
        return "Elevated", "yellow"
    return "High", "red"


def _std(values):
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ========== Daily Scores ==========

def compute_daily_scores(sleep_data, recharge_data):
    """Compute holistic scores per date for the UI."""
    scores = {}

    # Sleep scores
    if sleep_data:
        nights = sleep_data.get("nights", []) if isinstance(sleep_data, dict) else sleep_data
        for n in nights:
            date = n.get("date", "")
            ss = n.get("sleep_score", 0)
            label, color = _classify(ss, SLEEP_THRESHOLDS)
            total_sec = n.get("light_sleep", 0) + n.get("deep_sleep", 0) + n.get("rem_sleep", 0)
            scores.setdefault(date, {})
            scores[date]["sleep"] = {
                "score": ss,
                "label": label,
                "color": color,
                "hours": round(total_sec / 3600, 1),
            }

    # Recovery + Stress scores
    if recharge_data:
        recharges = recharge_data.get("recharges", []) if isinstance(recharge_data, dict) else recharge_data
        stress_scores = compute_stress_scores(recharge_data)

        for r in recharges:
            date = r.get("date", "")
            ans = r.get("ans_charge", 0)
            label, color = _classify(ans, RECOVERY_THRESHOLDS)
            scores.setdefault(date, {})
            scores[date]["recovery"] = {
                "ans_charge": ans,
                "label": label,
                "color": color,
            }
            if date in stress_scores:
                scores[date]["stress"] = stress_scores[date]

    # Readiness = composite of sleep, recovery, stress
    for date, s in scores.items():
        sleep_pct = min(s.get("sleep", {}).get("score", 0), 100)  # 0-100
        # Map ANS charge (-10 to +10) to 0-100
        ans = s.get("recovery", {}).get("ans_charge", 0)
        recovery_pct = _clamp((ans + 10) / 20 * 100)
        # Invert stress (low stress = high readiness)
        stress = s.get("stress", {}).get("stress_score", 50)
        stress_inv = 100 - stress

        readiness = round(0.35 * sleep_pct + 0.35 * recovery_pct + 0.30 * stress_inv)
        label, color = _classify(readiness, READINESS_THRESHOLDS)
        s["readiness"] = {"score": readiness, "label": label, "color": color}

    return scores


# ========== Summaries ==========

def compute_summaries(sleep_data, recharge_data):
    """Compute 7-day and all-available averages with trends."""
    now = datetime.now().date()
    week_cutoff = now - timedelta(days=7)

    week = {"sleep_score": [], "sleep_hours": [], "ans": [], "hrv": [], "rhr": [], "stress": []}
    month = {"sleep_score": [], "sleep_hours": [], "ans": [], "hrv": [], "rhr": [], "stress": []}

    if sleep_data:
        nights = sleep_data.get("nights", []) if isinstance(sleep_data, dict) else sleep_data
        for n in nights:
            d = _parse_date_only(n.get("date", ""))
            if not d:
                continue
            ss = n.get("sleep_score", 0)
            total_sec = n.get("light_sleep", 0) + n.get("deep_sleep", 0) + n.get("rem_sleep", 0)
            hours = total_sec / 3600

            if ss > 0:
                month["sleep_score"].append(ss)
                month["sleep_hours"].append(hours)
                if d >= week_cutoff:
                    week["sleep_score"].append(ss)
                    week["sleep_hours"].append(hours)

    stress_scores = compute_stress_scores(recharge_data) if recharge_data else {}

    if recharge_data:
        recharges = recharge_data.get("recharges", []) if isinstance(recharge_data, dict) else recharge_data
        for r in recharges:
            d = _parse_date_only(r.get("date", ""))
            if not d:
                continue

            ans = r.get("ans_charge")
            hrv = r.get("heart_rate_variability_avg")
            rhr = r.get("heart_rate_avg")
            stress = stress_scores.get(r.get("date", ""), {}).get("stress_score")

            for val, key in [(ans, "ans"), (hrv, "hrv"), (rhr, "rhr"), (stress, "stress")]:
                if val is not None:
                    month[key].append(val)
                    if d >= week_cutoff:
                        week[key].append(val)

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    week_avgs = {k: avg(v) for k, v in week.items()}
    month_avgs = {k: avg(v) for k, v in month.items()}

    # Trends (compare week to month)
    trends = {}
    higher_is_better = {"sleep_score", "sleep_hours", "ans", "hrv"}
    for key in week_avgs:
        w, m = week_avgs[key], month_avgs[key]
        if w is None or m is None or m == 0:
            trends[key] = "stable"
            continue
        diff_pct = (w - m) / abs(m)
        if abs(diff_pct) < 0.05:
            trends[key] = "stable"
        elif key in higher_is_better:
            trends[key] = "improving" if diff_pct > 0 else "declining"
        else:  # rhr, stress: lower is better
            trends[key] = "improving" if diff_pct < 0 else "declining"

    return {
        "week": week_avgs,
        "month": month_avgs,
        "trends": trends,
        "week_count": max(len(v) for v in week.values()) if any(week.values()) else 0,
        "month_count": max(len(v) for v in month.values()) if any(month.values()) else 0,
    }


def _parse_date_only(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ========== Insights Engine ==========

def analyze_training(exercises, sleep_data, recharge_data, training_summary=None):
    """Generate data-driven insights from all available data."""
    items = []  # list of {"text": str, "type": "warn"|"ok"|"info"}
    daily_scores = compute_daily_scores(sleep_data, recharge_data)
    summaries = compute_summaries(sleep_data, recharge_data)

    # --- Today's readiness ---
    today = datetime.now().strftime("%Y-%m-%d")
    today_scores = daily_scores.get(today, {})
    # Fall back to most recent date if today not available
    if not today_scores and daily_scores:
        latest = max(daily_scores.keys())
        today_scores = daily_scores[latest]
        today = latest

    readiness = today_scores.get("readiness", {})
    sleep = today_scores.get("sleep", {})
    recovery = today_scores.get("recovery", {})
    stress = today_scores.get("stress", {})

    # Readiness-based recommendation
    r_score = readiness.get("score", 0)
    if r_score >= 80:
        items.append({"text": f"Readiness {r_score}/100 — great day for a hard session or race.", "type": "ok"})
    elif r_score >= 60:
        items.append({"text": f"Readiness {r_score}/100 — good for moderate training.", "type": "ok"})
    elif r_score >= 40:
        items.append({"text": f"Readiness {r_score}/100 — keep it light, focus on technique or easy cardio.", "type": "warn"})
    else:
        items.append({"text": f"Readiness {r_score}/100 — your body needs rest. Consider a rest day or very light activity.", "type": "warn"})

    # --- Sleep insights ---
    ss = sleep.get("score", 0)
    sh = sleep.get("hours", 0)
    if ss > 0:
        sh_fmt = _fmt_hours(sh)
        if ss < 40:
            items.append({"text": f"Poor sleep ({ss}/100, {sh_fmt}). Recovery will be impaired — avoid intense training.", "type": "warn"})
        elif ss < 60:
            items.append({"text": f"Fair sleep ({ss}/100, {sh_fmt}). Not fully rested — moderate your effort today.", "type": "info"})
        elif sh < 6.5:
            items.append({"text": f"Short sleep ({sh_fmt}) despite decent quality ({ss}/100). Try to get 7-8h consistently.", "type": "warn"})
        elif ss >= 80 and sh >= 7:
            items.append({"text": f"Excellent sleep ({ss}/100, {sh_fmt}). You're well rested.", "type": "ok"})

    # --- Recovery insights ---
    ans = recovery.get("ans_charge", 0)
    if recovery:
        if ans <= -5:
            items.append({"text": f"ANS charge very low ({ans:.1f}). Your nervous system is strained — prioritize rest and sleep.", "type": "warn"})
        elif ans <= -2:
            items.append({"text": f"ANS charge below baseline ({ans:.1f}). Go easy today.", "type": "warn"})
        elif ans >= 2:
            items.append({"text": f"ANS charge positive ({ans:+.1f}). Your body is well recovered.", "type": "ok"})

    # --- Stress insights ---
    s_score = stress.get("stress_score", 0)
    if stress:
        if s_score >= 75:
            items.append({"text": f"Stress is high ({s_score}/100). Accumulated fatigue detected — back off training.", "type": "warn"})
        elif s_score >= 50:
            items.append({"text": f"Moderate stress ({s_score}/100). Listen to your body during training.", "type": "info"})

    # --- Trend insights (from summaries) ---
    trends = summaries.get("trends", {})
    week = summaries.get("week", {})
    month = summaries.get("month", {})

    if trends.get("sleep_score") == "declining" and week.get("sleep_score") and month.get("sleep_score"):
        items.append({"text": f"Sleep quality declining — 7d avg {week['sleep_score']:.0f} vs monthly {month['sleep_score']:.0f}.", "type": "warn"})

    if trends.get("hrv") == "declining" and week.get("hrv") and month.get("hrv"):
        items.append({"text": f"HRV trending down ({week['hrv']:.0f}ms vs {month['hrv']:.0f}ms avg). Watch for overtraining.", "type": "warn"})
    elif trends.get("hrv") == "improving" and week.get("hrv") and month.get("hrv"):
        items.append({"text": f"HRV improving ({week['hrv']:.0f}ms vs {month['hrv']:.0f}ms avg). Fitness adapting well.", "type": "ok"})

    if trends.get("rhr") == "declining" and week.get("rhr") and month.get("rhr"):
        items.append({"text": f"Resting HR dropping ({week['rhr']:.0f} vs {month['rhr']:.0f}bpm). Good sign of cardiovascular adaptation.", "type": "ok"})
    elif trends.get("rhr") == "improving" is False and trends.get("rhr") == "declining":
        pass  # already handled above
    elif week.get("rhr") and month.get("rhr") and week["rhr"] > month["rhr"] + 3:
        items.append({"text": f"Resting HR elevated ({week['rhr']:.0f} vs {month['rhr']:.0f}bpm). Could indicate fatigue or illness.", "type": "warn"})

    if trends.get("stress") == "declining":
        items.append({"text": "Stress levels improving this week. Good recovery pattern.", "type": "ok"})
    elif trends.get("stress") == "improving":  # stress "improving" means going up (bad)
        pass  # already covered by declining label

    # --- Training insights ---
    if training_summary:
        tw = training_summary.get("week", {})
        tm = training_summary.get("month", {})

        if tw["sessions"] > 0:
            h = tw["duration_min"] // 60
            m = tw["duration_min"] % 60
            txt = f"This week: {tw['sessions']} sessions, {h}h{m}m"
            if tw["distance_km"] > 0:
                txt += f", {tw['distance_km']:.1f}km"
            items.append({"text": txt, "type": "info"})

            if tw["sessions"] >= 7:
                items.append({"text": "Training every day this week — schedule a rest day for adaptation.", "type": "warn"})

        if tm["sessions"] > 0 and tw["sessions"] > 0:
            weekly_avg = tm["sessions"] / 4.3  # ~4.3 weeks per month
            if tw["sessions"] > weekly_avg * 1.5 and weekly_avg >= 2:
                items.append({"text": f"Volume spike — {tw['sessions']} sessions vs ~{weekly_avg:.0f}/week average. Risk of overtraining.", "type": "warn"})

        if tm["sessions"] > 0:
            sports = tm["sports"]
            if len(sports) == 1:
                items.append({"text": f"Only doing {list(sports.keys())[0]} this month. Cross-training helps prevent injury.", "type": "info"})

        if tw["sessions"] == 0 and tm["sessions"] > 0:
            items.append({"text": "No sessions logged this week. Stay consistent for progress.", "type": "info"})

    # --- Sleep consistency ---
    if sleep_data:
        nights = sleep_data.get("nights", []) if isinstance(sleep_data, dict) else sleep_data
        recent = nights[-7:] if len(nights) > 7 else nights
        durations = [_sleep_duration_hours(n) for n in recent if _sleep_duration_hours(n) > 0]
        if len(durations) >= 3:
            std = _std(durations)
            if std > 1.5:
                items.append({"text": f"Inconsistent sleep (varies by {std:.1f}h). Regular bedtime helps recovery.", "type": "info"})

    # Fallback if nothing generated
    if not items:
        items.append({"text": "No data available to generate insights.", "type": "info"})

    # Separate into warnings, ok, info
    warnings = [i["text"] for i in items if i["type"] == "warn"]
    recommendations = [i["text"] for i in items if i["type"] == "ok"]
    info = [i["text"] for i in items if i["type"] == "info"]

    return {
        "warnings": warnings,
        "recommendations": recommendations,
        "info": info,
    }


def _sleep_duration_hours(night):
    total = night.get("light_sleep", 0) + night.get("deep_sleep", 0) + night.get("rem_sleep", 0) + night.get("unrecognized_sleep_stage", 0)
    return total / 3600 if total > 0 else 0

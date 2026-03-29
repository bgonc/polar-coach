"""Polar AccessLink API client."""

import requests
from urllib.parse import urlencode


BASE_URL = "https://www.polaraccesslink.com"
TOKEN_URL = "https://polarremote.com/v2/oauth2/token"
AUTH_URL = "https://flow.polar.com/oauth2/authorization"


class PolarClient:
    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.access_token = None
        self.user_id = None

    def get_auth_url(self):
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code):
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
            auth=(self.client_id, self.client_secret),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json;charset=UTF-8",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.user_id = data.get("x_user_id")
        return data

    def register_user(self):
        resp = requests.post(
            f"{BASE_URL}/v3/users",
            json={"member-id": self.user_id},
            headers=self._headers(),
        )
        if resp.status_code == 409:
            return {"status": "already_registered"}
        resp.raise_for_status()
        return resp.json()

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def _basic_auth(self):
        return (self.client_id, self.client_secret)

    # --- Pull Notifications (triggers data availability) ---

    def pull_notifications(self):
        """Check for new data and return available notifications."""
        resp = requests.get(
            f"{BASE_URL}/v3/notifications",
            auth=self._basic_auth(),
            headers={"Accept": "application/json"},
        )
        if resp.status_code == 204:
            return []
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json().get("available-data", [])

    # --- Exercises ---

    def sync_exercises(self):
        """Pull new exercises via the transactional flow, then list all."""
        # 1. Create exercise transaction
        resp = requests.post(
            f"{BASE_URL}/v3/users/{self.user_id}/exercise-transactions",
            headers=self._headers(),
        )
        if resp.status_code == 201:
            tx = resp.json()
            tx_url = tx.get("resource-uri", "")
            if tx_url:
                # 2. List exercises in transaction
                list_resp = requests.get(tx_url, headers=self._headers())
                if list_resp.status_code == 200:
                    exercises_urls = list_resp.json().get("exercises", [])
                    exercises = []
                    for url in exercises_urls:
                        ex_resp = requests.get(url, headers=self._headers())
                        if ex_resp.status_code == 200:
                            exercises.append(ex_resp.json())
                    # 3. Commit transaction
                    requests.put(tx_url, headers=self._headers())
                    return exercises
        # 204 = no new exercises
        return []

    def get_exercises(self):
        """Get exercises from non-transactional endpoint."""
        resp = requests.get(f"{BASE_URL}/v3/exercises", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def get_exercise(self, exercise_id):
        resp = requests.get(
            f"{BASE_URL}/v3/exercises/{exercise_id}", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    # --- Heart Rate ---

    def get_heart_rate(self, date):
        resp = requests.get(
            f"{BASE_URL}/v3/users/continuous-heart-rate/{date}",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    # --- Sleep ---

    def get_sleep(self):
        resp = requests.get(
            f"{BASE_URL}/v3/users/sleep", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_sleep_date(self, date):
        resp = requests.get(
            f"{BASE_URL}/v3/users/sleep/{date}", headers=self._headers()
        )
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()

    # --- Nightly Recharge ---

    def get_nightly_recharge(self):
        resp = requests.get(
            f"{BASE_URL}/v3/users/nightly-recharge", headers=self._headers()
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # --- Activity ---

    def get_activity(self, date):
        """Get activity summary for a specific date."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/activities/{date}",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    def get_activities(self):
        """List activity summaries (last 28 days)."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/activities",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    # --- Cardio Load ---

    def get_cardio_load(self):
        resp = requests.get(
            f"{BASE_URL}/v3/users/cardio-load", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_cardio_load_history(self):
        """Get cardio load history data (daily breakdown)."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/cardio-load/histdata/days",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    # --- Sleep-Wise ---

    def get_alertness(self):
        """Get SleepWise alertness data."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/sleep-wise/alertness",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    def get_circadian_bedtime(self):
        """Get SleepWise circadian bedtime recommendation."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/sleep-wise/circadian-bedtime",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    # --- Body Measurements ---

    def get_body_temperature(self, date):
        """Get body temperature for a specific date."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/body-temperature/{date}",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    def get_sleep_temperature(self, date):
        """Get sleep skin temperature for a specific date."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/sleep-skin-temperature/{date}",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    def get_spo2(self, date):
        """Get SpO2 data for a specific date."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/spo2/{date}",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    def get_ecg(self, date):
        """Get wrist ECG data for a specific date."""
        resp = requests.get(
            f"{BASE_URL}/v3/users/wrist-ecg/{date}",
            headers=self._headers(),
        )
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    # --- User Info ---

    def get_user_info(self):
        resp = requests.get(
            f"{BASE_URL}/v3/users/{self.user_id}", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    # --- Debug: try all exercise endpoint variations ---

    def debug_exercises(self):
        """Try multiple endpoint patterns to find exercises."""
        results = {}
        endpoints = [
            ("GET /v3/exercises", f"{BASE_URL}/v3/exercises"),
            ("GET /v3/users/exercises", f"{BASE_URL}/v3/users/exercises"),
            ("GET /v3/users/{uid}/exercises", f"{BASE_URL}/v3/users/{self.user_id}/exercises"),
            ("GET /v3/users/{uid}/training-data", f"{BASE_URL}/v3/users/{self.user_id}/training-data"),
        ]
        for label, url in endpoints:
            try:
                resp = requests.get(url, headers=self._headers())
                results[label] = {
                    "status": resp.status_code,
                    "body": resp.json() if resp.status_code == 200 else resp.text[:200],
                }
            except Exception as e:
                results[label] = {"error": str(e)}

        # Also try creating exercise transaction
        try:
            resp = requests.post(
                f"{BASE_URL}/v3/users/{self.user_id}/exercise-transactions",
                headers=self._headers(),
            )
            results["POST exercise-transactions"] = {
                "status": resp.status_code,
                "body": resp.json() if resp.status_code in (200, 201) else resp.text[:200],
            }
        except Exception as e:
            results["POST exercise-transactions"] = {"error": str(e)}

        return results

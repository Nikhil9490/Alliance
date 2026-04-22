import requests


class HCPClient:
    def __init__(self, api_key, base_url="https://api.housecallpro.com"):
        self.base = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Token {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, path, params=None):
        r = requests.get(f"{self.base}{path}", headers=self.headers, params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path, payload):
        r = requests.post(f"{self.base}{path}", headers=self.headers, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    def _put(self, path, payload):
        r = requests.put(f"{self.base}{path}", headers=self.headers, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    def _delete(self, path):
        r = requests.delete(f"{self.base}{path}", headers=self.headers, timeout=15)
        r.raise_for_status()
        return r.json() if r.content else {}

    def list_jobs(self, page=1, per_page=50):
        return self._get("/jobs", params={"page": page, "per_page": per_page})

    def get_job(self, job_id):
        return self._get(f"/jobs/{job_id}")

    def create_job(self, payload):
        return self._post("/jobs", payload)

    def update_job_schedule(self, job_id, start_time, end_time=None):
        payload = {"start_time": start_time}
        if end_time:
            payload["end_time"] = end_time
        return self._put(f"/jobs/{job_id}/schedule", payload)

    def add_job_note(self, job_id, content):
        return self._post(f"/jobs/{job_id}/notes", {"content": content})

    def delete_job(self, job_id):
        return self._delete(f"/jobs/{job_id}")

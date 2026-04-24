import time
import requests


class HCPClient:
    def __init__(self, api_key, base_url="https://api.housecallpro.com"):
        self.base = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Token {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method, path, **kwargs):
        url = f"{self.base}{path}"
        for attempt in range(3):
            r = requests.request(method, url, headers=self.headers, timeout=15, **kwargs)
            if r.status_code == 429:
                reset = r.headers.get("RateLimit-Reset")
                if reset:
                    wait = max(0, int(reset) - int(time.time())) + 1
                else:
                    wait = 60
                print(f"  HCP rate limit hit — waiting {wait}s ...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json() if r.content else {}
        raise RuntimeError(f"HCP rate limit exceeded after retries: {path}")

    def list_jobs(self, page=1, per_page=50):
        return self._request("GET", "/jobs", params={"page": page, "per_page": per_page})

    def get_job(self, job_id):
        return self._request("GET", f"/jobs/{job_id}")

    def create_job(self, payload):
        return self._request("POST", "/jobs", json=payload)

    def update_job_schedule(self, job_id, start_time, end_time=None):
        payload = {"start_time": start_time}
        if end_time:
            payload["end_time"] = end_time
        return self._request("PUT", f"/jobs/{job_id}/schedule", json=payload)

    def add_job_note(self, job_id, content):
        return self._request("POST", f"/jobs/{job_id}/notes", json={"content": content})

    def delete_job(self, job_id):
        return self._request("DELETE", f"/jobs/{job_id}")

    def list_leads(self, page=1):
        return self._request("GET", "/leads", params={"page": page})

    def list_estimates(self, page=1):
        return self._request("GET", "/estimates", params={"page": page})

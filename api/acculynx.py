import requests

class AccuLynxAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.acculynx.com/api/v2"
        self.headers = {
            "accept": "application/json",
            "authorization": f"Bearer {self.api_key}"
        }

    def get_latest_report(self, report_id):
        url = f"{self.base_url}/reports/scheduled-reports/{report_id}/runs/latest"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()
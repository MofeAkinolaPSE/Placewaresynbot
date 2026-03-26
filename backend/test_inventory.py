import requests, json
BASE = "http://localhost:8000"
r = requests.post(BASE + "/token", data={"username": "admin@placeware.com", "password": "pware1234"})
token = r.json().get("access_token")
h = {"Authorization": "Bearer " + token}

for path in ["/stock", "/inventory/summary", "/inventory/dashboard"]:
    r2 = requests.get(BASE + path, headers=h)
    body = r2.json()
    n = len(body) if isinstance(body, list) else "dict"
    first = json.dumps(body[0] if isinstance(body, list) and body else body, indent=2, default=str)[:400]
    print("=== " + path + " === status=" + str(r2.status_code) + " count=" + str(n))
    print(first)
    print()

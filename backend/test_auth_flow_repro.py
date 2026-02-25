import time
import requests
import sys

# Configuration
BASE_URL = "http://127.0.0.1:8000"
EMAIL = "admin@placeware.com" # Adjust if needed
PASSWORD = "ChangeMe123!"      # Updated from seed_admin.py

def test_auth_flow():
    print(f"Testing Auth Flow against {BASE_URL}...")
    
    # 1. Login
    print("\n[1] Attempting Login...")
    try:
        resp = requests.post(f"{BASE_URL}/token", data={"username": EMAIL, "password": PASSWORD})
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} {resp.text}")
            # Try to see if we can get a token another way or just skip
            return
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    data = resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    
    print(f"Login successful.")
    print(f"Access Token (prefix): {access_token[:20]}...")
    print(f"Refresh Token (prefix): {refresh_token[:20]}...")
    print(f"Expires In: {expires_in} seconds")

    # 2. Check protected endpoint (immediate)
    print("\n[2] Checking /sage/history with NEW access token...")
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(f"{BASE_URL}/sage/history", headers=headers) # Assuming this endpoint exists or similar
    # If /sage/history doesn't exist, try another one 
    if resp.status_code == 404:
        print("Endpoint /sage/history not found, trying /admin/users or /analytics/kpis")
        resp = requests.get(f"{BASE_URL}/analytics/kpis", headers=headers)

    if resp.status_code == 200:
        print("Protected endpoint access: SUCCESS")
    else:
        print(f"Protected endpoint access: FAILED ({resp.status_code})")
        print(resp.text)

    # 3. Refresh Token
    print("\n[3] Testing Refresh Token flow...")
    time.sleep(2) # Wait a bit
    resp = requests.post(f"{BASE_URL}/refresh", json={"refresh_token": refresh_token})
    
    if resp.status_code == 200:
        print("Refresh: SUCCESS")
        new_data = resp.json()
        new_access_token = new_data.get("access_token")
        new_expires_in = new_data.get("expires_in")
        print(f"New Access Token (prefix): {new_access_token[:20]}...")
        print(f"New Expires In: {new_expires_in}")
        
        # 4. Check protected endpoint with REFRESHED token
        print("\n[4] Checking protected endpoint with REFRESHED access token...")
        headers = {"Authorization": f"Bearer {new_access_token}"}
        resp = requests.get(f"{BASE_URL}/analytics/kpis", headers=headers)
        if resp.status_code == 200:
            print("Refreshed token access: SUCCESS")
        else:
            print(f"Refreshed token access: FAILED ({resp.status_code})")
            print(resp.text)
            
    else:
        print(f"Refresh: FAILED ({resp.status_code})")
        print(resp.text)

if __name__ == "__main__":
    test_auth_flow()

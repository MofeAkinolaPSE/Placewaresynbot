from src.auth import hash_password

def seed_admin():
    import os
    from supabase import create_client
    from dotenv import load_dotenv
    
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        print("Missing Supabase credentials")
        return

    client = create_client(url, key)
    
    email = "admin@placeware.com"
    pwd = "ChangeMe123!"
    hashed = hash_password(pwd)
    
    print(f"Checking if {email} exists...")
    existing = client.table("placeware_users").select("id").eq("email", email).execute()
    
    if existing.data:
        # Update existing admin
        user_id = existing.data[0]["id"]
        print(f"Updating existing admin {user_id}...")
        client.table("placeware_users").update({
            "hashed_password": hashed,
            "roles": ["admin"],
            "is_active": True
        }).eq("id", user_id).execute()
        print("Updated.")
    else:
        # Create new admin
        print(f"Creating new admin {email}...")
        client.table("placeware_users").insert({
            "email": email,
            "hashed_password": hashed,
            "roles": ["admin"],
            "is_active": True
        }).execute()
        print("Created.")

if __name__ == "__main__":
    seed_admin()

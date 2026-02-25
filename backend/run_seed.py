import os
import sys

# Ensure backend directory is in path
sys.path.append(os.path.dirname(__file__))

from src.seed_qna import seed

# Path to CSV
# relative from backend/: ../data/qna_pairs_with_embeddings.csv
csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/qna_pairs_with_embeddings.csv"))

if __name__ == "__main__":
    print(f"Seeding from {csv_path}...")
    try:
        if not os.path.exists(csv_path):
             print(f"Error: CSV file not found at {csv_path}")
             exit(1)
        
        count = seed(csv_path)
        print(f"Seeding finished.")
    except Exception as e:
        print(f"Seeding failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

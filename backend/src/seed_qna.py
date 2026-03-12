import csv
import os
import logging
from .db import db
from .constants import TABLE_QNA, EMBEDDING_DIM

"""
Seed Q&A pairs with embeddings from data/qna_pairs_with_embeddings.csv into db.
CSV must have headers: question,answer,embedding (JSON array of length EMBEDDING_DIM).
"""

def load_csv(path: str):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def parse_embedding(s: str):
    try:
        # expect like: [0.1, 0.2, ...]
        import json
        arr = json.loads(s)
        if not isinstance(arr, list) or len(arr) != EMBEDDING_DIM:
            return None
        return arr
    except Exception:
        return None


def seed(path: str):
    rows = []
    for r in load_csv(path):
        emb = parse_embedding(r.get('embedding', ''))
        q = (r.get('question') or '').strip()
        a = (r.get('answer') or '').strip()
        if not emb or not q or not a:
            logging.warning("Skipping invalid row")
            continue
        rows.append({
            'question': q,
            'answer': a,
            'embedding': emb,
        })
    if not rows:
        logging.info('No valid rows to seed.')
        return 0
    try:
        db.table(TABLE_QNA).insert(rows).execute()
        logging.info(f'Seeded {len(rows)} rows into {TABLE_QNA}.')
        return len(rows)
    except Exception as e:
        logging.error(f'QnA seed failed: {e}')
        return 0


if __name__ == '__main__':
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'data', 'qna_pairs_with_embeddings.csv')
    path = os.path.abspath(path)
    count = seed(path)
    print(f'Seeded rows: {count}')

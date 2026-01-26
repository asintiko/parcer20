import math
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://uzbek_parser:password@localhost:5432/receipt_parser_db")
BATCH_SIZE = 1000

def main():
    engine = create_engine(DATABASE_URL)
    updated = 0
    with engine.begin() as conn:
        while True:
            res = conn.execute(text(
                """
                WITH cte AS (
                    SELECT id, amount
                    FROM checks
                    WHERE amount < 0
                    LIMIT :limit
                )
                UPDATE checks c
                SET amount = abs(c.amount)
                FROM cte
                WHERE c.id = cte.id
                RETURNING c.id;
                """
            ), {"limit": BATCH_SIZE})
            rows = res.fetchall()
            batch_count = len(rows)
            if batch_count == 0:
                break
            updated += batch_count
            print(f"Updated batch: {batch_count}")
    print(f"Total rows updated: {updated}")


if __name__ == "__main__":
    main()

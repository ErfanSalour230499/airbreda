import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ["DATABASE_URL"])
with conn, conn.cursor() as cur:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            station_id  VARCHAR(20)  NOT NULL,
            timestamp   TIMESTAMPTZ  NOT NULL,
            component   VARCHAR(10)  NOT NULL,
            value       FLOAT,
            PRIMARY KEY (station_id, timestamp, component)
        );
    """)
    cur.execute("SELECT count(*) FROM sensor_readings;")
    print("Table ready. Rows:", cur.fetchone()[0])
conn.close()

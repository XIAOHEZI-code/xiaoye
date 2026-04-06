import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Connect to default postgres database
conn = psycopg2.connect(
    host='localhost',
    port=5432,
    user='postgres',
    password='P}5sbPS!`Cd7I-8$LvZi'
)

conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cursor = conn.cursor()

# Check if database exists
cursor.execute("SELECT 1 FROM pg_database WHERE datname='metallurgy_db';")
exists = cursor.fetchone()

if not exists:
    print("Creating metallurgy_db database...")
    cursor.execute("CREATE DATABASE metallurgy_db WITH ENCODING='UTF8';")
    print("Database created successfully!")
else:
    print("Database metallurgy_db already exists.")

cursor.close()
conn.close()

print("\\nCreating extensions...")
# Connect to new database
conn2 = psycopg2.connect(
    host='localhost',
    port=5432,
    user='postgres',
    password='P}5sbPS!`Cd7I-8$LvZi',
    database='metallurgy_db'
)
conn2.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cursor2 = conn2.cursor()

# Create UUID extension
cursor2.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
print("UUID extension created!")

cursor2.close()
conn2.close()

print("\\nDatabase configuration complete!")

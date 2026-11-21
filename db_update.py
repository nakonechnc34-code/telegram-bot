import psycopg2
import urllib.parse

password_decoded = urllib.parse.unquote('2534%22%D0%AB%D1%84%D1%8C%D1%8B%D0%B3%D1%82%D0%BF')

conn = psycopg2.connect(
    host='aws-0-eu-west-1.pooler.supabase.com',
    port=6543,
    dbname='postgres',
    user='postgres.jgzrquktfgjyuolkdogd',
    password=password_decoded,
    connect_timeout=10
)
cur = conn.cursor()

# Ищем всех пользователей с "walker" в логине
cur.execute("SELECT user_id, login, full_name, is_admin, is_super_admin, position FROM users WHERE login ILIKE '%walker%' ORDER BY login")
rows = cur.fetchall()
print(f'Found {len(rows)} users with "walker":')
for r in rows:
    print(f'  id={r[0]}, login={r[1]}, name={r[2]}, is_admin={r[3]}, is_super={r[4]}, pos={r[5]}')

# А также покажем всех пользователей
cur.execute("SELECT user_id, login, full_name, is_admin, is_super_admin FROM users ORDER BY login")
all_users = cur.fetchall()
print(f'\nAll users ({len(all_users)} total):')
for u in all_users:
    print(f'  {u[1]} — is_admin={u[3]}, is_super={u[4]}')

cur.close()
conn.close()

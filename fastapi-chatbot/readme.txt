App ---> database.py
Explaination:
1.load_dotenv()
Line-by-line: Yeh line .env file ko dhoodh kar uske andar maujood saare variables ko active kar deti hai.

2.Yahan hum ek dictionary DB_CONFIG bana rahe hain jo database se judne ka rasta batati hai.
os.getenv("VARIABLE", "default") ka matlab hai: pehle .env file me check karo, agar wahan nahi milta toh default value
(jaise port ke liye "5432" ya password ke liye "taha123") use kar lo.

3.Connection_pool = pool.SimpleConnectionPool(minconn=1, maxconn=10, **DB_CONFIG)
Yeh line bohot ahem hai. 
Yeh ek Connection Pool tayyar karti hai. Iska faida yeh hai ke jab FastAPI par ek sath 10 users aayenge, 
toh yeh line unhe alag-alag connections handle karne degi (kam se kam 1 aur zyada 
se zyada 10 connections ek sath khul sakte hain), jisse backend crash nahi hota.
-----
4. @contextmanager
def get_conn():
    """Borrow a connection from the pool, always return it when done."""
    conn = connection_pool.getconn()
    try:
        yield conn
    finally:
        connection_pool.putconn(conn)

@contextmanager: Yeh is function ko with get_conn() as conn: ki tarah istemal karne ke qabil banata hai.

conn = connection_pool.getconn(): Pool se ek zinda connection udhaar (borrow) leta hai.

try: yield conn: Yeh code chalane wale ko woh connection temporary de deta hai taake woh apni SQL query chala sake.

finally: connection_pool.putconn(conn): Jab user ka kaam khatam ho jaye (chahe query sahi chale ya usme error aaye), yeh line har haal me connection ko wapas pool me jama kar deti hai taake koi dusra user use kar sake.
----
5.
def init_tables():
    """Create chat_sessions and chat_messages tables if they don't exist yet."""

Line-by-line: init_tables naam ka function shuru hota hai jo tables banane ka zimmedar hai.

6. create_sessions = """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL DEFAULT 'New chat',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
 Yeh SQL query chat_sessions naam ka table banati hai (agar pehle se na ho). 
Isme har chat ki ek auto-incrementing id hogi, chat ka title hoga (jo shuru me 'New chat' hoga), 
aur chat kab bani (created_at) aur kab update hui (updated_at) uski timing save hogi.

7.with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(create_sessions)
            cur.execute(create_messages)
            cur.execute(create_index)
    print("chat_sessions and chat_messages tables ready.")
with get_conn() as conn:: Hamare upar banaye gaye function se database connection udhaar leta hai.

conn.autocommit = True: Isko true karne se jo bhi table hum banayenge woh fauran pakka (save) ho jayega, hume bar-bar conn.commit() nahi likhna parega.

with conn.cursor() as cur:: Ek cursor open karta hai (cursor database me query chalane wale pointer ko kehte hain).

cur.execute(...): Teeno SQL queries ko bari-bari chalata hai taake tables aur index ban jayein.

print(...): Terminal par message dikhata hai ke tables tayyar hain.


/// main.py

Import	                           Kaam
asynccontextmanager	      App start/stop pe kuch chalana (DB init)
FastAPI	                  Main app object
HTTPException	          Custom error responses
StaticFiles	              Static files (CSS/JS/images) serve karna
FileResponse	          Single file return karna
CORSMiddleware	          Frontend-backend cross-origin allow karna
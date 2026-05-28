import argparse
import datetime
import os
import sqlite3
import uuid
from pathlib import Path

from app.services.credential import encrypt_credential, load_fernet_from_env

def run_migration(db_path: str, dry_run: bool = False):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_subscriptions'")
    if not cursor.fetchone():
        print("Table 'user_subscriptions' does not exist. Nothing to migrate.")
        return

    cursor.execute("SELECT * FROM user_subscriptions")
    old_subscriptions = cursor.fetchall()
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    fernet = load_fernet_from_env()

    if not dry_run:
        # Load v2 schema
        schema_path = Path("app/migrations/m20260528_multi_channel_schema.sql")
        if not schema_path.exists():
            # fallback if running from tests etc
            schema_path = Path(__file__).parent / "m20260528_multi_channel_schema.sql"
            
        cursor.executescript(schema_path.read_text(encoding="utf-8"))

        user_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        cursor.execute("""
            INSERT INTO users (id, name, enabled, created_at, updated_at) 
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, "default", True, now, now))
        
        added_subs = set()
        
        for row in old_subscriptions:
            index_id = row["index_id"]
            base_amount = row["base_amount"]
            channel = row["notify_channel"]
            target = row["notify_target"]
            
            if (user_id, index_id) not in added_subs:
                sub_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO user_index_subscriptions (id, user_id, index_id, base_amount, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (sub_id, user_id, index_id, base_amount, True, now, now))
                added_subs.add((user_id, index_id))
            
            if channel == "telegram":
                bot_token = os.environ.get("TG_BOT_TOKEN", "dummy_token_for_migration")
                payload = {"bot_token": bot_token}
                credential_enc = encrypt_credential(fernet, payload)
                
                endpoint_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO user_notification_endpoints (id, user_id, channel_type, target, credential_enc, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, channel_type, target) DO NOTHING
                """, (endpoint_id, user_id, channel, target, credential_enc, True, now, now))

        conn.commit()
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_migration(args.db_path, args.dry_run)

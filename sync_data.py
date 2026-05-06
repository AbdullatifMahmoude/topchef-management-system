import os
import asyncio
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

os.environ["RUNTIME_MODE"] = "desktop"

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import Base, engine, AsyncSessionLocal

from app.modules.users.models import User
from app.modules.menu.models import Category, Product, Variant
from app.modules.offer.models import Offer
from app.modules.settings.models import AppSetting
from app.modules.customer.models import Customer, CustomerAddress
from app.modules.comments.models import Comment
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJBYmR1bGxhdGlmIiwidXNlcl9pZCI6MSwicm9sZSI6ImFkbWluIiwiZXhwIjoxNzc3ODA1MjA3fQ.c547L3edfsBDvej7tBKP7TvMsQChEubrM3o3XBZ0y0Y"
API_URL = "https://topchef-system.fastapicloud.dev/api/desktop/master-data"

def get_data_with_token(token):
    req = urllib.request.Request(API_URL, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTPError: {e.code} - {e.read().decode()}")
        return None

async def main():
    print("Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("Fetching data from cloud...")
    data = get_data_with_token(TOKEN)
    
    if not data:
        print("Token failed, trying to login...")
        login_url = "https://topchef-system.fastapicloud.dev/api/auth/login"
        post_data = urllib.parse.urlencode({
            "username": "Abdullatif",
            "password": "Abdullatif@1234"
        }).encode()
        req = urllib.request.Request(login_url, data=post_data, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        try:
            with urllib.request.urlopen(req) as resp:
                token_data = json.loads(resp.read().decode())
                new_token = token_data.get("access_token")
                print("Got new token!")
                data = get_data_with_token(new_token)
        except urllib.error.HTTPError as e:
            print(f"Login failed: {e.code} - {e.read().decode()}")
            return
            
    if not data:
        print("Could not fetch data.")
        return

    model_mapping = {
        "users": User,
        "categories": Category,
        "products": Product,
        "variants": Variant,
        "offers": Offer,
        "app_settings": AppSetting,
        "customers": Customer,
        "customer_addresses": CustomerAddress,
        "comments": Comment,
        "order_status_history": OrderStatusHistory,
    }

    print("Syncing to local database...")
    async with AsyncSessionLocal() as session:
        for key, model in model_mapping.items():
            records = data.get(key, [])
            print(f"Syncing {len(records)} records for {key}...")
            for record_data in records:
                valid_keys = {c.name for c in model.__table__.columns}
                filtered_data = {}
                for k, v in record_data.items():
                    if k in valid_keys:
                        # Attempt to parse ISO datetimes if needed
                        if isinstance(v, str) and len(v) >= 19 and "T" in v:
                            try:
                                # Quick check if it looks like iso format
                                v_parsed = datetime.fromisoformat(v.replace("Z", "+00:00"))
                                # Local sqlite date/datetime columns expect naive or aware depending on setup
                                # Just leave it as datetime object
                                v = v_parsed.replace(tzinfo=None)
                            except ValueError:
                                pass
                        filtered_data[k] = v
                
                obj = model(**filtered_data)
                await session.merge(obj)
        await session.commit()
    print("Sync completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())

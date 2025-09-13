# save as notion_schema_probe.py
import os, json
from notion_client import Client
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local")
NOTION_API_KEY   = os.getenv("NOTION_API_KEY")
DATABASE_ID      = os.getenv("NOTION_DATABASE_ID")
notion = Client(auth=NOTION_API_KEY)
db = notion.databases.retrieve(DATABASE_ID)
props = db["properties"]
print(json.dumps({k: v["type"] for k,v in props.items()}, indent=2))

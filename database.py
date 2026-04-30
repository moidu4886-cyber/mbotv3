import os
from motor.motor_asyncio import AsyncIOMotorClient

# Set your MongoDB URI in environment variables or replace the default below
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")

client = AsyncIOMotorClient(MONGO_URI)
db     = client["telegram_bot"]

users      = db["users"]       # stores user IDs
files      = db["files"]       # stores indexed file references
plans      = db["plans"]       # stores plan info + settings
demo_media = db["demo_media"]  # stores demo photo/video items

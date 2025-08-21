<<<<<<< HEAD
mongo_uri = "mongodb+srv://botuser:mypassword123@cluster0.7f1imlk.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(mongo_uri)
=======
from pymongo import MongoClient
>>>>>>> 8076de129ca7a8bc156c5569f2036d5487e0ed22

mongo_uri = "mongodb+srv://botuser:mypassword123@cluster0.7f1imlk.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(mongo_uri)

db = client["discord_bot"]
users_col = db["users"]
config_col = db["config"]

def get_user(user_id: str):
    return users_col.find_one({"_id": user_id})

def create_user(user_id: str, default_data: dict = None):
    if get_user(user_id) is None:
        default_data = default_data or {
            "_id": user_id,
            "points": 0,
            "items": {},
            "smart": 0,
            "streak": 0
        }
        users_col.insert_one(default_data)

def update_user(user_id: str, update_dict: dict):
    users_col.update_one({"_id": user_id}, {"$set": update_dict}, upsert=True)

def save_user_full(user_id: str, full_data: dict):
    full_data["_id"] = user_id
    users_col.replace_one({"_id": user_id}, full_data, upsert=True)

def get_jackpot():
    jackpot_doc = config_col.find_one({"_id": "jackpot"})
    return jackpot_doc["value"] if jackpot_doc else 0

def update_jackpot(amount):
    config_col.update_one({"_id": "jackpot"}, {"$inc": {"value": amount}}, upsert=True)

def set_jackpot(value):
    config_col.update_one({"_id": "jackpot"}, {"$set": {"value": value}}, upsert=True)

def create_leaderboard(key="points"):
    sorted_users = users_col.find({key: {"$exists": True}}).sort(key, -1)
    from main import format_currency, coin
    leaderboard = "\n".join(
        f"> <@{user['_id']}>: {format_currency(user.get(key, 0))} {coin}" for user in sorted_users
    )
    return leaderboard or "Không có dữ liệu."

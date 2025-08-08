from pymongo import MongoClient

mongo_uri = "mongodb+srv://botuser:mypassword123@cluster0.7f1imlk.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(mongo_uri)

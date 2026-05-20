# core/database.py
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "resume_db")

_client = None
_db = None

def init_db():
    """
    Initialize and return DB object. Raises RuntimeError if connection fails.
    """
    global _client, _db
    if _db is not None:
        return _db
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI not set in .env")
    try:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        _client.admin.command("ping")
        _db = _client[MONGO_DBNAME]
        return _db
    except PyMongoError as e:
        raise RuntimeError(f"Could not connect to MongoDB Atlas: {e}")

def get_db():
    """Return DB object, initializing if necessary."""
    global _db
    if _db is None:
        return init_db()
    return _db

# Try to initialize at import if env configured (silently ignore failures here)
try:
    if MONGO_URI:
        _db = init_db()
except Exception:
    _db = None

# convenience export
db = _db






























# # core/database.py
# """
# Strict MongoDB Atlas connector.

# This module **requires** MONGO_URI and MONGO_DBNAME set in .env.
# On import it attempts a ping; if it cannot reach the DB it raises RuntimeError
# so the app fails fast and you can fix the config (Atlas only mode).
# """

# import os
# import logging
# from dotenv import load_dotenv
# from pymongo import MongoClient
# from pymongo.errors import ServerSelectionTimeoutError, PyMongoError

# load_dotenv()

# MONGO_URI = os.getenv("MONGO_URI")
# MONGO_DBNAME = os.getenv("MONGO_DBNAME", "resume_db")

# if not MONGO_URI:
#     raise RuntimeError(
#         "MONGO_URI not set. Set MONGO_URI in .env to your MongoDB Atlas connection string.\n"
#         "Example:\n"
#         'MONGO_URI=\"mongodb+srv://<user>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority\"\n'
#     )

# # Keep reasonable timeouts for quick failure
# _CLIENT = None

# def get_client():
#     global _CLIENT
#     if _CLIENT is None:
#         try:
#             _CLIENT = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
#             _CLIENT.admin.command("ping")
#         except ServerSelectionTimeoutError as e:
#             raise RuntimeError(f"Could not connect to MongoDB at MONGO_URI. Ping failed: {e}")
#         except PyMongoError as e:
#             raise RuntimeError(f"Could not connect to MongoDB: {e}")
#     return _CLIENT

# def get_db():
#     client = get_client()
#     return client[MONGO_DBNAME]

# def init_db():
#     """
#     Initialize DB and create basic indexes. Raises on failure.
#     Returns the db object.
#     """
#     db = get_db()
#     try:
#         db.resumeFetchedData.create_index("UserId")
#         db.JOBS.create_index("Job_Profile")
#         db.USERS.create_index("Email")
#     except Exception as e:
#         # index creation shouldn't stop the app but we log it
#         logging.warning("Index creation warning: %s", e)
#     return db

# # Export db and client for compatibility
# mongo = get_client()
# db = get_db()

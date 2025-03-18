import os

class Config:
    DB_USERNAME = "root"  
    DB_PASSWORD = "Lotty%40488"  
    DB_HOST = "localhost"
    DB_NAME = "Penzi_db"

    SQLALCHEMY_DATABASE_URI = f"mysql+mysqlconnector://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.urandom(24)

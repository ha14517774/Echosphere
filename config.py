import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'echosphere_secret_key')
    MONGO_URI = os.environ['MONGO_URI']

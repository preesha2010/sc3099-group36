import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(
    DATABASE_URL,
    pool_size=10,          # Maintains 10 persistent connections
    max_overflow=20,      # Can create 20 additional temporary connections
    pool_timeout=30,      # Wait 30 seconds for available connection
    pool_recycle=3600,    # Recycle connections after 1 hour
    pool_pre_ping=True    # Test connection before using
)

"""With connection pooling:
Get existing connection from pool (~1ms)
Execute query (~5–20ms)
Return connection to pool (~1ms)
Total: 7–22ms per request (10–20x faster!)
"""
                           
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

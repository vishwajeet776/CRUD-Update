# database.py - MongoDB Connection (with GridFS for file storage)
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient
from gridfs import GridFS
import os
from dotenv import load_dotenv

load_dotenv()

# MongoDB Connection String
MONGODB_URL = os.getenv(
    "MONGODB_URL",
    "mongodb://localhost:27017"
)
DATABASE_NAME = os.getenv("DATABASE_NAME", "pod_1")

# System Limits
FREE_PLAN_RESUME_LIMIT = 100  # Max resumes per workflow (increased from 10)
MAX_FILE_SIZE_MB = 5  # Max 5MB per file

# Synchronous MongoDB client (for non-async operations)
client = MongoClient(MONGODB_URL)
db = client[DATABASE_NAME]

# GridFS for file storage (files stored in MongoDB, no Azure needed for small files)
fs = GridFS(db)

# Async MongoDB client (for async operations)
async_client = AsyncIOMotorClient(MONGODB_URL)
async_db = async_client[DATABASE_NAME]

# Collection names
RESUME_COLLECTION = "resume"
JOB_DESCRIPTION_COLLECTION = "JobDescription"
RESUME_RESULT_COLLECTION = "resume_result"
USER_COLLECTION = "users"
AUDIT_LOG_COLLECTION = "audit_logs"
FILE_METADATA_COLLECTION = "files"  # Stores file metadata (actual files in GridFS)
WORKFLOW_EXECUTION_COLLECTION = "workflow_executions"  # Stores workflow execution records

# Note: With 10 resume limit and 5MB max per file, total storage = 50MB max per user
# GridFS is perfect for this use case (no external storage needed)

def get_db():
    """Dependency for getting database connection"""
    try:
        yield db
    finally:
        pass

def get_async_db():
    """Dependency for getting async database connection"""
    try:
        yield async_db
    finally:
        pass

def init_db():
    """Initialize database with indexes"""
    print("Initializing database and creating indexes...")
    
    # Resume collection indexes
    db[RESUME_COLLECTION].create_index("filename")
    db[RESUME_COLLECTION].create_index([("uploadedAt", -1)])
    db[RESUME_COLLECTION].create_index([("text", "text")])  # Full-text search
    
    # JobDescription collection indexes
    db[JOB_DESCRIPTION_COLLECTION].create_index("designation")
    db[JOB_DESCRIPTION_COLLECTION].create_index("status")
    db[JOB_DESCRIPTION_COLLECTION].create_index([("description", "text")])  # Full-text search
    
    # resume_result collection indexes
    db[RESUME_RESULT_COLLECTION].create_index([("resume_id", 1), ("jd_id", 1)], unique=True)
    db[RESUME_RESULT_COLLECTION].create_index([("match_score", -1)])
    db[RESUME_RESULT_COLLECTION].create_index("fit_category")
    db[RESUME_RESULT_COLLECTION].create_index([("timestamp", -1)])
    db[RESUME_RESULT_COLLECTION].create_index([("jd_id", 1), ("match_score", -1)])
    db[RESUME_RESULT_COLLECTION].create_index("workflow_id")  # NEW: For workflow lookups
    
    # User collection indexes
    db[USER_COLLECTION].create_index("email", unique=True)
    db[USER_COLLECTION].create_index("role")
    
    # Audit log indexes
    db[AUDIT_LOG_COLLECTION].create_index([("userId", 1), ("timestamp", -1)])
    db[AUDIT_LOG_COLLECTION].create_index([("action", 1), ("timestamp", -1)])
    db[AUDIT_LOG_COLLECTION].create_index("resourceId")
    
    # File metadata indexes
    db[FILE_METADATA_COLLECTION].create_index("resumeId")
    db[FILE_METADATA_COLLECTION].create_index("checksum")
    db[FILE_METADATA_COLLECTION].create_index("security.virusScanStatus")
    
    # Workflow execution indexes
    db[WORKFLOW_EXECUTION_COLLECTION].create_index("workflow_id", unique=True)
    db[WORKFLOW_EXECUTION_COLLECTION].create_index([("started_by", 1), ("started_at", -1)])
    db[WORKFLOW_EXECUTION_COLLECTION].create_index("jd_id")
    db[WORKFLOW_EXECUTION_COLLECTION].create_index("status")
    db[WORKFLOW_EXECUTION_COLLECTION].create_index([("started_at", -1)])
    
    print("Database initialization complete!")

def test_connection():
    """Test MongoDB connection"""
    try:
        client.admin.command('ping')
        print("✅ MongoDB connection successful!")
        print(f"📊 Database: {DATABASE_NAME}")
        print(f"🔗 URL: {MONGODB_URL}")
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False


# routers/resumes.py - Resume Management Endpoints
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database
from typing import List, Optional

import schemas
import crud
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/resumes", tags=["Resumes"])

@router.post("/", response_model=schemas.ResumeResponse, status_code=201)
def create_resume(
    resume_data: schemas.ResumeCreate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Create a new resume entry
    
    - **filename**: Original filename
    - **text**: Full parsed resume text
    - **fileSize**: File size in bytes
    - **source**: Upload source (direct, LinkedIn, Indeed, Naukri.com)
    """
    # Add uploaded by user
    resume_dict = resume_data.model_dump()
    resume_dict["uploadedBy"] = crud.object_id(current_user["_id"])
    
    # Create resume
    resume_id = crud.create_resume(db, resume_dict)
    
    # Log action
    crud.create_audit_log(db, {
        "userId": crud.object_id(current_user["_id"]),
        "action": "upload_resume",
        "resourceType": "resume",
        "resourceId": resume_id,
        "ipAddress": "0.0.0.0",
        "userAgent": "Unknown",
        "success": True
    })
    
    # Get created resume
    resume = crud.get_resume_by_id(db, resume_id)
    return resume

@router.get("/", response_model=List[schemas.ResumeListResponse])
def list_resumes(
    skip: int = Query(0, ge=0),
    limit: int = Query(130, ge=1, le=130),
    source: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    List all resumes with pagination
    
    - **skip**: Number of records to skip
    - **limit**: Maximum records to return (max 100)
    - **source**: Filter by source (optional)
    """
    resumes = crud.get_all_resumes(db, skip, limit, source)
    
    # Add text preview
    for resume in resumes:
        resume["text_preview"] = resume.get("text", "")[:200]
    
    return resumes

@router.get("/{resume_id}", response_model=schemas.ResumeResponse)
def get_resume(
    resume_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Get resume by ID"""
    resume = crud.get_resume_by_id(db, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Log view action
    crud.create_audit_log(db, {
        "userId": crud.object_id(current_user["_id"]),
        "action": "view_resume",
        "resourceType": "resume",
        "resourceId": resume_id,
        "ipAddress": "0.0.0.0",
        "userAgent": "Unknown",
        "success": True
    })
    
    return resume

@router.put("/{resume_id}", response_model=schemas.MessageResponse)
def update_resume(
    resume_id: str,
    resume_update: schemas.ResumeUpdate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Update resume"""
    # Check if resume exists
    existing_resume = crud.get_resume_by_id(db, resume_id)
    if not existing_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Update only provided fields
    update_data = resume_update.model_dump(exclude_unset=True)
    
    success = crud.update_resume(db, resume_id, update_data)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update resume")
    
    return {
        "success": True,
        "message": "Resume updated successfully"
    }

@router.delete("/{resume_id}", response_model=schemas.MessageResponse)
def delete_resume(
    resume_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Delete resume"""
    # Check if resume exists
    existing_resume = crud.get_resume_by_id(db, resume_id)
    if not existing_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Delete resume
    success = crud.delete_resume(db, resume_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete resume")
    
    # Log deletion
    crud.create_audit_log(db, {
        "userId": crud.object_id(current_user["_id"]),
        "action": "delete_resume",
        "resourceType": "resume",
        "resourceId": resume_id,
        "ipAddress": "0.0.0.0",
        "userAgent": "Unknown",
        "success": True
    })
    
    return {
        "success": True,
        "message": "Resume deleted successfully"
    }

@router.get("/search/text")
def search_resumes(
    q: str = Query(..., min_length=3, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Full-text search in resumes
    
    - **q**: Search query (minimum 3 characters)
    - **limit**: Maximum results (max 50)
    """
    results = crud.search_resumes(db, q, limit)
    
    # Add text preview
    for resume in results:
        resume["text_preview"] = resume.get("text", "")[:200]
    
    return {
        "query": q,
        "count": len(results),
        "results": results
    }

@router.get("/stats/count")
def get_resume_count(
    source: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Get total resume count, optionally filtered by source"""
    count = crud.count_resumes(db, source)
    return {
        "total": count,
        "source": source
    }


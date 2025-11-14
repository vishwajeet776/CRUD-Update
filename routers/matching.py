# routers/matching.py - Resume-JD Matching Endpoints
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pymongo.database import Database
from typing import List, Optional
from datetime import datetime
import httpx
import json

import schemas
import crud
from database import get_db
from routers.auth import get_current_user
from config import AI_AGENT_URL, AI_AGENT_TIMEOUT, AI_AGENT_ENABLED

router = APIRouter(prefix="/matching", tags=["Matching"])

# TODO: Implement actual AI matching logic
def mock_ai_matching(resume_text: str, jd_text: str) -> dict:
    """
    Mock AI matching function
    
    In production, this should call the AI agents:
    1. JD & Resume Extractor Agent
    2. JD Reader Agent
    3. Resume Reader Agent
    4. HR Comparator Agent
    """
    # This is mock data - replace with actual AI implementation
    return {
        "match_score": 85.5,
        "fit_category": "Excellent Match",
        "jd_extracted": {
            "position": "Software Engineer",
            "experience_required": {
                "min_years": 3,
                "max_years": 5,
                "type": "Software Development"
            },
            "required_skills": ["Python", "FastAPI", "MongoDB"],
            "preferred_skills": ["AWS", "Docker"],
            "education": "Bachelor's in Computer Science",
            "location": "Remote",
            "job_type": "Full-time",
            "responsibilities": ["Develop APIs", "Write tests", "Code reviews"]
        },
        "resume_extracted": {
            "candidate_name": "John Doe",
            "email": "john@example.com",
            "phone": "+1-234-567-8900",
            "location": "San Francisco, CA",
            "current_position": "Senior Software Engineer",
            "total_experience": 5.0,
            "relevant_experience": 4.5,
            "skills_matched": ["Python", "FastAPI", "MongoDB", "AWS"],
            "skills_missing": [],
            "education": {
                "degree": "B.S. Computer Science",
                "institution": "Stanford University",
                "year": 2018,
                "grade": "3.8/4.0"
            },
            "certifications": ["AWS Certified"],
            "work_history": [
                {
                    "title": "Senior Software Engineer",
                    "company": "Tech Corp",
                    "duration": "3 years",
                    "technologies": ["Python", "FastAPI", "AWS"]
                }
            ],
            "key_achievements": ["Led team of 5 developers", "Reduced API latency by 40%"]
        },
        "match_breakdown": {
            "skills_match": 95.0,
            "experience_match": 90.0,
            "education_match": 100.0,
            "location_match": 85.0,
            "cultural_fit": 80.0,
            "overall_compatibility": 85.5
        },
        "selection_reason": "HIGHLY RECOMMENDED\n\nSTRENGTHS:\n✅ Strong technical skills match\n✅ Exceeds experience requirements\n✅ Relevant education background\n\nThis candidate is an excellent fit for the position.",
        "confidence_score": 92.0,
        "processing_duration_ms": 2500
    }

async def call_ai_agent_batch(workflow_id: str, jd_text: str, resumes: List[dict]) -> dict:
    """
    Call AI Agent container to process multiple resumes
    
    Args:
        workflow_id: Workflow ID (e.g. "WF-1731427200000")
        jd_text: Full job description text
        resumes: List of [{resume_id, resume_text}, ...]
    
    Returns:
        {workflow_id, results: [{resume_id, match_score, ...}]}
    """
    if not AI_AGENT_ENABLED:
        print("⚠️ AI Agent disabled, using mock data")
        # Fallback to mock if agent is disabled
        return {
            "workflow_id": workflow_id,
            "results": [
                {
                    "resume_id": r["resume_id"],
                    **mock_ai_matching(r["resume_text"], jd_text)
                }
                for r in resumes
            ]
        }
    
    try:
        print(f"🤖 Calling AI Agent at {AI_AGENT_URL}/compare-batch")
        print(f"📊 Sending {len(resumes)} resumes to AI Agent")
        
        # Create timeout with separate connect, read, write, and pool timeouts
        # For large responses, we need a longer read timeout
        timeout_config = httpx.Timeout(
            connect=30.0,  # 30 seconds to establish connection
            read=AI_AGENT_TIMEOUT,  # Full timeout for reading response
            write=60.0,  # 60 seconds to write request
            pool=30.0  # 30 seconds to get connection from pool
        )
        
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            response = await client.post(
                f"{AI_AGENT_URL}/compare-batch",
                json={
                    "workflow_id": workflow_id,
                    "jd_text": jd_text,
                    "resumes": resumes
                }
            )
            
            if response.status_code == 200:
                print(f"✅ AI Agent responded successfully (Status: {response.status_code})")
                print(f"📦 Response size: {len(response.content)} bytes")
                
                # Parse JSON response (this can take time for large responses)
                try:
                    result = response.json()
                    print(f"✅ Successfully parsed JSON response with {len(result.get('results', []))} results")
                    return result
                except Exception as json_error:
                    error_msg = f"Failed to parse AI Agent JSON response: {str(json_error)}"
                    print(f"❌ {error_msg}")
                    print(f"📄 Response preview: {response.text[:500]}")
                    raise Exception(error_msg)
            else:
                error_msg = f"AI Agent returned error: {response.status_code} - {response.text[:500]}"
                print(f"❌ {error_msg}")
                raise Exception(error_msg)
    
    except httpx.TimeoutException:
        error_msg = "AI Agent timeout - processing took too long"
        print(f"❌ {error_msg}")
        raise Exception(error_msg)
    
    except httpx.ConnectError:
        error_msg = f"Cannot connect to AI Agent at {AI_AGENT_URL} - is it running?"
        print(f"❌ {error_msg}")
        raise Exception(error_msg)
    
    except Exception as e:
        error_msg = f"AI Agent error: {str(e)}"
        print(f"❌ {error_msg}")
        raise Exception(error_msg)

@router.post("/match", response_model=schemas.ResumeResultResponse)
def match_resume_with_jd(
    match_request: schemas.MatchingRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Match a single resume against a job description
    
    - **resume_id**: Resume ObjectId
    - **jd_id**: Job Description custom ID
    - **force_reprocess**: Force reprocessing even if result exists
    """
    # Get resume and JD
    resume = crud.get_resume_by_id(db, match_request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    jd = crud.get_jd_by_id(db, match_request.jd_id)
    if not jd:
        raise HTTPException(status_code=404, detail="Job Description not found")
    
    # Check if result already exists
    existing_result = crud.get_result_by_resume_jd(
        db, match_request.resume_id, match_request.jd_id
    )
    
    if existing_result and not match_request.force_reprocess:
        return existing_result
    
    # Perform AI matching
    start_time = datetime.utcnow()
    ai_result = mock_ai_matching(resume.get("text", ""), jd.get("description", ""))
    processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
    
    # Create result document
    result_doc = {
        "resume_id": crud.object_id(match_request.resume_id),
        "jd_id": match_request.jd_id,
        "match_score": ai_result["match_score"],
        "fit_category": ai_result["fit_category"],
        "jd_extracted": ai_result["jd_extracted"],
        "resume_extracted": ai_result["resume_extracted"],
        "match_breakdown": ai_result["match_breakdown"],
        "selection_reason": ai_result["selection_reason"],
        "agent_version": "v1.0.0",
        "processing_duration_ms": int(processing_time),
        "confidence_score": ai_result.get("confidence_score")
    }
    
    # Save or update result
    if existing_result:
        crud.delete_result(db, existing_result["_id"])
    
    result_id = crud.create_resume_result(db, result_doc)
    
    # Log action
    crud.create_audit_log(db, {
        "userId": crud.object_id(current_user["_id"]),
        "action": "run_matching",
        "resourceType": "resume_result",
        "resourceId": result_id,
        "ipAddress": "0.0.0.0",
        "userAgent": "Unknown",
        "success": True
    })
    
    # Get created result
    result = crud.get_result_by_id(db, result_id)
    return result

@router.post("/batch", response_model=schemas.MessageResponse)
async def batch_match_resumes(  # ✅ Made async!
    batch_request: schemas.MatchingBatchRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Match multiple resumes against a job description
    NOW WITH REAL AI AGENT INTEGRATION!
    """
    from database import FREE_PLAN_RESUME_LIMIT
    
    # Get JD
    jd = crud.get_jd_by_id(db, batch_request.jd_id)
    if not jd:
        raise HTTPException(status_code=404, detail="Job Description not found")
    
    # Get resumes to match
    if batch_request.resume_ids:
        resume_ids = batch_request.resume_ids
    else:
        all_resumes = crud.get_all_resumes(db, 0, 1000)
        resume_ids = [r["_id"] for r in all_resumes]
    
    # Enforce 10-resume limit
    if len(resume_ids) > FREE_PLAN_RESUME_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {FREE_PLAN_RESUME_LIMIT} resumes allowed per workflow."
        )
    
    # Generate unique workflow ID
    workflow_id = f"WF-{int(datetime.utcnow().timestamp() * 1000)}"
    
    # Create workflow execution record
    workflow_doc = {
        "workflow_id": workflow_id,
        "jd_id": batch_request.jd_id,
        "jd_title": jd.get("designation", "Job Description"),
        "status": "in_progress",
        "started_by": crud.object_id(current_user["_id"]),
        "started_at": datetime.utcnow(),
        "resume_ids": [crud.object_id(rid) for rid in resume_ids],
        "total_resumes": len(resume_ids),
        "processed_resumes": 0,
        "agents": [
            {
                "agent_id": "jd-reader",
                "name": "JD Reader Agent",
                "status": "completed",
                "is_ai_agent": False
            },
            {
                "agent_id": "resume-reader",
                "name": "Resume Reader Agent",
                "status": "completed",
                "is_ai_agent": False
            },
            {
                "agent_id": "hr-comparator",
                "name": "HR Comparator Agent",
                "status": "in_progress",
                "is_ai_agent": True,
                "started_at": datetime.utcnow()
            }
        ],
        "progress": {
            "completed_agents": 2,
            "total_agents": 3,
            "percentage": 66
        },
        "metrics": {
            "total_candidates": len(resume_ids),
            "processing_time_ms": 0,
            "match_rate": 0,
            "top_matches": 0
        }
    }
    
    workflow_db_id = crud.create_workflow_execution(db, workflow_doc)
    
    # ============================================
    # 🚀 CALL AI AGENT (NEW CODE)
    # ============================================
    try:
        # Prepare resumes for AI Agent
        resumes_data = []
        for resume_id in resume_ids:
            resume = crud.get_resume_by_id(db, resume_id)
            if resume:
                resumes_data.append({
                    "resume_id": resume_id,
                    "resume_text": resume.get("text", "")
                })
        
        # Call AI Agent
        print(f"🤖 Calling AI Agent for workflow: {workflow_id}")
        ai_results = await call_ai_agent_batch(
            workflow_id=workflow_id,
            jd_text=jd.get("description", ""),
            resumes=resumes_data
        )
        
        print(f"✅ AI Agent completed for workflow: {workflow_id}")
        print(f"📊 Received {len(ai_results.get('results', []))} results from AI Agent")
        
        # Save results to database
        processed_count = 0
        failed_count = 0
        total_results = len(ai_results.get("results", []))
        
        for idx, result in enumerate(ai_results.get("results", []), 1):
            try:
                print(f"💾 [{idx}/{total_results}] Saving result for resume: {result.get('resume_id', 'unknown')}")
                result_doc = {
                    "resume_id": crud.object_id(result["resume_id"]),
                    "jd_id": batch_request.jd_id,
                    "workflow_id": workflow_id,  # Added workflow_id
                    "match_score": result.get("match_score", 0),
                    "fit_category": result.get("fit_category", "Unknown"),
                    "jd_extracted": result.get("jd_extracted", {}),
                    "resume_extracted": result.get("resume_extracted", {}),
                    "match_breakdown": result.get("match_breakdown", {}),
                    "selection_reason": result.get("selection_reason", ""),
                    "agent_version": "v1.0.0",
                    "processing_duration_ms": ai_results.get("processing_time_ms", 0),
                    "confidence_score": result.get("confidence_score", "Unknown")
                }
                
                # Check if result already exists
                existing_result = crud.get_result_by_resume_jd(
                    db, result["resume_id"], batch_request.jd_id
                )
                
                if existing_result:
                    print(f"🔄 Deleting existing result: {existing_result['_id']}")
                    crud.delete_result(db, existing_result["_id"])
                
                result_id = crud.create_resume_result(db, result_doc)
                print(f"✅ [{idx}/{total_results}] Saved result with ID: {result_id}")
                processed_count += 1
            except Exception as save_error:
                failed_count += 1
                print(f"❌ [{idx}/{total_results}] Error saving result for resume {result.get('resume_id', 'unknown')}: {save_error}")
                import traceback
                traceback.print_exc()
                # Continue with next resume even if this one fails
        
        print(f"📊 Save summary: {processed_count} succeeded, {failed_count} failed out of {total_results} total")
        
        # Update workflow status to completed
        crud.update_workflow_status(db, workflow_id, {
            "status": "completed",
            "completed_at": datetime.utcnow(),
            "processed_resumes": processed_count,
            "agents": [
                {
                    "agent_id": "jd-reader",
                    "name": "JD Reader Agent",
                    "status": "completed",
                    "is_ai_agent": False
                },
                {
                    "agent_id": "resume-reader",
                    "name": "Resume Reader Agent",
                    "status": "completed",
                    "is_ai_agent": False
                },
                {
                    "agent_id": "hr-comparator",
                    "name": "HR Comparator Agent",
                    "status": "completed",
                    "is_ai_agent": True,
                    "completed_at": datetime.utcnow(),
                    "duration_ms": ai_results.get("processing_time_ms", 0)
                }
            ],
            "progress": {
                "completed_agents": 3,
                "total_agents": 3,
                "percentage": 100
            },
            "metrics": {
                "total_candidates": len(resume_ids),
                "processing_time_ms": ai_results.get("processing_time_ms", 0),
                "match_rate": 100,
                "top_matches": processed_count
            }
        })
        
        print(f"✅ Workflow completed: {workflow_id}")
        
        # Log action
        crud.create_audit_log(db, {
            "userId": crud.object_id(current_user["_id"]),
            "action": "run_matching",
            "resourceType": "workflow_execution",
            "resourceId": workflow_id,
            "ipAddress": "0.0.0.0",
            "userAgent": "Unknown",
            "success": True
        })
        
        return {
            "success": True,
            "message": f"AI processing completed for {processed_count} resumes",
            "data": {
                "workflow_id": workflow_id,
                "jd_id": batch_request.jd_id,
                "total_resumes": len(resume_ids),
                "processed_resumes": processed_count,
                "status": "completed"
            }
        }
    
    except Exception as e:
        # Update workflow status to failed
        crud.update_workflow_status(db, workflow_id, {
            "status": "failed",
            "error": str(e),
            "agents": [
                {
                    "agent_id": "jd-reader",
                    "name": "JD Reader Agent",
                    "status": "completed",
                    "is_ai_agent": False
                },
                {
                    "agent_id": "resume-reader",
                    "name": "Resume Reader Agent",
                    "status": "completed",
                    "is_ai_agent": False
                },
                {
                    "agent_id": "hr-comparator",
                    "name": "HR Comparator Agent",
                    "status": "failed",
                    "is_ai_agent": True,
                    "error": str(e)
                }
            ]
        })
        
        print(f"❌ Workflow failed: {workflow_id} - {str(e)}")
        
        raise HTTPException(
            status_code=500,
            detail=f"AI Agent error: {str(e)}"
        )

@router.get("/results/{jd_id}", response_model=List[schemas.ResumeResultListResponse])
def get_jd_results(
    jd_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    min_score: Optional[float] = Query(None, ge=0, le=100),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Get all matching results for a job description
    
    - **jd_id**: Job Description custom ID
    - **skip**: Number of records to skip
    - **limit**: Maximum records to return
    - **min_score**: Minimum match score filter
    """
    results = crud.get_results_by_jd(db, jd_id, skip, limit, min_score)
    
    # Format response
    response = []
    for result in results:
        response.append({
            "id": result["_id"],
            "resume_id": str(result["resume_id"]),
            "jd_id": result["jd_id"],
            "candidate_name": result.get("resume_extracted", {}).get("candidate_name", "Unknown"),
            "match_score": result["match_score"],
            "fit_category": result["fit_category"],
            "timestamp": result["timestamp"]
        })
    
    return response

@router.get("/top-matches/{jd_id}", response_model=schemas.TopMatchesResponse)
def get_top_matches(
    jd_id: str,
    limit: int = Query(100, ge=1, le=500),  # Increased max limit to 500 to support large batches
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Get top matching candidates for a job description
    
    - **jd_id**: Job Description custom ID
    - **limit**: Number of top matches to return (max 500, default 100)
    """
    # Get JD
    jd = crud.get_jd_by_id(db, jd_id)
    if not jd:
        raise HTTPException(status_code=404, detail="Job Description not found")
    
    # Get top matches
    top_results = crud.get_top_matches(db, jd_id, limit)
    
    # Helper function to parse experience strings like "4+", "3-5", "5.5"
    def parse_experience(exp_value):
        if not exp_value:
            return 0.0
        exp_str = str(exp_value).strip()
        # Remove common suffixes
        exp_str = exp_str.replace('+', '').replace(' years', '').replace('yrs', '')
        # Take first number if range (e.g., "3-5" -> "3")
        if '-' in exp_str:
            exp_str = exp_str.split('-')[0]
        try:
            return float(exp_str)
        except (ValueError, AttributeError):
            return 0.0
    
    # Helper function to parse resume_extracted (might be JSON string or dict)
    def parse_resume_data(resume_extracted):
        if isinstance(resume_extracted, dict):
            return resume_extracted
        if isinstance(resume_extracted, str):
            try:
                # Remove markdown code blocks
                cleaned = resume_extracted.replace('```json', '').replace('```', '').strip()
                return json.loads(cleaned)
            except Exception as e:
                print(f"⚠️ Error parsing resume_extracted: {e}")
                return {}
        return {}
    
    # Helper function to flatten skills (convert dict to list)
    def flatten_skills(skills):
        """Convert nested skills dict to flat list of strings"""
        if isinstance(skills, list):
            # Check if list contains dicts (nested structure)
            if skills and isinstance(skills[0], dict):
                # Flatten all dicts in the list
                flat_skills = []
                for item in skills:
                    if isinstance(item, dict):
                        for category, skill_list in item.items():
                            if isinstance(skill_list, list):
                                flat_skills.extend(skill_list)
                            elif isinstance(skill_list, str):
                                flat_skills.append(skill_list)
                    elif isinstance(item, str):
                        flat_skills.append(item)
                return flat_skills
            # Already a flat list of strings
            return skills
        if isinstance(skills, dict):
            # Flatten all values from the dict
            flat_skills = []
            for category, skill_list in skills.items():
                if isinstance(skill_list, list):
                    flat_skills.extend(skill_list)
                elif isinstance(skill_list, str):
                    flat_skills.append(skill_list)
            return flat_skills
        return []
    
    # Get workflow IDs for all resumes (batch lookup for efficiency)
    from database import WORKFLOW_EXECUTION_COLLECTION
    workflow_map = {}
    if top_results:
        resume_ids = [r["resume_id"] for r in top_results]
        print(f"🔍 Looking up workflows for {len(resume_ids)} resumes")
        
        workflows = list(db[WORKFLOW_EXECUTION_COLLECTION].find(
            {"resume_ids": {"$in": resume_ids}},
            {"workflow_id": 1, "resume_ids": 1}
        ).sort("started_at", -1))
        
        print(f"🔍 Found {len(workflows)} workflows")
        
        for workflow in workflows:
            wf_id = workflow.get("workflow_id")
            print(f"   Workflow: {wf_id} with {len(workflow.get('resume_ids', []))} resumes")
            for resume_id in workflow.get("resume_ids", []):
                if resume_id not in workflow_map:
                    workflow_map[resume_id] = wf_id
        
        print(f"🔍 Workflow map created for {len(workflow_map)} resumes")
    
    # Format response with full candidate details
    top_matches = []
    for result in top_results:
        resume_data = parse_resume_data(result.get("resume_extracted", {}))
        match_breakdown = result.get("match_breakdown", {})
        
        print(f"📊 Processing candidate: {resume_data.get('Name', 'Unknown')}")
        print(f"   Total_Experience_Years: {resume_data.get('Total_Experience_Years')}")
        print(f"   Career_History: {len(resume_data.get('Career_History', []))} entries")
        print(f"   Skill_Score: {match_breakdown.get('Skill_Score')}")
        
        # Debug: Check skills format
        tech_skills = resume_data.get("Technical_Skills")
        print(f"   Technical_Skills type: {type(tech_skills)}")
        if isinstance(tech_skills, dict):
            print(f"   ⚠️ Skills is dict, will flatten: {list(tech_skills.keys())}")
        
        # Extract current position from Career_History if available
        current_position = resume_data.get("Current_Position") or resume_data.get("current_position")
        if not current_position and resume_data.get("Career_History"):
            career = resume_data.get("Career_History", [])
            if isinstance(career, list) and len(career) > 0:
                # Get most recent role
                latest_job = career[-1] if career else {}
                current_position = latest_job.get("Role") or latest_job.get("Job_Title")
        
        # Get workflow_id from map
        workflow_id = workflow_map.get(result["resume_id"])
        print(f"   Workflow ID: {workflow_id}")
        
        # Handle email - might be string or list
        email_value = resume_data.get("Email") or resume_data.get("email") or ""
        if isinstance(email_value, list):
            # If email is a list, take the first one or join with comma
            email_value = email_value[0] if email_value else ""
        
        # Handle phone - might be string or list
        phone_value = resume_data.get("Mobile") or resume_data.get("phone") or ""
        if isinstance(phone_value, list):
            # If phone is a list, take the first one
            phone_value = phone_value[0] if phone_value else ""
        
        top_matches.append({
            "id": result["_id"],
            "resume_id": str(result["resume_id"]),
            "jd_id": result["jd_id"],
            "workflow_id": workflow_id,
            "candidate_name": resume_data.get("Name") or resume_data.get("candidate_name") or "Unknown",
            "current_position": current_position or "Unknown Position",
            "email": email_value if isinstance(email_value, str) else "",
            "phone": phone_value if isinstance(phone_value, str) else "",
            "location": resume_data.get("Current_Location") or resume_data.get("location") or "",
            "total_experience": parse_experience(resume_data.get("Total_Experience_Years") or resume_data.get("total_experience")),
            "skills_matched": flatten_skills(resume_data.get("Technical_Skills") or resume_data.get("skills_matched") or []),
            "match_score": result["match_score"],
            "fit_category": result["fit_category"],
            "match_breakdown": {
                "skills_match": int(match_breakdown.get("Skill_Score") or match_breakdown.get("skills_match") or 0),
                "experience_match": int(match_breakdown.get("Experience_Score") or match_breakdown.get("experience_match") or 0),
                "location_match": int(match_breakdown.get("Location_Score") or match_breakdown.get("location_match") or 0),
                "stability": int(result.get("stability_score") or match_breakdown.get("cultural_fit") or 0)
            },
            "timestamp": result["timestamp"]
        })
    
    return {
        "jd_id": jd_id,
        "jd_designation": jd.get("designation", "Unknown"),
        "total_candidates": len(top_matches),
        "top_matches": top_matches
    }

@router.get("/result/{result_id}", response_model=schemas.ResumeResultResponse)
def get_result_by_id(
    result_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Get detailed matching result by ID"""
    result = crud.get_result_by_id(db, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    
    return result

@router.delete("/result/{result_id}", response_model=schemas.MessageResponse)
def delete_result(
    result_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Delete matching result"""
    success = crud.delete_result(db, result_id)
    if not success:
        raise HTTPException(status_code=404, detail="Result not found")
    
    return {
        "success": True,
        "message": "Result deleted successfully"
    }


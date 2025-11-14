# routers/workflow.py - AI Workflow Status Endpoints
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database
from datetime import datetime
from typing import List, Optional
from database import get_db, RESUME_COLLECTION, JOB_DESCRIPTION_COLLECTION, RESUME_RESULT_COLLECTION, AUDIT_LOG_COLLECTION, WORKFLOW_EXECUTION_COLLECTION
from routers.auth import get_current_user
import schemas
import crud

router = APIRouter(prefix="/workflow", tags=["AI Workflow"])

@router.get("/status")
async def get_workflow_status(
    jd_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Get real-time AI workflow status
    
    Returns actual data from MongoDB about:
    - Agent execution status
    - Processing metrics
    - Real candidates processed
    - Actual match results
    """
    try:
        # Get the most recent workflow execution to show current workflow data
        recent_workflow = db[WORKFLOW_EXECUTION_COLLECTION].find_one(
            {},
            sort=[("started_at", -1)]
        )
        
        # If we have a recent workflow, use its data
        if recent_workflow:
            workflow_id = recent_workflow.get("workflow_id")
            resume_ids = recent_workflow.get("resume_ids", [])
            jd_id = recent_workflow.get("jd_id")
            
            print(f"🔍 Loading workflow status for: {workflow_id}")
            print(f"   Resume IDs: {len(resume_ids)} resumes")
            print(f"   JD ID: {jd_id}")
            
            # Count resumes for THIS workflow only
            total_resumes = len(resume_ids)
            
            # Count JDs (1 JD per workflow)
            total_jds = 1 if jd_id else 0
            
            # Count matches for THIS workflow only
            total_matches = db[RESUME_RESULT_COLLECTION].count_documents({
                "resume_id": {"$in": resume_ids},
                "jd_id": jd_id
            })
            
            print(f"   Total resumes: {total_resumes}")
            print(f"   Total matches: {total_matches}")
        else:
            # No workflows yet - show empty state
            print(f"⚠️ No workflows found in database")
            workflow_id = None
            resume_ids = []
            jd_id = None
            total_resumes = 0
            total_jds = 0
            total_matches = 0
        
        # Get recent audit logs to determine agent status
        recent_logs = list(
            db[AUDIT_LOG_COLLECTION].find()
            .sort("timestamp", -1)
            .limit(20)
        )
        
        # Determine which agents have run
        agents_run = set()
        for log in recent_logs:
            action = log.get("action", "").lower()
            if "resume" in action and "process" in action:
                agents_run.add("resume-extractor")
            if "jd" in action or "job" in action:
                agents_run.add("jd-reader")
            if "match" in action:
                agents_run.add("hr-comparator")
                agents_run.add("resume-reader")  # Must have run before matching
        
        # Calculate processing times from audit logs
        processing_times = []
        for log in recent_logs:
            if "duration" in log.get("details", {}):
                processing_times.append(log["details"]["duration"])
        
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
        
        # Get match statistics for THIS workflow only
        # Remove limit to count ALL matches for accurate fit category counts
        if recent_workflow and resume_ids and jd_id:
            matches = list(db[RESUME_RESULT_COLLECTION].find({
                "resume_id": {"$in": resume_ids},
                "jd_id": jd_id
            }))
        else:
            matches = []
        
        high_matches = [m for m in matches if m.get("match_score", 0) >= 80]
        match_rate = (len(high_matches) / len(matches) * 100) if matches else 0
        
        # Calculate fit category counts based on match scores (using ALL matches, not limited)
        best_fit_count = len([m for m in matches if m.get("match_score", 0) >= 80])
        partial_fit_count = len([m for m in matches if 50 <= m.get("match_score", 0) < 80])
        not_fit_count = len([m for m in matches if m.get("match_score", 0) < 50])
        
        # Build agent statuses
        # Note: Only HR Comparator is actual AI agent
        # JD Reader and Resume Reader are direct parsing steps, not AI agents
        agents = []
        
        # Step 1: JD Reader (Direct Parsing - Not an AI Agent)
        jd_logs = [l for l in recent_logs if "job" in l.get("action", "").lower() or "jd" in l.get("action", "").lower()]
        agents.append({
            "id": "jd-reader",
            "name": "JD Reader Agent",
            "status": "completed" if total_jds > 0 else "idle",
            "timestamp": jd_logs[0].get("timestamp").isoformat() if jd_logs else None,
            "duration": f"{avg_processing_time * 0.3:.1f}s" if avg_processing_time and total_jds > 0 else None,
            "description": f"Parsed {total_jds} job description(s) and extracted requirements (Direct Parsing)" if total_jds > 0 else "Waiting for JD upload",
            "confidence": None,
            "is_ai_agent": False,  # This is direct parsing, not AI
            "metrics": {
                "jdsProcessed": total_jds,
                "criteriaExtracted": "Complete" if total_jds > 0 else "Pending"
            }
        })
        
        # Step 2: Resume Reader (Direct Parsing - Not an AI Agent)
        resume_logs = [l for l in recent_logs if "resume" in l.get("action", "").lower() and "upload" in l.get("action", "").lower()]
        agents.append({
            "id": "resume-reader",
            "name": "Resume Reader Agent",
            "status": "completed" if total_resumes > 0 else "idle",
            "timestamp": resume_logs[0].get("timestamp").isoformat() if resume_logs else None,
            "duration": f"{avg_processing_time * 1.5:.1f}s" if avg_processing_time and total_resumes > 0 else None,
            "description": f"Parsed {total_resumes} resume(s) and extracted candidate details (Direct Parsing)" if total_resumes > 0 else "Waiting for resumes",
            "confidence": None,
            "is_ai_agent": False,  # This is direct parsing, not AI
            "metrics": {
                "candidatesProcessed": total_resumes,
                "structuredProfiles": total_resumes,
                "completenessScore": f"{int((total_resumes / max(total_resumes, 1)) * 100)}%" if total_resumes > 0 else "0%"
            }
        })
        
        # Step 3: HR Comparator (REAL AI AGENT - The only one!)
        match_logs = [l for l in recent_logs if "match" in l.get("action", "").lower()]
        
        # Determine HR Comparator status based on workflow state
        hr_comparator_status = "idle"
        hr_comparator_description = "Waiting for matching to start"
        
        if recent_workflow:
            workflow_status = recent_workflow.get("status", "pending")
            print(f"   Workflow status: {workflow_status}")
            print(f"   Total matches: {total_matches}")
            
            if total_matches > 0:
                # Has results - completed
                hr_comparator_status = "completed"
                hr_comparator_description = f"AI-powered matching: Compared and scored {total_matches} candidate(s)"
            elif workflow_status == "in_progress":
                # Workflow is actively running
                hr_comparator_status = "in-progress"
                hr_comparator_description = f"AI agent analyzing {total_resumes} candidates in real-time..."
                print(f"   ⚡ HR Comparator: IN PROGRESS")
            elif workflow_status == "pending" and total_resumes > 0 and total_jds > 0:
                # Ready to start but not started yet
                hr_comparator_status = "pending"
                hr_comparator_description = "Ready to start matching"
            
            print(f"   HR Comparator final status: {hr_comparator_status}")
        
        agents.append({
            "id": "hr-comparator",
            "name": "HR Comparator Agent",
            "status": hr_comparator_status,
            "timestamp": match_logs[0].get("timestamp").isoformat() if match_logs else None,
            "duration": f"{avg_processing_time * 2:.1f}s" if avg_processing_time and total_matches > 0 else None,
            "description": hr_comparator_description,
            "confidence": None,
            "is_ai_agent": True,  # This is the ONLY real AI agent
            "metrics": {
                "candidateProfiles": total_resumes,
                "candidatesScored": total_matches,
                "highMatches": len(high_matches),
                "topMatches": f"{len(high_matches)} candidates ready" if len(high_matches) > 0 else "Processing..."
            }
        })
        
        # Calculate overall progress
        # Note: Only HR Comparator is actual AI agent, others are parsing steps
        completed_agents = sum(1 for a in agents if a["status"] == "completed")
        total_agents = len(agents)  # 3 steps total
        overall_progress = (completed_agents / total_agents) * 100
        
        # Get actual processing time from workflow metrics
        workflow_metrics = recent_workflow.get("metrics", {})
        total_processing_time_ms = workflow_metrics.get("processing_time_ms", 0)
        total_processing_time = total_processing_time_ms / 1000 if total_processing_time_ms > 0 else 0
        
        # Get JD for THIS workflow
        recent_jd = None
        if recent_workflow and jd_id:
            from bson import ObjectId
            try:
                recent_jd = db[JOB_DESCRIPTION_COLLECTION].find_one(
                    {"_id": ObjectId(jd_id) if isinstance(jd_id, str) else jd_id}
                )
            except:
                recent_jd = db[JOB_DESCRIPTION_COLLECTION].find_one(
                    {"_id": jd_id}
                )
        
        # Determine if we should continue monitoring
        workflow_status = recent_workflow.get("status", "idle")
        should_monitor = workflow_status in ["in_progress", "pending"]
        
        return {
            "success": True,
            "status": workflow_status,  # Add status to response
            "agents": agents,
            "metrics": {
                "totalCandidates": total_resumes,
                "processingTime": f"{total_processing_time:.1f}s" if total_processing_time > 0 else "0s",
                "matchRate": f"{int(match_rate)}%" if matches else "0%",
                "topMatches": len(high_matches),
                "bestFit": best_fit_count,
                "partialFit": partial_fit_count,
                "notFit": not_fit_count
            },
            "progress": {
                "completed": completed_agents,
                "total": total_agents,
                "percentage": int(overall_progress)
            },
            "monitoring": should_monitor,  # ✅ FIXED: Only True if in_progress/pending
            "workflowId": workflow_id,
            "jdId": str(recent_jd["_id"]) if recent_jd else None,
            "jdTitle": recent_jd.get("designation", "Job Description") if recent_jd else "Job Description"
        }
        
    except Exception as e:
        # Return empty state on error
        return {
            "success": False,
            "status": "idle",
            "agents": [
                {"id": "jd-reader", "name": "JD Reader Agent", "status": "idle", "description": "No data yet", "is_ai_agent": False},
                {"id": "resume-reader", "name": "Resume Reader Agent", "status": "idle", "description": "No data yet", "is_ai_agent": False},
                {"id": "hr-comparator", "name": "HR Comparator Agent", "status": "idle", "description": "No data yet", "is_ai_agent": True}
            ],
            "metrics": {
                "totalCandidates": 0,
                "processingTime": "0s",
                "matchRate": "0%",
                "topMatches": 0
            },
            "progress": {
                "completed": 0,
                "total": 3,  # Only 3 steps now
                "percentage": 0
            },
            "monitoring": False,
            "error": str(e)
        }

@router.get("/executions", response_model=List[schemas.WorkflowExecutionListResponse])
def get_workflow_executions(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Get all workflow executions for current user
    
    - **skip**: Number of records to skip
    - **limit**: Maximum records to return (max 50)
    - **status**: Filter by status (pending/in_progress/completed/failed)
    """
    workflows = crud.get_user_workflows(db, current_user["_id"], skip, limit)
    
    # Filter by status if provided
    if status:
        workflows = [w for w in workflows if w.get("status") == status]
    
    # Format response to match schema (rename _id to id)
    formatted_workflows = []
    for w in workflows:
        formatted_workflows.append({
            "id": w["_id"],  # Rename _id to id
            "workflow_id": w["workflow_id"],
            "jd_id": w["jd_id"],
            "jd_title": w["jd_title"],
            "status": w["status"],
            "started_at": w["started_at"],
            "completed_at": w.get("completed_at"),
            "total_resumes": w["total_resumes"],
            "processed_resumes": w["processed_resumes"],
            "agents": w.get("agents", []),  # Include agents!
            "progress": w.get("progress", {}),
            "metrics": w.get("metrics", {})  # Include metrics!
        })
    
    return formatted_workflows

@router.get("/executions/{workflow_id}", response_model=schemas.WorkflowExecutionResponse)
def get_workflow_execution(
    workflow_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Get specific workflow execution details by workflow_id"""
    workflow = crud.get_workflow_by_id(db, workflow_id)
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # Format response to match schema (rename _id to id)
    formatted_workflow = {
        "id": workflow["_id"],
        "workflow_id": workflow["workflow_id"],
        "jd_id": workflow["jd_id"],
        "jd_title": workflow["jd_title"],
        "status": workflow["status"],
        "started_by": workflow["started_by"],
        "started_at": workflow["started_at"],
        "completed_at": workflow.get("completed_at"),
        "total_resumes": workflow["total_resumes"],
        "processed_resumes": workflow["processed_resumes"],
        "agents": workflow["agents"],
        "progress": workflow["progress"],
        "metrics": workflow["metrics"],
        "results": workflow.get("results"),
        "createdAt": workflow["createdAt"],
        "updatedAt": workflow["updatedAt"]
    }
    
    return formatted_workflow

@router.put("/executions/{workflow_id}/status", response_model=schemas.MessageResponse)
def update_workflow_execution_status(
    workflow_id: str,
    status_update: schemas.WorkflowStatusUpdate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Update workflow execution status (for background tasks)"""
    workflow = crud.get_workflow_by_id(db, workflow_id)
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # Build update data
    update_data = status_update.model_dump(exclude_unset=True)
    
    # If status is completed, set completed_at
    if update_data.get("status") == "completed":
        update_data["completed_at"] = datetime.utcnow()
    
    # Update workflow
    success = crud.update_workflow_status(db, workflow_id, update_data)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update workflow")
    
    return {
        "success": True,
        "message": "Workflow status updated successfully"
    }

@router.delete("/executions/{workflow_id}", response_model=schemas.MessageResponse)
def delete_workflow_execution(
    workflow_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Delete workflow execution"""
    workflow = crud.get_workflow_by_id(db, workflow_id)
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # Check if user owns this workflow
    if str(workflow.get("started_by")) != current_user["_id"]:
        raise HTTPException(status_code=403, detail="Not authorized to delete this workflow")
    
    success = crud.delete_workflow(db, workflow_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete workflow")
    
    return {
        "success": True,
        "message": "Workflow deleted successfully"
    }

@router.get("/executions/stats/count")
def get_workflow_count(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Get total workflow count, optionally filtered by status"""
    # Get workflows for current user
    all_workflows = crud.get_user_workflows(db, current_user["_id"], 0, 1000)
    
    if status:
        count = len([w for w in all_workflows if w.get("status") == status])
    else:
        count = len(all_workflows)
    
    return {
        "total": count,
        "status": status
    }


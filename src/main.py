import httpx
from typing import Dict, Any, Optional
from langgraph.graph import Graph
import asyncio
from datetime import datetime
import os
from dotenv import load_dotenv
from pathlib import Path
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, UUID4
import traceback

# Load environment variables
env_path = Path(__file__).parents[1] / '.env'
load_dotenv(dotenv_path=env_path)

# Configure API
ZEP_API_KEY = os.getenv("ZEP_API_KEY")
if not ZEP_API_KEY:
    raise ValueError("ZEP_API_KEY not found in environment variables")

ZEP_API_URL = "https://api.getzep.com/api/v2"

class ZepAPIError(Exception):
    """Custom exception for Zep API errors"""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class UserFactsResponse(BaseModel):
    status: str
    business_summary: Optional[Dict[str, Any]] = None
    fact_count: Optional[int] = None
    error: Optional[str] = None
    timestamp: str

# Create FastAPI app
app = FastAPI(
    title="Zep Facts API",
    description="API for retrieving and processing user facts from Zep",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def query_user_facts(user_id: str) -> Dict:
    """Query the Zep API for user facts"""
    print(f"Querying Zep API for user {user_id}...")
    print(f"Using API URL: {ZEP_API_URL}")
    
    headers = {
        "Authorization": f"Api-Key {ZEP_API_KEY}",
        "Content-Type": "application/json"
    }
    
    url = f"{ZEP_API_URL}/users/{user_id}/facts"
    print(f"Making request to: {url}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            print(f"Response status code: {response.status_code}")
            
            if response.status_code == 404:
                raise ZepAPIError(f"User {user_id} not found", status_code=404)
            elif response.status_code != 200:
                raise ZepAPIError(
                    f"Zep API error: {response.text}",
                    status_code=response.status_code
                )
            
            return response.json()
        except httpx.HTTPError as e:
            print(f"HTTP error occurred: {str(e)}")
            raise ZepAPIError(f"HTTP error occurred: {str(e)}", status_code=500)

async def process_user_facts(state: Dict[str, Any]) -> Dict[str, Any]:
    """Process user facts from Zep API"""
    user_id = state["user_id"]
    try:
        facts = await query_user_facts(user_id)
        return {
            "facts": facts,
            "user_id": user_id,
            "status": "success",
            "timestamp": datetime.now().isoformat()
        }
    except ZepAPIError as e:
        return {
            "user_id": user_id,
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def enrich_facts(state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich facts with additional metadata"""
    if state.get("status") != "success":
        return state
    
    facts_list = state.get("facts", {}).get("facts", [])
    
    business_info = {
        "name": next((f["target_node_name"] for f in facts_list if "HAS_NAME" == f["name"]), "Unknown"),
        "industry": next((f["target_node_name"] for f in facts_list if "HAS_INDUSTRY" == f["name"]), "Unknown"),
        "revenue": next((f["content"] for f in facts_list if "HAS_ANNUAL_REVENUE" == f["name"]), "Unknown"),
        "location": next((f["content"] for f in facts_list if "IS_LOCATED_AT" == f["name"]), "Unknown"),
        "services": {
            "type": next((f["content"] for f in facts_list if "HAS_BUSINESS_TYPE" == f["name"]), "Unknown"),
            "service_split": {
                "mechanic": next((f["content"] for f in facts_list if "COMPRISES" == f["name"] and "mechanic" in f["content"].lower()), "Unknown"),
                "towing": next((f["content"] for f in facts_list if "COMPRISES" == f["name"] and "towing" in f["content"].lower()), "Unknown")
            }
        },
        "contact": {
            "owner": next((f["content"] for f in facts_list if "HAS_CONTACT_ROLE" == f["name"]), "Unknown"),
            "email": next((f["target_node_name"] for f in facts_list if "HAS_EMAIL" == f["name"]), "Unknown"),
            "phone": next((f["target_node_name"] for f in facts_list if "HAS_PHONE" == f["name"]), "Unknown")
        },
        "equipment": {
            "tow_truck": {
                "model": next((f["content"].split("Tow Truck: ")[1].split(" has")[0] 
                             for f in facts_list if "Tow Truck:" in f["content"]), "Unknown"),
                "value": next((f["target_node_name"] for f in facts_list if "HAS_VALUE" == f["name"]), "Unknown"),
                "operating_radius": next((f["target_node_name"] for f in facts_list if "HAS_OPERATING_RADIUS" == f["name"]), "Unknown")
            }
        }
    }

    return {
        "status": "success",
        "business_summary": business_info,
        "facts": facts_list,
        "fact_count": len(facts_list),
        "processed_at": datetime.now().isoformat()
    }

def create_workflow() -> Graph:
    """Create the workflow graph"""
    workflow = Graph()
    
    # Add nodes
    workflow.add_node("query_facts", process_user_facts)
    workflow.add_node("enrich_facts", enrich_facts)
    
    # Add edges
    workflow.add_edge("query_facts", "enrich_facts")
    
    # Set entry and end points
    workflow.set_entry_point("query_facts")
    workflow.set_finish_point("enrich_facts")
    
    return workflow

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle all unhandled exceptions"""
    error_msg = f"An error occurred: {str(exc)}\n{traceback.format_exc()}"
    print(error_msg)  # Log the full error
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": str(exc),
            "detail": error_msg,
            "timestamp": datetime.now().isoformat()
        }
    )

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to Zep Facts API",
        "version": "1.0.0",
        "endpoints": {
            "user_facts": "/api/users/{user_id}/facts",
            "health": "/health",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/users/{user_id}/facts", response_model=UserFactsResponse)
async def get_user_facts(user_id: UUID4):
    """Get and process facts for a specific user"""
    try:
        # Create and compile workflow
        workflow = create_workflow().compile()
        
        # Execute workflow
        result = await workflow.ainvoke({"user_id": str(user_id)})
        
        if result.get("status") != "success":
            raise ZepAPIError(
                message=result.get("error", "Unknown error occurred"),
                status_code=500
            )
        
        return {
            "status": "success",
            "business_summary": result.get("business_summary"),
            "fact_count": result.get("fact_count", 0),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"Error in get_user_facts: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving user facts: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
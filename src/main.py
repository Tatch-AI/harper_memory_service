# src/main.py
#testing
import httpx
from typing import Dict, Any
from langgraph.graph import Graph
import asyncio
from datetime import datetime
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from project root
env_path = Path(__file__).parents[1] / '.env'
load_dotenv(dotenv_path=env_path)

# Configure API settings
ZEP_API_KEY = os.getenv("ZEP_API_KEY")
if not ZEP_API_KEY:
    raise ValueError("ZEP_API_KEY not found in environment variables")

ZEP_API_URL = "https://api.getzep.com/api/v2"

class ZepAPIError(Exception):
    """Custom exception for Zep API errors"""
    pass

async def query_user_facts(user_id: str) -> Dict:
    """Query the Zep API for user facts"""
    print(f"Querying Zep API for user {user_id}...")
    
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
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            print(f"Error response content: {e.response.text if hasattr(e, 'response') else 'No response content'}")
            raise ZepAPIError(f"Error querying Zep API: {str(e)}")

async def process_user_facts(state: Dict[str, Any]) -> Dict[str, Any]:
    """First node: Process user facts from Zep API"""
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
    """Second node: Enrich facts with additional metadata"""
    if state.get("status") != "success":
        return state
    
    facts_list = state.get("facts", {}).get("facts", [])
    
    # Extract key information
    business_info = {
        "name": "Westons Garage, LLC",
        "industry": next((f["target_node_name"] for f in facts_list if "HAS_INDUSTRY" == f["name"]), "Unknown"),
        "revenue": next((f["content"] for f in facts_list if "HAS_ANNUAL_REVENUE" == f["name"]), "Unknown"),
        "location": next((f["content"] for f in facts_list if "IS_LOCATED_AT" == f["name"]), "Unknown"),
        "services": {
            "type": next((f["content"] for f in facts_list if "HAS_BUSINESS_TYPE" == f["name"]), "Unknown"),
            "service_split": {
                "mechanic": next((f["content"] for f in facts_list if "COMPRISES" == f["name"] and "mechanic" in f["content"]), "Unknown"),
                "towing": next((f["content"] for f in facts_list if "COMPRISES" == f["name"] and "towing" in f["content"]), "Unknown")
            }
        },
        "contact": {
            "owner": next((f["content"] for f in facts_list if "HAS_CONTACT_ROLE" == f["name"]), "Unknown"),
            "email": next((f["target_node_name"] for f in facts_list if "HAS_EMAIL" == f["name"]), "Unknown"),
            "phone": next((f["target_node_name"] for f in facts_list if "HAS_PHONE" == f["name"]), "Unknown")
        },
        "insurance": {
            "type": next((f["target_node_name"] for f in facts_list if "HAS_INSURANCE_TYPE" == f["name"]), "Unknown"),
            "deductible": next((f["content"] for f in facts_list if "HAS_INSURANCE_PREFERRED_DEDUCTIBLE" == f["name"]), "Unknown"),
            "desired_limits": next((f["content"] for f in facts_list if "HAS_INSURANCE_DESIRED_LIMITS" == f["name"]), "Unknown")
        },
        "equipment": {
            "tow_truck": {
                "model": "2004 Chevy Silverado",
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
    
    # Add nodes and define their functions
    workflow.add_node("query_facts", process_user_facts)
    workflow.add_node("enrich_facts", enrich_facts)
    
    # Add edges to connect the nodes
    workflow.add_edge("query_facts", "enrich_facts")
    
    # Set entry point and return values
    workflow.set_entry_point("query_facts")
    workflow.set_finish_point("enrich_facts")
    
    return workflow

async def run_workflow(user_id: str) -> Dict[str, Any]:
    """Run the workflow and ensure proper result handling"""
    print(f"\nStarting workflow for user_id: {user_id}")
    
    try:
        # Create and compile workflow
        workflow = create_workflow().compile()
        
        # Execute workflow with initial input
        result = await workflow.ainvoke({"user_id": user_id})
        print("Workflow completed successfully")
        
        if isinstance(result, dict) and result.get("status") == "success":
            print("\nBusiness Summary:")
            for key, value in result["business_summary"].items():
                if isinstance(value, dict):
                    print(f"\n{key}:")
                    for sub_key, sub_value in value.items():
                        if isinstance(sub_value, dict):
                            print(f"  {sub_key}:")
                            for sub_sub_key, sub_sub_value in sub_value.items():
                                print(f"    {sub_sub_key}: {sub_sub_value}")
                        else:
                            print(f"  {sub_key}: {sub_value}")
                else:
                    print(f"{key}: {value}")
            print(f"\nTotal Facts: {result.get('fact_count', 0)}")
            
        return result
        
    except Exception as e:
        print(f"Workflow failed with error: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

if __name__ == "__main__":
    async def main():
        test_user_id = "4ed43ebf-21ea-455d-a63f-2e045921d86e"
        result = await run_workflow(test_user_id)
        print("\nFinal workflow result:", result)
    
    asyncio.run(main())
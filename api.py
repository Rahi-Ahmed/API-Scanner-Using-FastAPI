import os
import json
import shutil
import zipfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings
from trainer import train_on_library
from analyzer import analyze_script

class Settings(BaseSettings):
    knowledge_file: str = "knowledge_base.json"
    temp_dir: str = "./temp_uploads"

settings = Settings()
app = FastAPI(title="API Scanner Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

# State Management Helpers
def load_knowledge_base() -> dict:
    if not os.path.exists(settings.knowledge_file):
        return {}
    with open(settings.knowledge_file, 'r', encoding="utf-8") as f:
        return json.load(f)

def save_knowledge_base(data: dict):
    with open(settings.knowledge_file, 'w', encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# Ensure temp directory exists on startup
@app.on_event("startup")
def startup_event():
    os.makedirs(settings.temp_dir, exist_ok=True)

# Endpoints
@app.post("/train", summary="Train on a zipped library")
async def train(file: UploadFile = File(...)):
    """Upload a .zip file of a library (e.g., bs4.zip) to extract deprecations."""
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Library must be uploaded as a .zip file.")

    base_module_name = file.filename.replace('.zip', '')
    zip_path = os.path.join(settings.temp_dir, file.filename)
    extract_path = os.path.join(settings.temp_dir, base_module_name)

    try:
        # Save and extract zip
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
            
        new_knowledge = train_on_library(extract_path, base_module_name)
        
        # Update persistent storage
        master_knowledge = load_knowledge_base()
        master_knowledge.update(new_knowledge)
        save_knowledge_base(master_knowledge)
        
        return {
            "status": "success",
            "library": base_module_name,
            "new_deprecations_found": len(new_knowledge),
            "total_knowledge_base_size": len(master_knowledge)
        }
        
    finally:
        # Cleanup temp files
        if os.path.exists(zip_path):
            os.remove(zip_path)
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path)

@app.post("/analyze", summary="Analyze a Python script")
async def analyze(file: UploadFile = File(...)):
    """Upload a .py script to check for deprecated API usage."""
    if not file.filename.endswith('.py'):
        raise HTTPException(status_code=400, detail="Script must be a .py file.")

    script_path = os.path.join(settings.temp_dir, file.filename)
    
    try:
        # Save script temporarily
        with open(script_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Run analyzer
        knowledge_base = load_knowledge_base()
        if not knowledge_base:
            return {"status": "warning", "message": "Knowledge base is empty. Please /train first.", "findings": []}
            
        findings = analyze_script(script_path, knowledge_base)
        
        return {
            "status": "success",
            "script": file.filename,
            "issues_found": len(findings),
            "findings": findings
        }
        
    finally:
        # Cleanup
        if os.path.exists(script_path):
            os.remove(script_path)

@app.post("/reset", summary="Clear the knowledge base")
async def reset():
    """Deletes all training data and empties the knowledge base."""
    save_knowledge_base({})
    return {"status": "success", "message": "Knowledge base has been reset to empty."}
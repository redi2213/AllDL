#!/usr/bin/env python3
import requests
import time
import sys

REPO = "redi2213/AllDL"
API = f"https://api.github.com/repos/{REPO}"

print("=" * 60)
print("Upload File via GitHub")
print("=" * 60)
print()

token = input("Enter GitHub Token: ").strip()
file_url = input("Enter File URL: ").strip()

if not token or not file_url:
    print("Error: Token and URL required!")
    exit(1)

headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github+json"
}

print("\nTriggering GitHub workflow...")

try:
    # Trigger workflow
    r = requests.post(
        f"{API}/actions/workflows/download.yml/dispatches",
        headers=headers,
        json={"ref": "main", "inputs": {"file_url": file_url}}
    )
    r.raise_for_status()
    print("Workflow triggered!")
    
except Exception as e:
    print(f"Error: {e}")
    exit(1)

# Wait for workflow to start
time.sleep(5)

print("Waiting for download to complete...")

try:
    # Get latest run ID
    r = requests.get(
        f"{API}/actions/workflows/download.yml/runs?per_page=1",
        headers=headers
    )
    r.raise_for_status()
    runs = r.json()["workflow_runs"]
    
    if not runs:
        print("Error: Workflow not found!")
        exit(1)
    
    run_id = runs[0]["id"]
    
    # Wait for run to complete
    while True:
        r = requests.get(f"{API}/actions/runs/{run_id}", headers=headers)
        r.raise_for_status()
        status = r.json()["status"]
        
        if status == "completed":
            conclusion = r.json()["conclusion"]
            if conclusion != "success":
                print(f"Workflow failed: {conclusion}")
                exit(1)
            break
        
        print(f"Status: {status}...", end='\r')
        time.sleep(3)
    
    print("Download completed!         ")
    
    # Get release link
    tag = f"run-{run_id}"
    r = requests.get(f"{API}/releases/tags/{tag}", headers=headers)
    
    if r.status_code != 200:
        print("Waiting for release to be created...")
        time.sleep(5)
        r = requests.get(f"{API}/releases/tags/{tag}", headers=headers)
    
    r.raise_for_status()
    assets = r.json().get("assets", [])
    
    if not assets:
        print("Error: No files found in release!")
        exit(1)
    
    download_link = assets[0]["browser_download_url"]
    
    print("\n" + "=" * 60)
    print("SUCCESS!")
    print("=" * 60)
    print(download_link)
    print("=" * 60)
    
except Exception as e:
    print(f"Error: {e}")
    exit(1)

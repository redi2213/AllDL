import os
import json
import sys
import time
import uuid
import threading
import requests

CONFIG_FILE = os.path.expanduser("~/.alldl_config.json")
LINKS_FILE = "/storage/self/primary/0cdn/linkx/Linkyes.txt"
RESULTS_FILE = "/storage/self/primary/0cdn/linkx/dlyes.txt"
REPO = "redi2213/AllDL"
API = f"https://api.github.com/repos/{REPO}"

# How long the Termux script waits for a job to finish before moving on
POLL_GIVEUP_SECONDS = 5 * 60

print_lock = threading.Lock()
file_lock = threading.Lock()


def load_token():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f).get("token")
    return None


def save_token(token):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"token": token}, f)
    os.chmod(CONFIG_FILE, 0o600)


def get_token():
    token = load_token()
    if token:
        return token
    token = input("Enter GitHub Token (saved for future use): ").strip()
    save_token(token)
    return token


def ask_yes_no(prompt):
    while True:
        ans = input(prompt + " (y/n): ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def log(tag, msg):
    with print_lock:
        print(f"[{tag}] {msg}")


def save_result(file_url, result_text):
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with file_lock:
        with open(RESULTS_FILE, "a") as f:
            f.write(f"{file_url} -> {result_text}\n")


def process_link(headers, file_url, zip_it, custom_name):
    job_id = uuid.uuid4().hex[:10]
    tag = job_id
    label = custom_name if custom_name else file_url.split("/")[-1][:20]

    log(label, "Triggering workflow...")
    try:
        r = requests.post(
            f"{API}/actions/workflows/download.yml/dispatches",
            headers=headers,
            json={
                "ref": "main",
                "inputs": {
                    "file_url": file_url,
                    "zip_it": "true" if zip_it else "false",
                    "custom_name": custom_name,
                    "job_id": job_id,
                },
            },
        )
        r.raise_for_status()
    except Exception as e:
        log(label, f"Dispatch failed: {e}")
        save_result(file_url, "FAILED (dispatch error)")
        return

    log(label, "Waiting for run to appear...")
    run_id = None
    for _ in range(20):
        time.sleep(3)
        r = requests.get(f"{API}/actions/runs?per_page=20", headers=headers)
        if r.status_code != 200:
            continue
        for run in r.json().get("workflow_runs", []):
            if run.get("display_title") == job_id or run.get("name") == job_id:
                run_id = run["id"]
                break
        if run_id:
            break

    if not run_id:
        log(label, "Could not find run, giving up")
        save_result(file_url, "FAILED (run not found)")
        return

    log(label, f"Run found (id={run_id}), tracking...")
    last_status = None
    waited = 0
    while waited < POLL_GIVEUP_SECONDS:
        r = requests.get(f"{API}/actions/runs/{run_id}", headers=headers)
        if r.status_code == 200:
            data = r.json()
            status = data["status"]
            if status != last_status:
                log(label, f"status: {status}")
                last_status = status
            if status == "completed":
                if data["conclusion"] != "success":
                    log(label, f"FAILED: {data['conclusion']}")
                    save_result(file_url, f"FAILED ({data['conclusion']})")
                    return
                break
        time.sleep(4)
        waited += 4
    else:
        log(label, "Still running after 5 min, moving on (check GitHub Releases later)")
        save_result(file_url, f"PENDING (still running, tag: {tag})")
        return

    log(label, "Fetching release link...")
    for _ in range(10):
        r = requests.get(f"{API}/releases/tags/{tag}", headers=headers)
        if r.status_code == 200:
            assets = r.json().get("assets", [])
            if assets:
                link = assets[0]["browser_download_url"]
                log(label, f"DONE: {link}")
                save_result(file_url, link)
                return
        time.sleep(3)

    log(label, "Could not get release link")
    save_result(file_url, "FAILED (no release link)")


def main():
    token = get_token()
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    print("1. Enter link here")
    print("2. Read links from file")
    choice = input("Choice (1/2): ").strip()

    if choice == "1":
        file_url = input("Enter file URL: ").strip()
        if not file_url:
            print("URL required")
            sys.exit(1)
        links = [file_url]
    elif choice == "2":
        if not os.path.exists(LINKS_FILE):
            print(f"File not found: {LINKS_FILE}")
            sys.exit(1)
        with open(LINKS_FILE) as f:
            links = [line.strip() for line in f if line.strip()]
        if not links:
            print("No links found in file")
            sys.exit(1)
        print(f"Found {len(links)} link(s)")
    else:
        print("Invalid choice")
        sys.exit(1)

    # Ask everything up front so nothing blocks mid-run
    zip_it = ask_yes_no("Zip the file(s)")
    rename = ask_yes_no("Rename the file(s)")
    base_name = ""
    if rename:
        base_name = input("Enter new name (no extension): ").strip()

    print("\nStarting all uploads in parallel...\n")

    threads = []
    for i, link in enumerate(links, start=1):
        if rename and base_name:
            custom_name = f"{base_name}_{i}" if len(links) > 1 else base_name
        else:
            custom_name = ""
        t = threading.Thread(
            target=process_link,
            args=(headers, link, zip_it, custom_name),
        )
        t.start()
        threads.append(t)
        time.sleep(1)

    for t in threads:
        t.join()

    print("\nAll jobs finished. Results saved to:")
    print(RESULTS_FILE)


if __name__ == "__main__":
    main()

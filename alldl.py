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

print_lock = threading.Lock()


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


def process_link(headers, file_url, zip_it, custom_name, results):
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
        results[file_url] = None
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
        results[file_url] = None
        return

    log(label, f"Run found (id={run_id}), downloading on GitHub...")
    last_status = None
    while True:
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
                    results[file_url] = None
                    return
                break
        time.sleep(4)

    log(label, "Fetching release link...")
    for _ in range(10):
        r = requests.get(f"{API}/releases/tags/{tag}", headers=headers)
        if r.status_code == 200:
            assets = r.json().get("assets", [])
            if assets:
                link = assets[0]["browser_download_url"]
                log(label, f"DONE: {link}")
                results[file_url] = link
                return
        time.sleep(3)

    log(label, "Could not get release link")
    results[file_url] = None


def main():
    token = get_token()
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    print("1. Enter link here")
    print("2. Read links from file")
    choice = input("Choice (1/2): ").strip()

    links = []
    zip_it = False
    custom_name = ""

    if choice == "1":
        file_url = input("Enter file URL: ").strip()
        if not file_url:
            print("URL required")
            sys.exit(1)
        links = [file_url]
        zip_it = ask_yes_no("Zip the file")
        rename = ask_yes_no("Rename the file")
        if rename:
            custom_name = input("Enter new name (no extension): ").strip()
    elif choice == "2":
        if not os.path.exists(LINKS_FILE):
            print(f"File not found: {LINKS_FILE}")
            sys.exit(1)
        with open(LINKS_FILE) as f:
            links = [line.strip() for line in f if line.strip()]
        if not links:
            print("No links found in file")
            sys.exit(1)
        print(f"Found {len(links)} link(s), uploading all in parallel...")
    else:
        print("Invalid choice")
        sys.exit(1)

    results = {}
    threads = []
    for link in links:
        t = threading.Thread(
            target=process_link,
            args=(headers, link, zip_it, custom_name, results),
        )
        t.start()
        threads.append(t)
        time.sleep(1)

    for t in threads:
        t.join()

    print("\n" + "=" * 60)
    print("ALL RESULTS")
    print("=" * 60)

    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "a") as f:
        for link in links:
            result = results.get(link)
            if result:
                print(f"{link}\n -> {result}\n")
                f.write(f"{link} -> {result}\n")
            else:
                print(f"{link}\n -> FAILED\n")
                f.write(f"{link} -> FAILED\n")

    print("=" * 60)
    print(f"Saved to: {RESULTS_FILE}")


if __name__ == "__main__":
    main()

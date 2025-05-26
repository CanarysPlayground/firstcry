import os
import requests
import subprocess
import json
import logging
import csv
import time

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Config
GITLAB_DOMAIN = "your.gitlab.domain"  # E.g. gitlab.company.com
GITLAB_GROUP = "c-team"
GITHUB_ORG = "your-github-org"
GITHUB_PAT = "ghp_yourgithubtoken"
GITLAB_USER = "your_gitlab_username"  # Add your GitLab username here
GITLAB_TOKEN = "your_gitlab_token"  # Add your GitLab personal access token here
CSV_FILE_NAME = "repositories.csv"
LOG_FILE_NAME = "migration_log.csv"

def read_repos(csv_file):
    with open(csv_file, mode='r') as file:
        reader = csv.DictReader(file)
        return [(row['Source Repository'], row['Target Repository']) for row in reader]  # Read with headers

def write_log(entry):
    file_exists = os.path.isfile(LOG_FILE_NAME)
    with open(LOG_FILE_NAME, mode='a', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=[
            "Source Repository", "Target Repository", "GitLab Clone", "LFS Migration", "GitHub Push", "Final Status"
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerow(entry)

def create_github_repo(repo):
    url = f"https://api.github.com/orgs/{GITHUB_ORG}/repos"
    headers = {"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}
    payload = json.dumps({"name": repo, "private": True})
    r = requests.post(url, headers=headers, data=payload)
    if r.status_code == 201:
        logging.info(f"GitHub repo {repo} created.")
    elif r.status_code == 422:
        logging.info(f"GitHub repo {repo} already exists.")
    else:
        raise Exception(f"Failed to create repo {repo}: {r.text}")

def clone_gitlab_repo(source_repo, target_repo):
    # GitLab authentication included in the URL
    url = f"https://{GITLAB_USER}:{GITLAB_TOKEN}@{GITLAB_DOMAIN}/{GITLAB_GROUP}/{source_repo}.git"
    subprocess.run(["git", "clone", "--bare", url, target_repo], check=True)

def list_large_files(repo):
    os.chdir(f"{repo}.git")
    result = subprocess.run(
        "git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | sed -n 's/^blob //p'",
        capture_output=True, text=True, shell=True)
    files = []
    if result.returncode == 0:
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    size = int(parts[1])
                    if size > 104857600:  # Files greater than 100MB
                        files.append(parts[2])
                except ValueError:
                    continue
    os.chdir("..")
    return files

def rewrite_lfs(repo, files):
    if not files:
        return "Skipped"
    os.chdir(f"{repo}.git")
    try:
        subprocess.run(["git", "lfs", "migrate", "import", "--everything", f"--include={','.join(files)}"], check=True)
        status = "Success"
    except subprocess.CalledProcessError:
        status = "Failed"
    os.chdir("..")
    return status

def push_to_github(repo, target_repo):
    os.chdir(f"{repo}.git")
    url = f"https://{GITHUB_PAT}@github.com/{GITHUB_ORG}/{target_repo}.git"
    try:
        subprocess.run(["git", "remote", "remove", "github"], check=False)
        subprocess.run(["git", "remote", "add", "github", url], check=True)
        subprocess.run(["git", "push", "--all", "github", "--force"], check=True)
        subprocess.run(["git", "push", "--tags", "github", "--force"], check=True)
        status = "Success"
    except subprocess.CalledProcessError:
        status = "Failed"
    os.chdir("..")
    return status

def main():
    repos = read_repos(CSV_FILE_NAME)
    for source_repo, target_repo in repos:
        logging.info(f"Starting migration for {source_repo} to {target_repo}")
        log = {"Source Repository": source_repo, "Target Repository": target_repo, "GitLab Clone": "", "LFS Migration": "", "GitHub Push": "", "Final Status": ""}
        try:
            create_github_repo(target_repo)  # Create target GitHub repo

            if not os.path.exists(f"{target_repo}.git"):
                clone_gitlab_repo(source_repo, target_repo)  # Clone from GitLab to the target repo name
                log["GitLab Clone"] = "Success"
            else:
                log["GitLab Clone"] = "Already Exists"

            large_files = list_large_files(target_repo)
            log["LFS Migration"] = rewrite_lfs(target_repo, large_files)
            log["GitHub Push"] = push_to_github(target_repo, target_repo)  # Push to the created target repo

            if log["GitLab Clone"] in ["Success", "Already Exists"] and log["GitHub Push"] == "Success":
                log["Final Status"] = "Success"
            else:
                log["Final Status"] = "Partial/Failed"
        except Exception as e:
            logging.error(f"{source_repo} failed: {e}")
            log["Final Status"] = "Failed"
            if not log["GitLab Clone"]:
                log["GitLab Clone"] = "Failed"
            if not log["LFS Migration"]:
                log["LFS Migration"] = "Skipped"
            if not log["GitHub Push"]:
                log["GitHub Push"] = "Failed"
        write_log(log)
        time.sleep(3)

if __name__ == "__main__":
    main()

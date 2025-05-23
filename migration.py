import os
import requests
import subprocess
import json
import logging
import csv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Sensitive information and configuration
GITLAB_TOKEN = "glhhhjhjjjknknkn"
GITLAB_BASE_URL = "ghgjhknkjlb"
GITLAB_GROUP = "c-team"
GITHUB_ORG = "******"
GITHUB_PAT = "ghp_oDU6lAeDMabjhknknr3ECLTs1YBb2n3E3T"

CSV_FILE_NAME = "repositories.csv"
LOG_FILE_NAME = "migration_log.csv"

def read_repos_from_csv(csv_file):
    repos = []
    with open(csv_file, mode='r') as file:
        csv_reader = csv.reader(file)
        for row in csv_reader:
            repos.append(row[0])
    return repos

def write_log(log_data):
    file_exists = os.path.isfile(LOG_FILE_NAME)
    with open(LOG_FILE_NAME, mode='a', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=[
            "Repository", "GitLab Clone Status", "LFS Migration Status", "GitHub Push Status", "Final Status"
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerow(log_data)

def create_github_repo(repo):
    logging.info(f"Creating repository {repo} on GitHub...")
    create_repo_url = f"https://api.github.com/orgs/{GITHUB_ORG}/repos"
    create_repo_payload = json.dumps({"name": repo, "private": True})
    response = requests.post(create_repo_url, headers={
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }, data=create_repo_payload)
    response.raise_for_status()

def clone_repo_bare(repo):
    logging.info(f"Cloning repository as bare: {repo}")
    clone_url = f"https://{GITLAB_TOKEN}@{GITLAB_BASE_URL}/{GITLAB_GROUP}/{repo}.git"
    subprocess.run(["git", "clone", "--bare", clone_url], check=True)

def list_large_files(repo):
    logging.info(f"Listing large files (>100MB) in repository: {repo}")
    os.chdir(f"{repo}.git")
    command = (
        "git rev-list --objects --all | "
        "git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | "
        "sed -n 's/^blob //p'"
    )
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    large_files = []
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    size = int(parts[1])
                    if size > 104857600:  # 100 MB
                        large_files.append(parts[2])
                except ValueError:
                    continue
    else:
        logging.warning("No large files found or command failed")
    os.chdir("..")
    return large_files

def rewrite_history(repo, large_files):
    if not large_files:
        logging.info(f"No files larger than 100MB in {repo}, skipping LFS migration.")
        return "Skipped"
    logging.info(f"Rewriting history for large files in repository: {repo}")
    os.chdir(f"{repo}.git")
    include_files = ",".join(large_files)
    try:
        subprocess.run(["git", "lfs", "migrate", "import", "--everything", f"--include={include_files}"], check=True)
        status = "Success"
    except subprocess.CalledProcessError as e:
        logging.error(f"Git LFS migration failed for {repo}: {e}")
        status = "Failed"
    os.chdir("..")
    return status

def push_to_github(repo):
    logging.info(f"Pushing latest changes of {repo} to GitHub...")
    os.chdir(f"{repo}.git")
    try:
        subprocess.run(["git", "remote", "add", "github", f"https://{GITHUB_PAT}@github.com/{GITHUB_ORG}/{repo}.git"], check=True)
        subprocess.run(["git", "push", "--all", "github", "--force"], check=True)
        subprocess.run(["git", "push", "--tags", "github", "--force"], check=True)
        status = "Success"
    except subprocess.CalledProcessError as e:
        logging.error(f"GitHub push failed for {repo}: {e}")
        status = "Failed"
    os.chdir("..")
    return status

def main():
    repo_slugs = read_repos_from_csv(CSV_FILE_NAME)
    logging.info(f"Repositories to migrate: {repo_slugs}")

    for repo in repo_slugs:
        logging.info(f"Processing repository: {repo}")
        log_entry = {
            "Repository": repo,
            "GitLab Clone Status": "",
            "LFS Migration Status": "",
            "GitHub Push Status": "",
            "Final Status": ""
        }

        try:
            github_repo_url = f"https://api.github.com/repos/{GITHUB_ORG}/{repo}"
            check_github_repo = requests.get(github_repo_url, headers={"Authorization": f"token {GITHUB_PAT}"})

            if check_github_repo.status_code == 404:
                create_github_repo(repo)

            if not os.path.exists(f"{repo}.git"):
                clone_repo_bare(repo)
                log_entry["GitLab Clone Status"] = "Success"
            else:
                log_entry["GitLab Clone Status"] = "Already Exists"

            large_files = list_large_files(repo)
            log_entry["LFS Migration Status"] = rewrite_history(repo, large_files)
            log_entry["GitHub Push Status"] = push_to_github(repo)

            log_entry["Final Status"] = "Success" if (
                log_entry["GitLab Clone Status"] in ["Success", "Already Exists"] and
                log_entry["GitHub Push Status"] == "Success"
            ) else "Partial/Failed"

        except Exception as e:
            logging.error(f"Migration failed for {repo}: {e}")
            log_entry["Final Status"] = "Failed"
            if not log_entry["GitLab Clone Status"]:
                log_entry["GitLab Clone Status"] = "Failed"
            if not log_entry["GitHub Push Status"]:
                log_entry["GitHub Push Status"] = "Skipped"
            if not log_entry["LFS Migration Status"]:
                log_entry["LFS Migration Status"] = "Skipped"

        write_log(log_entry)
        logging.info(f"Repository {repo} migration complete with status: {log_entry['Final Status']}")

    logging.info("All repository migrations completed.")

if __name__ == "__main__":
    main()

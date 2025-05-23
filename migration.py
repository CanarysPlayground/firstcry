import os
import requests
import subprocess
import json
import logging
import csv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Sensitive information and configuration
GITLAB_TOKEN = "glhhhjhjjjknknkn"  # GitLab token
GITLAB_BASE_URL = "ghgjhknkjlb"  # Custom GitLab instance URL
GITLAB_GROUP = "c-team"  # Adjust according to your group or user namespace
GITHUB_ORG = "******"
GITHUB_PAT = "ghp_oDU6lAeDMabjhknknr3ECLTs1YBb2n3E3T"

CSV_FILE_NAME = "repositories.csv"

def read_repos_from_csv(csv_file):
    repos = []
    with open(csv_file, mode='r') as file:
        csv_reader = csv.reader(file)
        for row in csv_reader:
            repos.append(row[0])
    return repos

def create_github_repo(repo):
    logging.info(f"Creating repository {repo} on GitHub...")
    create_repo_url = f"https://api.github.com/orgs/{GITHUB_ORG}/repos"
    create_repo_payload = json.dumps({"name": repo, "private": True})
    response = requests.post(create_repo_url, headers={"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}, data=create_repo_payload)
    response.raise_for_status()

def clone_repo_bare(repo):
    logging.info(f"Cloning repository as bare: {repo}")
    # Use GitLab token to authenticate when cloning
    clone_url = f"https://{GITLAB_TOKEN}@{GITLAB_BASE_URL}/{GITLAB_GROUP}/{repo}.git"
    subprocess.run(["git", "clone", "--bare", clone_url], check=True)

def list_large_files(repo):
    logging.info(f"Listing large files in repository: {repo}")
    os.chdir(f"{repo}.git")
    command = "git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | sed -n 's/^blob //p' | sort --numeric-sort --key=2 | tail -n 20 | cut -c 1-12,41- | $(command -v gnumfmt || echo numfmt) --field=2 --to=iec-i --suffix=B --padding=7 --round=nearest"
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    logging.info(f"Command output: {result.stdout}")
    if result.stdout.strip():
        large_files = [line.split()[0] for line in result.stdout.strip().split('\n')]
    else:
        logging.warning("No large files found or command failed")
        large_files = []
    os.chdir("..")
    return large_files

def rewrite_history(repo, large_files):
    logging.info(f"Rewriting history for large files in repository: {repo}")
    os.chdir(f"{repo}.git")
    include_files = ",".join(large_files)
    subprocess.run(["git", "lfs", "migrate", "import", "--everything", f"--include={include_files}"], check=True)
    os.chdir("..")

def push_to_github(repo):
    logging.info(f"Pushing latest changes of {repo} to GitHub...")
    os.chdir(f"{repo}.git")
    subprocess.run(["git", "remote", "add", "github", f"https://{GITHUB_PAT}@github.com/{GITHUB_ORG}/{repo}.git"], check=True)
    subprocess.run(["git", "push", "--all", "github", "--force"], check=True)
    subprocess.run(["git", "push", "--tags", "github", "--force"], check=True)
    os.chdir("..")

def main():
    repo_slugs = read_repos_from_csv(CSV_FILE_NAME)
    logging.info(f"Repositories to migrate: {repo_slugs}")

    for repo in repo_slugs:
        logging.info(f"Processing repository: {repo}")
        
        github_repo_url = f"https://api.github.com/repos/{GITHUB_ORG}/{repo}"
        check_github_repo = requests.get(github_repo_url, headers={"Authorization": f"token {GITHUB_PAT}"})
        
        if check_github_repo.status_code == 404:
            create_github_repo(repo)
        
        if not os.path.exists(f"{repo}.git"):
            clone_repo_bare(repo)
        
        large_files = list_large_files(repo)
        rewrite_history(repo, large_files)
        push_to_github(repo)
        
        logging.info(f"Repository {repo} migrated successfully.")

    logging.info("All repositories updated successfully.")

if __name__ == "__main__":
    main()

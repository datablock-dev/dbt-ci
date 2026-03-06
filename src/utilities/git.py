"""
Module for Git-related utilities, such as cloning repositories and managing branches.
"""
import os
import subprocess

class GitAdapter:
    provider = os.getenv("GIT_PROVIDER", "github").lower()

    def __init__(self):
        head_branch = subprocess.run(["git", "remote", "show", "origin"], capture_output=True, text=True, check=True)
        head_branch = head_branch.stdout.splitlines()
        head_branch = [line for line in head_branch if "HEAD branch" in line][0].split(":")[-1].strip()
        self.head_branch = head_branch

        subprocess.run(["git", "fetch", "origin", head_branch], check=True)

        # Get the difference between the head branch and the current branch
        result = subprocess.run(
            ["git", "diff", "--name-status", f"origin/{head_branch}", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Return a list of tuples containing the change type and file path
        self.changes = [line.split("\t") for line in result.stdout.splitlines()]

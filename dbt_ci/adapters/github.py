import os
from argparse import Namespace
from dbt_ci.schema import GitHubContext

class Github:
    def __init__(self, args: Namespace):
        self.args: Namespace = args
        self.provider = getattr(self.args, "git_provider").lower()
        self.context: GitHubContext | None = self.get_github_context()

    def get_github_context(self) -> GitHubContext | None:
        if self.provider == "github":
            github_context = os.getenv("GITHUB_CONTEXT")
            return github_context
        
        return None
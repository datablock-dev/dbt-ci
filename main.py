import sys
import argparse
from src.dependency_graph import DbtGraph
from src.runners.bash import bash_runner

def main():
    """
    Command-line interface for the DBT CI Tool.
    This function sets up the argument parser for the DBT CI Tool, allowing users to specify various options and parameters when running the tool from the command line.
    The available arguments include:
    --version: Displays the version of the tool.
    --prod-manifest-path / --reference-manifest-path: Specifies the path to the production or reference manifest.json file, which is required for the tool to function.
    --profiles-dir: Specifies the path to the directory containing the dbt profiles.yml file. If not provided, the tool will look for the profiles.yml file in the current directory and then in the user's home directory under ~/.dbt/.
    --dbt-project-dir: Specifies the path to the dbt project directory. If not provided, it defaults to the current directory.
    --target / -t: Specifies the dbt target to use for the test run. If not provided, it defaults to "default".
    """
    parser = argparse.ArgumentParser(
        prog="DBT CI Tool",
        description="DBT CI Tool",
        epilog="For more information, visit https://datablock.dev",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    parser.add_argument(
        "--prod-manifest-dir",
        "--reference-manifest-dir",
        type=str,
        help="Path to the production/reference manifest.json directory (Not the file itself)",
        required=True,
    )

    parser.add_argument(
        "--profiles-dir",
        type=str,
        help="Path to the directory containing the dbt profiles.yml file (defaults: <dbt-directory>/profiles.yml then ~/.dbt/)",
        required=False,
    )

    parser.add_argument(
        '--dbt-project-dir',
        type=str,
        help='Path to the dbt project directory (default: current directory)',
        default='.',
        required=True,
    )

    parser.add_argument(
        "--target",
        "-t",
        type=str,
        help="The dbt target to use for the test run (defaults to what is defined in target in profiles.yml)",
        required=False,
    )

    parser.add_argument(
        "--vars",
        "-v",
        type=str,
        help="A YAML string or a path to a YAML file containing variables to pass to dbt (default: empty)",
        default="",
        required=False,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="If set, the tool will only print the dbt commands that would be executed without actually running them (default: false)",
        default=False,
        required=False,
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (default: INFO)",
        default="INFO",
        required=False,
    )

    parser.add_argument(
        "--log-file",
        type=str,
        help="Path to a file where logs should be written (default: None, logs will be printed to stdout)",
        default=None,
        required=False,
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=["run", "test", "snapshot", "seed", None],
        help="The mode to run the tool in (default: run)",
        default="run",
        required=False,
    )

    parser.add_argument(
        "--selector",
        "-s",
        type=str,
        help="Space-separated list of selectors to run (default: empty)",
        default="",
        required=False,
        nargs="*"
    )

    parser.add_argument(
        "--runner",
        "-r",
        type=str,
        choices=["local", "docker", "bash"],
        default="local",
        help="The runner to use for running dbt commands (default: local)"
    )

    parser.add_argument(
        "--shell-path",
        "--bash-path",
        type=str,
        help="Path to the shell executable to use when runner is set to 'bash' (default: /bin/bash)",
        default="/bin/bash",
        required=False,
    )

    parser.add_argument(
        "--docker-image",
        type=str,
        help="Docker image to use (default: ghcr.io/dbt-labs/dbt-core:latest)",
        default="ghcr.io/dbt-labs/dbt-core:latest",
        required=False,
    )

    parser.add_argument(
        "--docker-platform",
        type=str,
        help="Platform for Docker image (e.g., linux/amd64, linux/arm64). Use linux/amd64 on Apple Silicon for compatibility",
        default=None,
        required=False,
    )

    parser.add_argument(
        "--docker-volumes",
        type=str,
        nargs="*",
        help="Additional volume mounts in format 'host:container' or 'host:container:ro'",
        default=[],
        required=False,
    )

    parser.add_argument(
        "--docker-env",
        type=str,
        nargs="*",
        help="Environment variables to pass to Docker in format 'KEY=VALUE'",
        default=[],
        required=False,
    )

    parser.add_argument(
        "--docker-network",
        type=str,
        help="Docker network mode (default: host)",
        default="host",
        required=False,
    )

    parser.add_argument(
        "--docker-user",
        type=str,
        help="User to run as inside container (default: current UID:GID)",
        default=None,
        required=False,
    )

    parser.add_argument(
        "--docker-args",
        type=str,
        help="Additional docker run arguments as a single string",
        default="",
        required=False,
    )
    
    args = parser.parse_args()

    try:
        bash_runner(
            commands=["ls", "--select", "state:modified+", "--target", "dev", "--state", ".dbtstate"],
            shell_path="/bin/dbt",
            dry_run=False
        )

        # Implement the main functionality here
        #print(args)
        dependency_graph = DbtGraph(args)
        dependency_graph.to_json()
        changed_nodes = dependency_graph.get_state_modified()

        print(changed_nodes)

    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)



if __name__ == "__main__":
    main()
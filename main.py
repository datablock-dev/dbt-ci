import sys
import argparse
from src.dependency_graph import DbtGraph

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
        choices=["local", "docker"],
        default="local",
        help="The runner to use for running dbt commands (default: local)"
    )

    parser.add_argument(
        "--docker-image",
        type=str,
        help="The Docker image to use when the runner is set to docker (default: dbt:latest)",
        default="dbt:latest",
        required=False,
    )
    
    args = parser.parse_args()

    try:
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
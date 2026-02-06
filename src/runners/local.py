import subprocess

def local_runner(args):
    # Build the dbt command based on the provided arguments
    dbt_command = ["dbt", args.mode]

    if args.target:
        dbt_command.extend(["--target", args.target])

    if args.vars:
        dbt_command.extend(["--vars", args.vars])

    if args.profiles_dir:
        dbt_command.extend(["--profiles-dir", args.profiles_dir])

    if args.dbt_project_dir:
        dbt_command.extend(["--project-dir", args.dbt_project_dir])

    if args.dry_run:
        print("Dry run enabled. The following command would be executed:")
        print(" ".join(dbt_command))
        return

    # Execute the dbt command
    try:
        result = subprocess.run(dbt_command, check=True, capture_output=True, text=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error executing dbt command: {e.stderr}")
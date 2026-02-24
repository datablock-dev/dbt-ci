# CHANGELOG


## v1.2.1 (2026-02-24)

### Bug Fixes

- Slack-sdk, logging & summary ([#13](https://github.com/datablock-dev/dbt-ci/pull/13),
  [`893b299`](https://github.com/datablock-dev/dbt-ci/commit/893b299e8bef524b9102df57db84991dcd39fbef))

* feat: Refactor Slack client initialization and message sending logic

* Refactor code to use built-in `dict` type annotations and improve logging for initialization and
  migration processes

- Updated type annotations from `Dict` and `List` to built-in `dict` and `list` for consistency and
  clarity across multiple files. - Introduced `init_summary` function in `init.py` to encapsulate
  the summary generation logic, including migration and ephemeral plans. - Enhanced logging to
  provide detailed summaries of state changes, migration plans, and ephemeral plans during
  initialization. - Refactored migration logic in `migration.py` to utilize the new
  `generate_migration_map` function for improved readability and maintainability. - Added a new
  settings file for VSCode to streamline development environment setup.

* fix: Update Slack webhook URL retrieval to use getattr for better error handling

* feat: Enhance test coverage by adding logger patches and improving error handling in delete and
  ephemeral command tests

---------

Co-authored-by: Patrick Tannoury <patrick.tannoury@kivra.com>


## v1.2.0 (2026-02-18)

### Chores

- **release**: 1.2.0 [skip ci]
  ([`8a8ef8e`](https://github.com/datablock-dev/dbt-ci/commit/8a8ef8e15251703248f873c87f21b8228ce7e10c))

### Features

- Enhance filter functionality for test mode in run command
  ([#12](https://github.com/datablock-dev/dbt-ci/pull/12),
  [`0eecabd`](https://github.com/datablock-dev/dbt-ci/commit/0eecabdb79ee80c824ca05cd0b178c7534f5f778))

Co-authored-by: Patrick Tannoury <patrick.tannoury@kivra.com>


## v1.1.0 (2026-02-18)

### Bug Fixes

- Fixing ci ([#10](https://github.com/datablock-dev/dbt-ci/pull/10),
  [`b52f9b0`](https://github.com/datablock-dev/dbt-ci/commit/b52f9b0866cbb79b5dd96fbc6e4eb25627157593))

Co-authored-by: Patrick Tannoury <patrick.tannoury@kivra.com>

- Update ENTRYPOINT in Dockerfile to reference main module
  ([`00808ef`](https://github.com/datablock-dev/dbt-ci/commit/00808efd88a9855e1964697ab2fff155e1bd2150))

### Chores

- **release**: 1.1.0 [skip ci]
  ([`d236ced`](https://github.com/datablock-dev/dbt-ci/commit/d236ced89cdbba361cb553c747035d5dff46907f))

- Enhance CI/CD workflows for automatic releases and multi-version support
  ([`02b0b98`](https://github.com/datablock-dev/dbt-ci/commit/02b0b98fa1bdeff56b3ea584ffa6d6c46e0e1b42))

- Remove concurrency settings from tests workflow
  ([`590eeb9`](https://github.com/datablock-dev/dbt-ci/commit/590eeb974c6bf22d29684ed973b34fed29e74923))

- Update CI/CD workflows to improve concurrency and fix GitHub token usage
  ([`c88c763`](https://github.com/datablock-dev/dbt-ci/commit/c88c763b7524a6787a048ff1dbc5d91ede70ee6d))

- Remove tag trigger from CI/CD pipeline
  ([`a30e10f`](https://github.com/datablock-dev/dbt-ci/commit/a30e10f80ced19e5a441f8d605dd0feb65b5551c))

### Documentation

- Update installation instructions for GitHub to clarify version installation
  ([`a5e73c9`](https://github.com/datablock-dev/dbt-ci/commit/a5e73c926ace55ec36cd2c1eccc14839d7c98a4c))

### Features

- Add steps to build and publish package to PyPI in workflow
  ([#9](https://github.com/datablock-dev/dbt-ci/pull/9),
  [`58bd9c4`](https://github.com/datablock-dev/dbt-ci/commit/58bd9c41ec119147c3d0c7b91d4a26be07a20e1b))

Co-authored-by: Patrick Tannoury <patrick.tannoury@kivra.com>

- Enhance logging for ephemeral command and improve error handling in run command
  ([#6](https://github.com/datablock-dev/dbt-ci/pull/6),
  [`2e18647`](https://github.com/datablock-dev/dbt-ci/commit/2e18647229e70632e2d7a3358287d08a967ccf8f))

Co-authored-by: Patrick Tannoury <patrick.tannoury@kivra.com>

- Enhance logging for ephemeral command and improve error handling in run command
  ([#5](https://github.com/datablock-dev/dbt-ci/pull/5),
  [`63bde7a`](https://github.com/datablock-dev/dbt-ci/commit/63bde7a674f044a37dee55881e6b2719c360ae2a))

Co-authored-by: Patrick Tannoury <patrick.tannoury@kivra.com>

- Update Semantic Release action and remove redundant publish steps
  ([`18f9696`](https://github.com/datablock-dev/dbt-ci/commit/18f969658f5102370ec1379e3635ca62caed5772))

### Refactoring

- Rename production_target to reference_target in init command and update related documentation
  ([`55e9027`](https://github.com/datablock-dev/dbt-ci/commit/55e9027c15332923b7740a98f37374d7f0ace2a2))


## v1.0.0 (2026-02-13)

### Bug Fixes

- Update GitHub token to use SEMANTIC_RELEASE_TOKEN in publish workflow
  ([`767bb83`](https://github.com/datablock-dev/dbt-ci/commit/767bb83771f282cf3826b84a05e189daf0dd1944))

- Remove 'quiet' argument from run_dbt_command in DbtGraph class
  ([`36de14b`](https://github.com/datablock-dev/dbt-ci/commit/36de14b1941b1ca956e626cfd7f9fbdfefa85cfb))

- Remove unused import of CLIArgs from variables module
  ([`b9f9e78`](https://github.com/datablock-dev/dbt-ci/commit/b9f9e78ebf25b938c0c034ad578850662aa0e382))

- Remove unused import of get_nodes from delete.py
  ([`35f9b4b`](https://github.com/datablock-dev/dbt-ci/commit/35f9b4b0fb14bd4ac17fb824c35639f56e26bc82))

- Update file permissions for install script and add py-modules entry in pyproject.toml
  ([`b4d665b`](https://github.com/datablock-dev/dbt-ci/commit/b4d665b1d9594826a40f6fc14ef308fba3adf9cb))

- Handle case when no downstream dependencies are found and improve output formatting
  ([`6adeda0`](https://github.com/datablock-dev/dbt-ci/commit/6adeda0619484aa9293cc8dc4a3505424484cc6e))

### Chores

- **release**: 1.0.0 [skip ci]
  ([`ba50bcf`](https://github.com/datablock-dev/dbt-ci/commit/ba50bcff7d6071b991ec70140277081d8263467b))

### Features

- Update publish workflow to include root_options for semantic release and adjust checkout step
  ([`bda4505`](https://github.com/datablock-dev/dbt-ci/commit/bda4505d3fe067242acd657798e69229d2d9285a))

- Add root_options to Python Semantic Release for no-commit option
  ([`75773af`](https://github.com/datablock-dev/dbt-ci/commit/75773afc2019467e22e377c44b7495cb85248eb8))

- Import filter_node_ids_by_type utility in ephemeral command
  ([`10fcf98`](https://github.com/datablock-dev/dbt-ci/commit/10fcf98c4c27dea8f3877f7882b8952b40d92e36))

- Refactor ephemeral command to filter modified nodes by type; remove unused ephemeral environment
  workflow
  ([`14f54bb`](https://github.com/datablock-dev/dbt-ci/commit/14f54bba5127831218a7f34d4c6e0524531599c8))

- Update logging format and add skip_target option in dbt command arguments; enhance error handling
  in docker runner
  ([`ce1da14`](https://github.com/datablock-dev/dbt-ci/commit/ce1da1496bf963172958046a51503909897d944c))

- Add logging to ephemeral and init commands, enhance error handling, and introduce migration
  command
  ([`b3b742b`](https://github.com/datablock-dev/dbt-ci/commit/b3b742bf78c8d4bff2ed26bf731562574ad1bc8e))

- Improve output formatting for modified nodes in run command and streamline node processing logic
  ([`860fc5f`](https://github.com/datablock-dev/dbt-ci/commit/860fc5f1f321c8fa85adb36b3b5ce8fc57798356))

- Add handling for new nodes in dbt run command
  ([`9a99c3d`](https://github.com/datablock-dev/dbt-ci/commit/9a99c3d70476c7984ca58ab0e10fea404ffa9ad3))

- Enhance volume handling in Docker runner to support read/write modes
  ([`3ce0257`](https://github.com/datablock-dev/dbt-ci/commit/3ce02577ce656f43053077e81a85651673ee9825))

- Enhance Docker runner with environment variable and volume management functions
  ([`62d7d9b`](https://github.com/datablock-dev/dbt-ci/commit/62d7d9b47adb6ddd62e80297fa8ad56e27272039))

- Refactor runner functions to use RunnerConfig and enhance command options for Docker
  ([`eca3b54`](https://github.com/datablock-dev/dbt-ci/commit/eca3b54cf26166a3acf085765ff90d5a90ac6786))

- Enhance command output with descriptive messages and improve error handling in Docker runner
  ([`6e6744a`](https://github.com/datablock-dev/dbt-ci/commit/6e6744a8713b9a33edaee7c7b5d44e0a1deb15b3))

- Add CODEOWNERS file to define code ownership and review assignments
  ([`a406c5a`](https://github.com/datablock-dev/dbt-ci/commit/a406c5a190ac158094ac3f38cdae05a33d4f856e))

- Update dbt-core version in Pipfile, pyproject.toml, and requirements.txt to 1.10.13; implement
  delete command with cache handling and dry run support
  ([`37ecb1e`](https://github.com/datablock-dev/dbt-ci/commit/37ecb1e256142f2fb52de7d19ce4122f48c99196))

- Update dependency specifications in Pipfile, pyproject.toml, and requirements.txt for consistency
  and clarity
  ([`c37e33e`](https://github.com/datablock-dev/dbt-ci/commit/c37e33e68f39ecb68bfd7aa443cb78d8dbad1e7a))

- Add delete command to remove modified dbt models and update command imports
  ([`e2db73b`](https://github.com/datablock-dev/dbt-ci/commit/e2db73b69b67586675d7cc065f78fbf7d59165e0))

- Implement BigQuery ephemeral strategy and enhance ephemeral command for improved model handling
  ([`7062a91`](https://github.com/datablock-dev/dbt-ci/commit/7062a91f1cbd11678384da4178890446d2b4293d))

- Enhance ephemeral command to skip non-materialized models and add materialization details to
  dependency graph
  ([`194897c`](https://github.com/datablock-dev/dbt-ci/commit/194897cf800daccd8a53345cd4a095e40701b567))

- Add keep-env option to ephemeral command and refactor dependency graph getters
  ([`d88b4b5`](https://github.com/datablock-dev/dbt-ci/commit/d88b4b50f64fe7a06eb174980d6d180af9911c7b))

- Add connector type validation in ephemeral command and enhance target resolution in Variables
  class
  ([`13c860b`](https://github.com/datablock-dev/dbt-ci/commit/13c860b1b2ceefa4e3e1a5f7feca22a9841aff80))

- Improve profile retrieval logic in Variables class to handle missing profiles and configurations
  ([`68e1a69`](https://github.com/datablock-dev/dbt-ci/commit/68e1a69596e97ffe093c606623dbfcf0cdf4f1a6))

- Enhance ephemeral command to utilize user production state and streamline cache handling
  ([`af85a9d`](https://github.com/datablock-dev/dbt-ci/commit/af85a9d77b224f63ddcb7530161a66a12ad8b40a))

- Improve state change summary output in init command and optimize node comparison logic
  ([`cabe52a`](https://github.com/datablock-dev/dbt-ci/commit/cabe52a4b4ee64fae7bdcf8b992f69ac00c59649))

- Add functionality to identify new nodes in dependency graphs and enhance init command output
  ([`2d0fb7e`](https://github.com/datablock-dev/dbt-ci/commit/2d0fb7ec9fd50eaeae4b138a1cde26511d99c4cd))

- Enhance output for modified nodes and downstream dependencies in run_with_mode function
  ([`28b65ed`](https://github.com/datablock-dev/dbt-ci/commit/28b65ede954034411413b22539f767cbb242de19))

- Add filtering utility for node IDs by type and enhance mode mapping for downstream dependencies
  ([`04c1951`](https://github.com/datablock-dev/dbt-ci/commit/04c1951e05f53267d64bbae01bfc181daabd3f4a))

- Refactor CLI implementation to use Click for command handling and add caching functionality
  ([`8d29aff`](https://github.com/datablock-dev/dbt-ci/commit/8d29affb93ed795766ba0b962a16f9bd06afef3f))

- Enhance BigQuery integration and add multithreading utility for concurrent execution
  ([`3954efe`](https://github.com/datablock-dev/dbt-ci/commit/3954efe36ac29f71ae50485a46b98539b622e4a9))

- Add state argument to main function and update dbt runner command handling
  ([`24ae11c`](https://github.com/datablock-dev/dbt-ci/commit/24ae11c4360ae9f292652054a3c4266432fd4747))

- Implement centralized dbt command dispatcher and enhance runner configuration
  ([`38a4a01`](https://github.com/datablock-dev/dbt-ci/commit/38a4a01a9ff91fc275f33473330c283f08dfe3d2))

- Add dbt runner functionality and update main.py to support new runner option
  ([`853da1d`](https://github.com/datablock-dev/dbt-ci/commit/853da1d201ce9a3e5483511a4c11d909b6ddefa5))

- Add Slack messaging functionality and ephemeral environment management
  ([`7374380`](https://github.com/datablock-dev/dbt-ci/commit/7374380bd9c5355fc2018ca62b171f48fcaad628))

- Update DbtGraph and generate_dependency_graph to support state manifest handling
  ([`f1f3ac0`](https://github.com/datablock-dev/dbt-ci/commit/f1f3ac0c6f2824b48442294fc58e24df8151b3db))

- Enhance DbtGraph initialization to support production state comparison and improve dependency
  graph generation
  ([`117ee81`](https://github.com/datablock-dev/dbt-ci/commit/117ee8101ad5bc331d80a854c44f5159dfdb8e42))

- Simplify metadata handling in generate_dependency_graph function
  ([`d0d39b2`](https://github.com/datablock-dev/dbt-ci/commit/d0d39b2cc12cefd7e699a0c1c2fdd5c908880a92))

- Enhance path handling in DbtGraph for improved runner compatibility
  ([`77faa0c`](https://github.com/datablock-dev/dbt-ci/commit/77faa0c226f838c01d2cec00f0adaa32870e3c6e))

- Improve entrypoint handling in DbtGraph for command execution
  ([`7acadf2`](https://github.com/datablock-dev/dbt-ci/commit/7acadf212da74cdbecc1344a4f49d6d1072c090b))

- Add entrypoint argument to customize dbt command execution in main function
  ([`947ac8a`](https://github.com/datablock-dev/dbt-ci/commit/947ac8a8bd37d24fcc35ffa28e06c8dea34caa28))

- Update bash runner to support custom shell path and enhance command execution
  ([`6e06805`](https://github.com/datablock-dev/dbt-ci/commit/6e068054a0a591279fbb5ec6daa747eef5e0f33f))

- Integrate bash_runner into main function and enhance error handling
  ([`7a4c2b1`](https://github.com/datablock-dev/dbt-ci/commit/7a4c2b1db45e6ce9b1f554c1726968285938927c))

- Update Dockerfile to set correct working directory and copy dbt project to /dbt
  ([`e2dfed4`](https://github.com/datablock-dev/dbt-ci/commit/e2dfed43db8b9723f6a5a37f154caf16d1732627))

- Update Dockerfile to set working directory and copy dbt project; install dbt-duckdb
  ([`845148d`](https://github.com/datablock-dev/dbt-ci/commit/845148d740ac2ea59cabe94066b7c56fbc10c873))

- Enhance bash runner to support custom dbt binary and update command execution; add Dockerfile for
  container setup
  ([`ba1ad4f`](https://github.com/datablock-dev/dbt-ci/commit/ba1ad4fbeb8fd5ca5fb62435d693c154a9cbef85))

- Introduce bash runner and refactor existing runners; update CLI for new shell path option
  ([`4792523`](https://github.com/datablock-dev/dbt-ci/commit/479252347430375a9dd9c393923a668da38e0e70))

- Add support for Docker platform specification and update README with installation instructions
  ([`61ddf9c`](https://github.com/datablock-dev/dbt-ci/commit/61ddf9cbc094b7396668fc4965d2c6df5fb31d5f))

- Clean up DbtGraph and runners by removing redundant code and comments
  ([`d7ac2eb`](https://github.com/datablock-dev/dbt-ci/commit/d7ac2eb62ac9175c9c08a21f10ec5db2d725ece9))

- Add Docker runner support and enhance CLI argument handling in main.py and README
  ([`4df1b32`](https://github.com/datablock-dev/dbt-ci/commit/4df1b3252d7fc8dd80b19078307781760a9b6ea4))

- Enhance DbtGraph to return modified node names and update main to print changes
  ([`ca908fd`](https://github.com/datablock-dev/dbt-ci/commit/ca908fd581ebad8e33c7a8213ad7ae4dc29aad68))

- Refactor target setting and enhance local_runner with quiet mode
  ([`c47d059`](https://github.com/datablock-dev/dbt-ci/commit/c47d059c85d2f0345508bf6816ca41df7f3b6c92))

- Convert paths to absolute in DbtGraph and enhance local_runner output
  ([`794f9bc`](https://github.com/datablock-dev/dbt-ci/commit/794f9bc1da39e77b90a2e9119981db436e52444c))

- Enhance target handling in DbtGraph and update local_runner return type
  ([`4153501`](https://github.com/datablock-dev/dbt-ci/commit/4153501c705b05f2b322047f5bc51bc7a2011287))

- Update argument parsing and enhance DbtGraph functionality with production manifest handling
  ([`abb64b6`](https://github.com/datablock-dev/dbt-ci/commit/abb64b694ac055d00972f750675c41eb27b0672c))

- Implement DBT CI Tool CLI and core functionality
  ([`f53b89f`](https://github.com/datablock-dev/dbt-ci/commit/f53b89f2ace7323e60c8c433ae6285cebbbb9002))

- Added main.py for command-line interface with argument parsing for DBT CI Tool. - Introduced
  src/connectors for BigQuery client integration. - Created src/dependency_graph for managing and
  exporting DBT dependency graphs. - Developed src/parser for generating dependency graphs from
  manifest files. - Implemented error handling and logging options in the CLI.

- Implement command-line argument parsing and installation script for dbt-ci tool
  ([`25bbf24`](https://github.com/datablock-dev/dbt-ci/commit/25bbf24dec6e2fc9f8f50dedc199a7b65e692eb2))

- Initialize dbt-ci project with Poetry and create CLI structure
  ([`c1ea400`](https://github.com/datablock-dev/dbt-ci/commit/c1ea400cd30400d3475aedc2fb339b818fd1584a))

- Added pyproject.toml for dependency management using Poetry. - Created requirements.txt for
  package installation. - Implemented CLI argument parsing in src/cli.py. - Developed main entry
  point in src/main.py. - Added functions to handle dbt project and profiles file paths in
  src/paths.py. - Created local runner for executing dbt commands in src/runners/local.py. - Defined
  TypedDict structures for dbt manifest and CLI arguments in src/schema.py. - Set up initial package
  structure in src and runners directories.

### Refactoring

- Remove unnecessary comments in ephemeral command for cleaner code
  ([`4243a35`](https://github.com/datablock-dev/dbt-ci/commit/4243a35be5f0ac09f91ed9445954da4ea7af4573))

- Simplify node comparison logic in get_deleted_nodes and get_new_nodes functions
  ([`ca38756`](https://github.com/datablock-dev/dbt-ci/commit/ca38756f180520527225050aecf6b52ab7428bea))

- Simplify downstream dependency handling and clean up unused imports
  ([`5af0aa1`](https://github.com/datablock-dev/dbt-ci/commit/5af0aa1847020c6b6e108eb35b89d6496d79197e))

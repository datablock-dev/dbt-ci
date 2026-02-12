"""
Module to manage resolution of configuration from environment variables and command-line flags.

This module defines a Variables class that resolves configuration values with the following precedence:
1. Command-line flags (highest priority)
2. Environment variables
3. Default values (lowest priority)

The class also validates required fields and provides easy access to all resolved configuration.
"""
import os
import sys
from argparse import Namespace
from typing import Any, Dict, Optional
from src.variables.config import OPTIONS_CONFIG
from src.utilities.paths import (
    get_dbt_project_file,
    get_manifest_file,
    get_reference_manifest_file,
    get_profiles_file
)


class Variables:
    """
    Resolve and validate configuration from multiple sources.
    
    Precedence order: CLI flags > Environment variables > Defaults
    
    Example:
        args = Namespace(reference_state='./state', runner=None, ...)
        vars = Variables(args)
        
        # Access resolved values
        state_dir = vars.reference_state
        runner = vars.runner  # Will use env var or default if flag not set
    """

    def __init__(self, args: Namespace):
        self.args = args
        self._resolved = {}
        self._missing_required = []

        # Resolve all configuration options
        for option_name, config in OPTIONS_CONFIG.items():
            resolved_value = self._resolve_option(option_name, config)
            self._resolved[option_name] = resolved_value if resolved_value != "" else None
            setattr(self, option_name, self._resolved[option_name])
            # Track missing required fields
            if config.get('required') and resolved_value is None:
                self._missing_required.append(option_name)

        # Validate required fields
        if self._missing_required:
            self._raise_missing_required()

        # Variables requiring helper functions to resolve value
        self._resolved["project"] = get_dbt_project_file(self.dbt_project_dir)
        self._resolved["target_manifest_file"] = get_manifest_file(self.dbt_project_dir)
        self._resolved["reference_manifest_file"] = get_reference_manifest_file(self.reference_state)
        self._resolved["profile"] = get_profiles_file(self.dbt_project_dir, self.profiles_dir)
        
        # Get target info (call once to avoid recomputing)
        target_info = self._set_target()
        self._resolved["target"] = target_info["target_name"]
        self._resolved["target_config"] = target_info["config"]

        for variable_name, value in self._resolved.items():
            setattr(self, variable_name, value)

    def _resolve_option(self, option_name: str, config: Dict) -> Any:
        """
        Resolve a single option value from flags, env vars, or defaults.
        
        Precedence: CLI flags > Environment variables > Default value
        """
        # Try CLI flags first
        for flag_name in config.get('cli_flags', []):
            if hasattr(self.args, flag_name):
                value = getattr(self.args, flag_name)
                if value is not None:
                    return self._convert_type(value, config.get('type'))

        # Try environment variables
        for env_var in config.get('env_vars', []):
            if env_var in os.environ:
                env_value = os.environ[env_var]
                if env_value:  # Not empty string
                    return self._convert_type(env_value, config.get('type'))
        
        # Return default value
        return config.get('default')
    
    def _convert_type(self, value: str, type_hint: Optional[str]) -> Any:
        """Convert string values to appropriate types."""
        if type_hint == 'bool':
            if isinstance(value, bool):
                return value
            return value.lower() in ('true', '1', 'yes', 'on')
        elif type_hint == 'list':
            # Handle list types - can come from Click (tuple) or env vars (comma-separated)
            if isinstance(value, (list, tuple)):
                return list(value)
            # Split comma-separated env var values
            if isinstance(value, str) and value:
                return [v.strip() for v in value.split(',') if v.strip()]
            return []
        return value
    
    def _raise_missing_required(self):
        """Raise error for missing required fields with helpful message."""
        missing_fields = []
        for field in self._missing_required:
            config = OPTIONS_CONFIG[field]
            flags = ', '.join([f'--{f.replace("_", "-")}' for f in config['cli_flags']])
            envs = ', '.join(config['env_vars'])
            missing_fields.append(f"  • {field}: {flags} or env {envs}")
        
        error_msg = (
            "❌ Missing required configuration:\n"
            + "\n".join(missing_fields)
            + "\n\nProvide values via CLI flags or environment variables."
        )
        print(error_msg, file=sys.stderr)
        sys.exit(1)

    def _set_target(self):
        """Set the target from args if provided, otherwise get from profile."""
        # If target is explicitly provided, we still need to get the config from profile
        if self._resolved["target"] and self._resolved["target"] != "default":
            target_name = self._resolved["target"]
            # Get profile info to retrieve the config for the specified target
            profile_name = self._resolved["project"].get("profile", "")
            profile_config = self._resolved["profile"].get(profile_name, {})
            outputs = profile_config.get("outputs", {})
            
            return {
                "target_name": target_name,
                "config": outputs.get(target_name, {})
            }
        
        return self._get_target_profile()
        
    def _get_target_profile(self) -> Dict:
        """Get the default profile from the profiles.yml file."""
        # Get profile name from dbt_project.yml
        profile_name = self._resolved["project"].get("profile", "")
        
        if not profile_name:
            raise ValueError("No 'profile' key found in dbt_project.yml")
        
        # Get the profile configuration from profiles.yml
        profile_config = self._resolved["profile"].get(profile_name, {})
        
        if not profile_config:
            raise ValueError(f"Profile '{profile_name}' not found in profiles.yml")
        
        target = profile_config.get("target", "")
        outputs = profile_config.get("outputs", {})

        return {
            "config": outputs.get(target, {}),
            "target_name": target
        }
    
    def __getattr__(self, name: str) -> Any:
        """Allow attribute access to resolved values."""
        if name.startswith('_'):
            return object.__getattribute__(self, name)
        
        if name in self._resolved:
            return self._resolved[name]
        
        raise AttributeError(f"No configuration option: {name}")
    
    def get(self, name: str, default=None) -> Any:
        """Get a resolved value with optional default."""
        return self._resolved.get(name, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """Return all resolved values as a dictionary."""
        return self._resolved.copy()
    
    def to_namespace(self) -> Namespace:
        """Convert resolved values back to Namespace for compatibility."""
        return Namespace(**self._resolved)
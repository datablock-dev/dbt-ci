"""Utility function to convert kwargs dict to argparse.Namespace for easier access and compatibility with existing code"""
import yaml
import os
import logging
from argparse import Namespace

logger = logging.getLogger(__name__)

def to_namespace(kwargs, command=None):
    """Convert kwargs dict to argparse.Namespace for easier access and compatibility with existing code"""
    if command:
        kwargs["command"] = command
    
    return parse_config(Namespace(**kwargs))

# Add validation for the config file to ensure that it is structured correctly
def parse_config(args: Namespace) -> Namespace:
    """Parse dbt-ci configuration file and merge with command-line args"""    
    config_path: str = getattr(args, "config")
    
    if not os.path.exists(config_path):
        logger.debug(f"Configuration file '{config_path}' not found. Proceeding with command-line arguments only.")
        return args
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config: dict = yaml.safe_load(f)
    
    print(config)
    return args

    # Merge config with args, giving precedence to command-line args
    for key, value in config.items():
        if not hasattr(args, key) or getattr(args, key) is None:
            setattr(args, key, value)
    
    return args
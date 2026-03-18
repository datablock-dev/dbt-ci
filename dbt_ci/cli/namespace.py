"""Utility function to convert kwargs dict to argparse.Namespace for easier access and compatibility with existing code"""
import logging
from argparse import Namespace

logger = logging.getLogger(__name__)

def to_namespace(kwargs, command=None):
    """Convert kwargs dict to argparse.Namespace for easier access and compatibility with existing code"""
    if command:
        kwargs["command"] = command
    
    return Namespace(**kwargs)
"""
ElastiCache Hot Shard Monitor

A comprehensive toolkit for debugging hot shard issues and analyzing 
uneven distribution in AWS ElastiCache clusters.
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("elasticache-monitor")
except PackageNotFoundError:
    __version__ = "dev"  # Running from source without install

__author__ = "Kratik Jain"

from .monitor import ShardMonitor
from .endpoints import get_replica_endpoints
from .analyzer import analyze_log_file
from .reporter import print_comparison_report, save_report

__all__ = [
    "ShardMonitor",
    "get_replica_endpoints",
    "analyze_log_file",
    "print_comparison_report",
    "save_report",
]


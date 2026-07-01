"""
DEPRECATED — memory_store.py

This file has been merged into memory.py (unified memory system).
It is kept here as a stub to avoid import errors.
All remember/recall/forget calls now route through extensions/memory.py.
"""
import logging
log = logging.getLogger("jarvis.ext.memory_store")


def register(brain):
    log.info("memory_store.py is deprecated — memory.py handles all storage now.")

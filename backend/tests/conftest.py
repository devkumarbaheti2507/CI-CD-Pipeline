import sys
import os

# Allow tests to import modules from the parent backend/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

# Import the individual FastAPI app instances
from failure_classifier import app as classifier_app
from recovery_manager import app as recovery_app
from notification_service import app as notification_app
from github_adapter import app as github_app


@pytest.fixture(scope="session")
def classifier_client():
    """TestClient for the Failure Classifier service."""
    with TestClient(classifier_app, raise_server_exceptions=True) as client:
        yield client


@pytest.fixture(scope="session")
def recovery_client():
    """TestClient for the Recovery Manager service."""
    with TestClient(recovery_app, raise_server_exceptions=True) as client:
        yield client


@pytest.fixture(scope="session")
def notification_client():
    """TestClient for the Notification Service."""
    with TestClient(notification_app, raise_server_exceptions=True) as client:
        yield client


@pytest.fixture(scope="session")
def github_client():
    """TestClient for the GitHub Adapter."""
    with TestClient(github_app, raise_server_exceptions=True) as client:
        yield client

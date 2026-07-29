import os

# Set dummy env vars for testing before any app modules are imported
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["NVIDIA_API_KEY"] = "dummy-key-for-testing"

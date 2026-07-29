import pytest
from fastapi.testclient import TestClient
import requests
from main import app

client = TestClient(app)

def test_extract_receipt_success(mocker):
    # Mock the requests.post to NVIDIA NIM
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"merchant_name": "Test Store", "category": "Food", "items": [{"item": "Coffee", "quantity": 1, "price": 20000}], "total_amount": 20000, "currency": "IDR"}'
                }
            }
        ]
    }
    mocker.patch("requests.post", return_value=mock_response)
    
    # Upload a dummy image
    response = client.post(
        "/extract-receipt",
        files={"file": ("test.jpg", b"dummy image data", "image/jpeg")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["items"][0]["item"] == "Coffee"
    assert data["data"]["items"][0]["price"] == 20000.0

def test_extract_receipt_timeout(mocker):
    # Mock requests.post to raise a Timeout exception
    mocker.patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out"))
    
    response = client.post(
        "/extract-receipt",
        files={"file": ("test.jpg", b"dummy image data", "image/jpeg")}
    )
    
    assert response.status_code == 502
    assert "timeout" in response.json()["detail"].lower()

def test_extract_receipt_nvidia_429(mocker):
    # Mock 429 Too Many Requests
    mock_response = mocker.Mock()
    mock_response.status_code = 429
    mock_response.text = "Too Many Requests"
    mocker.patch("requests.post", return_value=mock_response)
    
    response = client.post(
        "/extract-receipt",
        files={"file": ("test.jpg", b"dummy image data", "image/jpeg")}
    )
    
    assert response.status_code == 503
    assert "sibuk" in response.json()["detail"].lower()

def test_extract_receipt_unreadable(mocker):
    # Mock the response to return no items, triggering the fallback failure
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"items": [], "total_amount": 0}'
                }
            }
        ]
    }
    mocker.patch("requests.post", return_value=mock_response)
    
    response = client.post(
        "/extract-receipt",
        files={"file": ("test.jpg", b"dummy image data", "image/jpeg")}
    )
    
    assert response.status_code == 400
    assert "tidak terbaca jelas" in response.json()["detail"].lower()

#!/usr/bin/env python3
"""
Test script for AWS Textract integration with Ghana Card processing
"""

import os
import sys
import json
import django
from pathlib import Path
from datetime import datetime

# Add the Backend directory to Python path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.conf import settings
from users.aws_textract_service import AWSTextractService
from users.ghana_card_textract_service import GhanaCardTextractService
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_aws_configuration():
    """Test Backblaze B2 and Tesseract OCR configuration"""
    print("=" * 60)
    print("TESTING BACKBLAZE B2 & TESSERACT CONFIGURATION")
    print("=" * 60)

    b2_config = {
        'B2_APPLICATION_KEY_ID': getattr(settings, 'B2_APPLICATION_KEY_ID', None),
        'B2_APPLICATION_KEY': '***' if getattr(settings, 'B2_APPLICATION_KEY', None) else None,
        'B2_ENDPOINT_URL': getattr(settings, 'B2_ENDPOINT_URL', None),
        'B2_BUCKET_NAME': getattr(settings, 'B2_BUCKET_NAME', None),
    }

    print("Backblaze B2 Configuration:")
    for key, value in b2_config.items():
        status = "[SET]" if value else "[NOT SET]"
        print(f"  {key}: {status}")

    # Checking Tesseract engine setting
    engine = getattr(settings, 'DOCUMENT_PROCESSING_ENGINE', None)
    print(f"  DOCUMENT_PROCESSING_ENGINE: {engine}")

    return True


def test_textract_service_initialization():
    """Test local Tesseract OCR & Backblaze B2 service initialization"""
    print("\n" + "=" * 60)
    print("TESTING TESSERACT OCR & B2 SERVICE INITIALIZATION")
    print("=" * 60)

    try:
        textract_service = AWSTextractService()
        print("[OK] Local Tesseract OCR service initialized successfully")

        # Test Tesseract system binary installation
        try:
            import pytesseract
            version = pytesseract.get_tesseract_version()
            print(f"[OK] pytesseract package is installed and can locate Tesseract binary (version: {version})")
        except Exception as e:
            print(f"[ERROR] pytesseract was unable to find or run Tesseract on your path: {str(e)}")
            print("  Please make sure 'tesseract-ocr' is installed on your OS.")

        try:
            is_valid = textract_service.validate_aws_credentials()
            if is_valid:
                print("[OK] Backblaze B2 credentials validated successfully")
            else:
                print("[ERROR] Backblaze B2 credential validation failed")
        except Exception as e:
            print(f"[ERROR] Backblaze B2 credential validation failed: {str(e)}")

        return True

    except Exception as e:
        print(f"[ERROR] Failed to initialize local OCR service: {str(e)}")
        return False


def test_ghana_card_service_initialization():
    """Test Ghana Card service initialization"""
    print("\n" + "=" * 60)
    print("TESTING GHANA CARD SERVICE INITIALIZATION")
    print("=" * 60)

    try:
        ghana_service = GhanaCardTextractService()
        print("[OK] Ghana Card service initialized successfully")

        if hasattr(ghana_service, 'textract_service') and ghana_service.textract_service:
            print("   [OK] Local OCR service available")
        else:
            print("   [ERROR] Local OCR service not available - this is required")
            return False

        return True

    except Exception as e:
        print(f"[ERROR] Failed to initialize Ghana Card service: {str(e)}")
        return False


def test_import_structure():
    """Test that all imports work correctly"""
    print("\n" + "=" * 60)
    print("TESTING IMPORT STRUCTURE")
    print("=" * 60)

    try:
        from users.aws_textract_service import aws_textract_service
        print("[OK] AWS Textract service import successful")
    except Exception as e:
        print(f"[ERROR] AWS Textract service import failed: {str(e)}")

    try:
        from users.ghana_card_textract_service import ghana_card_textract_service
        print("[OK] Ghana Card Textract service import successful")
    except Exception as e:
        print(f"[ERROR] Ghana Card Textract service import failed: {str(e)}")

    # OCR fallback service has been removed - using only AWS Textract

    try:
        import boto3
        print(f"[OK] boto3 imported successfully (version: {boto3.__version__})")
    except Exception as e:
        print(f"[ERROR] boto3 import failed: {str(e)}")


# ---------- New Ghana Card Tests (Front / Back) ----------

def test_process_ghana_card_full(front_image_path, back_image_path):
    """Test processing complete Ghana Card (both front and back)"""
    print("\n" + "=" * 60)
    print("TESTING COMPLETE GHANA CARD PROCESSING")
    print("=" * 60)

    if not os.path.exists(front_image_path):
        print(f"[ERROR] Front image not found: {front_image_path}")
        return {}
        
    if not os.path.exists(back_image_path):
        print(f"[ERROR] Back image not found: {back_image_path}")
        return {}

    try:
        service = GhanaCardTextractService()
        
        # Open image files
        with open(front_image_path, 'rb') as front_file:
            with open(back_image_path, 'rb') as back_file:
                # Test with sample user data
                result = service.process_ghana_card_enterprise(
                    front_file, 
                    back_file,
                    first_name="John",
                    last_name="Doe", 
                    ghana_card_number="GHA-123456789-1"
                )

        print("Ghana Card Processing Result:")
        print(json.dumps(result, indent=2, default=str))
        
        # Extract the key information for the API response
        if result.get('success') and result.get('results'):
            extracted_data = {
                "surname": result['results'].get('extracted_name', '').split()[-1] if result['results'].get('extracted_name') else None,
                "firstname": ' '.join(result['results'].get('extracted_name', '').split()[:-1]) if result['results'].get('extracted_name') else None,
                "ghana_card_number": result['results'].get('extracted_number')
            }
            
            print("\n" + "=" * 40)
            print("EXTRACTED DATA FOR API:")
            print("=" * 40)
            print(json.dumps(extracted_data, indent=2))
            return extracted_data
        else:
            print("[ERROR] Processing failed or no results returned")
            return {}

    except Exception as e:
        print(f"[ERROR] Failed to process Ghana Card: {str(e)}")
        return {}


def test_single_image(image_path):
    """Test processing a single Ghana Card image"""
    print("\n" + "=" * 60)
    print("TESTING SINGLE GHANA CARD IMAGE")
    print("=" * 60)

    if not os.path.exists(image_path):
        print(f"[ERROR] File not found: {image_path}")
        return {}

    try:
        service = GhanaCardTextractService()
        
        # For single image test, we'll use it as both front and back
        with open(image_path, 'rb') as image_file:
            # Create a copy for the second parameter
            image_file.seek(0)
            image_data = image_file.read()
            
            from io import BytesIO
            front_file = BytesIO(image_data)
            back_file = BytesIO(image_data)
            
            result = service.process_ghana_card_enterprise(
                front_file, 
                back_file,
                first_name="Test",
                last_name="User", 
                ghana_card_number="GHA-000000000-0"
            )

        print("Single Image Processing Result:")
        print(json.dumps(result, indent=2, default=str))
        return result

    except Exception as e:
        print(f"[ERROR] Failed to process single image: {str(e)}")
        return {}


# ---------- Helpers ----------

def save_json(data, prefix='extracted_card'):
    """Save extracted data to timestamped JSON file"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.json"
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"\n[INFO] Saved extracted data to {filename}")
    except Exception as e:
        print(f"[ERROR] Failed to save JSON: {str(e)}")


def print_setup_instructions():
    print("\n" + "=" * 60)
    print("AWS SETUP INSTRUCTIONS")
    print("=" * 60)
    print("""
1. Create an IAM User with programmatic access
   - Attach AmazonTextractFullAccess + AmazonS3FullAccess

2. Create an S3 Bucket
   - Ensure it's in the same region as Textract

3. Update your .env with:
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   AWS_S3_BUCKET_NAME=...
   AWS_REGION=...

4. Run this script with sample Ghana Card images
   python test_aws_textract.py front.jpg back.jpg
""")


# ---------- Main Runner ----------

def main():
    print("TESTING AWS TEXTRACT INTEGRATION FOR GHANA CARD PROCESSING")

    config_ok = test_aws_configuration()
    test_textract_service_initialization()
    test_ghana_card_service_initialization()
    test_import_structure()

    # Handle Ghana Card test
    if len(sys.argv) > 1:
        if len(sys.argv) == 2:
            # Single file test
            print("\n[INFO] Testing single image...")
            result = test_single_image(sys.argv[1])
            save_json(result, prefix='single_image_test')

        elif len(sys.argv) == 3:
            # Front + Back test
            print("\n[INFO] Testing front + back images...")
            extracted_data = test_process_ghana_card_full(sys.argv[1], sys.argv[2])
            
            print("\nFINAL EXTRACTED DATA (for backend API payload):")
            print(json.dumps(extracted_data, indent=2))
            save_json(extracted_data, prefix='full_card_test')
    else:
        print("\n[INFO] No sample images provided.")
        print("Usage:")
        print("  python test_textract_integration.py /path/to/front.jpg")
        print("  python test_textract_integration.py /path/to/front.jpg /path/to/back.jpg")

    if not config_ok:
        print_setup_instructions()


if __name__ == "__main__":
    main()

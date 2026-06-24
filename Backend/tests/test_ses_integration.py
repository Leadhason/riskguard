#!/usr/bin/env python3
"""
Test script to verify SES integration works correctly.
This script tests the email sending functionality with SES fallback to Django email.
"""

import os
import sys
import django
from pathlib import Path

# Add the project root to the Python path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from users.utils.email import send_email_via_ses
from users.otp_service import EnterpriseOTPService, OTPType
import asyncio
from django.conf import settings
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_ses_email():
    """Test SES email sending functionality"""
    print("Testing SES Email Integration")
    print("=" * 50)
    
    # Test basic SES email sending
    test_email = "klvnafriyie96@gmail.com"  # Verified recipient email
    
    try:
        print(f"Testing basic SES email to: {test_email}")
        
        result = send_email_via_ses(
            subject="SES Integration Test",
            html_message="<h1>Test Email</h1><p>This is a test email from your SES integration.</p>",
            plain_message="Test Email\n\nThis is a test email from your SES integration.",
            recipient_email=test_email
        )
        
        if result:
            print("SUCCESS: SES email test completed successfully!")
        else:
            print("FAILED: SES email test failed!")
            
    except Exception as e:
        print(f"ERROR: Error testing SES email: {str(e)}")
        print("NOTE: This may fail if SES credentials are not configured")

async def test_otp_service():
    """Test OTP service with SES"""
    print("\nTesting OTP Service with SES")
    print("=" * 50)
    
    try:
        otp_service = EnterpriseOTPService()
        test_email = "klvnafriyie96@gmail.com"  # Verified recipient email
        
        print(f"Testing OTP email to: {test_email}")
        
        # This will attempt to send an OTP email
        result = await otp_service.send_otp(test_email, OTPType.EMAIL)
        
        if result.get('success'):
            print("SUCCESS: OTP service test completed successfully!")
            print(f"OTP Code (for testing): {result.get('dev_otp', 'Not shown in production')}")
        else:
            print(f"FAILED: OTP service test failed: {result.get('message', 'Unknown error')}")
            
    except Exception as e:
        print(f"ERROR: Error testing OTP service: {str(e)}")
        print("NOTE: This may fail if SES credentials are not configured")


def check_configuration():
    """Check Resend configuration"""
    print("\nChecking Resend Configuration")
    print("=" * 50)
    
    # Check environment variables
    resend_api_key = getattr(settings, 'RESEND_API_KEY', None)
    resend_from_email = getattr(settings, 'RESEND_FROM_EMAIL', None)
    
    print(f"RESEND_API_KEY: {'Set' if resend_api_key else 'Not set'}")
    print(f"RESEND_FROM_EMAIL: {resend_from_email if resend_from_email else 'Not set'}")
    
    if not resend_api_key or not resend_from_email:
        print("\nWARNING: Some Resend configuration is missing!")
        print("   Please update your .env file with proper Resend settings")
        print("   The system will fall back to Django email backend")
    else:
        print("\nSUCCESS: Resend configuration appears complete!")

async def main():
    """Main test function"""
    print("SES Integration Test Suite")
    print("=" * 50)
    
    check_configuration()
    test_ses_email()
    await test_otp_service()
    
    print("\nTest suite completed!")
    print("=" * 50)
    print("NOTE: To fully test SES, update the test_email variable with a real email address")
    print("   and ensure your SES credentials are properly configured in .env")

if __name__ == "__main__":
    asyncio.run(main())
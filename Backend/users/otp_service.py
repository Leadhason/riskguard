import re
import time
import hashlib
import logging
import secrets
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone
import json

logger = logging.getLogger(__name__)

class OTPType(Enum):
    """Types of OTP verification"""
    EMAIL = "email"
    PHONE = "phone"
    BACKUP = "backup"

class OTPStatus(Enum):
    """OTP verification status"""
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"

@dataclass
class OTPConfig:
    """OTP configuration settings"""
    length: int = 6
    expiry_minutes: int = 10
    max_attempts: int = 3
    rate_limit_window: int = 60
    max_requests_per_window: int = 3
    
class OTPSecurityManager:
    """Advanced security manager for OTP operations"""
    
    @staticmethod
    def generate_secure_otp(length: int = 6) -> str:
        """Generate cryptographically secure OTP"""
        # Use secrets module for cryptographically secure random numbers
        return ''.join([str(secrets.randbelow(10)) for _ in range(length)])
    
    @staticmethod
    def hash_contact_info(contact: str, otp_type: str) -> str:
        """Create secure hash for contact information"""
        salt = settings.SECRET_KEY[:16]  # Use first 16 chars of secret key as salt
        data = f"{contact}:{otp_type}:{salt}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]
    
    @staticmethod
    def validate_contact_format(contact: str, otp_type: OTPType) -> Tuple[bool, str]:
        """Validate contact information format"""
        if otp_type == OTPType.EMAIL:
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(pattern, contact):
                return False, "Invalid email format"
            return True, ""
        
        elif otp_type == OTPType.PHONE:
            # Ghana phone number validation
            clean_phone = re.sub(r'[\s\-\(\)]', '', contact)
            if clean_phone.startswith('+233'):
                pattern = r'^\+233[2-9]\d{8}$'
            elif clean_phone.startswith('0'):
                pattern = r'^0[2-9]\d{8}$'
            else:
                return False, "Phone number must start with +233 or 0"
            
            if not re.match(pattern, clean_phone):
                return False, "Invalid Ghana phone number format"
            return True, ""
        
        return False, "Unsupported contact type"

class OTPDeliveryService:
    """Enterprise-grade OTP delivery service with multiple providers"""
    
    def __init__(self):
        self.email_providers = [
            'resend',       # Primary - Resend API
            'django_smtp',  # Fallback 1
            'sendgrid',     # Fallback 2
        ]
        
        self.sms_providers = [
            'twilio',       # Primary
            'aws_sns',      # Fallback 1
            'hubtel',       # Ghana-specific fallback
        ]
    
    async def send_email_otp(self, email: str, otp: str, template_context: Dict[str, Any]) -> Dict[str, Any]:
        """Send OTP via email with multiple provider fallback"""
        result = {
            'success': False,
            'provider_used': None,
            'delivery_time_ms': 0,
            'error': None
        }
        
        start_time = time.time()
        
        try:
            # Try primary email provider (Resend API)
            success = await self._send_resend_email(email, otp, template_context)
            
            if success:
                result.update({
                    'success': True,
                    'provider_used': 'resend',
                    'delivery_time_ms': (time.time() - start_time) * 1000
                })
                logger.info(f"Email OTP sent successfully via Resend to {email}")
                return result
            
            # Try fallback providers if primary fails
            for provider in self.email_providers[1:]:
                try:
                    if provider == 'django_smtp':
                        success = await self._send_django_email(email, otp, template_context)
                    elif provider == 'sendgrid':
                        success = await self._send_sendgrid_email(email, otp, template_context)
                    
                    if success:
                        result.update({
                            'success': True,
                            'provider_used': provider,
                            'delivery_time_ms': (time.time() - start_time) * 1000
                        })
                        logger.info(f"Email OTP sent successfully via {provider} to {email}")
                        return result
                        
                except Exception as e:
                    logger.warning(f"Email provider {provider} failed: {str(e)}")
                    continue
            
            result['error'] = "All email providers failed"
            logger.error(f"Failed to send email OTP to {email} - all providers failed")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Email OTP sending failed: {str(e)}")
        
        result['delivery_time_ms'] = (time.time() - start_time) * 1000
        return result
    
    async def send_sms_otp(self, phone: str, otp: str, template_context: Dict[str, Any]) -> Dict[str, Any]:
        """Send OTP via SMS with multiple provider fallback"""
        result = {
            'success': False,
            'provider_used': None,
            'delivery_time_ms': 0,
            'error': None
        }
        
        start_time = time.time()
        
        try:
            # Try primary SMS provider (Twilio)
            success = await self._send_twilio_sms(phone, otp, template_context)
            
            if success:
                result.update({
                    'success': True,
                    'provider_used': 'twilio',
                    'delivery_time_ms': (time.time() - start_time) * 1000
                })
                logger.info(f"SMS OTP sent successfully via Twilio to {phone}")
                return result
            
            # Try fallback providers
            for provider in self.sms_providers[1:]:
                try:
                    if provider == 'aws_sns':
                        success = await self._send_aws_sns_sms(phone, otp, template_context)
                    elif provider == 'hubtel':
                        success = await self._send_hubtel_sms(phone, otp, template_context)
                    
                    if success:
                        result.update({
                            'success': True,
                            'provider_used': provider,
                            'delivery_time_ms': (time.time() - start_time) * 1000
                        })
                        logger.info(f"SMS OTP sent successfully via {provider} to {phone}")
                        return result
                        
                except Exception as e:
                    logger.warning(f"SMS provider {provider} failed: {str(e)}")
                    continue
            
            result['error'] = "All SMS providers failed"
            logger.error(f"Failed to send SMS OTP to {phone} - all providers failed")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"SMS OTP sending failed: {str(e)}")
        
        result['delivery_time_ms'] = (time.time() - start_time) * 1000
        return result
    
    async def _send_django_email(self, email: str, otp: str, context: Dict[str, Any]) -> bool:
        """Send email using Django's built-in email system"""
        try:
            # Render HTML template
            html_message = render_to_string('emails/otp_verification.html', {
                'otp_code': otp,
                'user_email': email,
                'expiry_minutes': context.get('expiry_minutes', 10),
                'company_name': 'CreditRisk Assessment Platform',
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@creditrisk.com'),
                **context
            })
            
            # Create plain text version
            plain_message = strip_tags(html_message)
            
            result = send_mail(
                subject=f'Your Verification Code: {otp}',
                message=plain_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@creditrisk.com'),
                recipient_list=[email],
                html_message=html_message,
                fail_silently=False,
            )
            
            return result == 1  # Django send_mail returns 1 on success
            
        except Exception as e:
            logger.error(f"Django email sending failed: {str(e)}")
            return False
    
    async def _send_sendgrid_email(self, email: str, otp: str, context: Dict[str, Any]) -> bool:
        """Send email using SendGrid API (fallback)"""
        try:
            # TODO: Implement SendGrid integration
            # import sendgrid
            # sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
            logger.info(f"SendGrid email fallback not implemented yet for {email}")
            return False
        except Exception as e:
            logger.error(f"SendGrid email failed: {str(e)}")
            return False
    
    async def _send_resend_email(self, email: str, otp: str, context: Dict[str, Any]) -> bool:
        """Send email using Resend API"""
        try:
            import requests
            
            # Get Resend configuration from settings
            resend_api_key = getattr(settings, 'RESEND_API_KEY', None)
            resend_from_email = getattr(settings, 'RESEND_FROM_EMAIL', 'onboarding@resend.dev')
            
            if not resend_api_key:
                logger.warning("Resend API key not configured")
                return False
            
            # Render HTML template
            html_message = render_to_string('emails/otp_verification.html', {
                'otp_code': otp,
                'user_email': email,
                'expiry_minutes': context.get('expiry_minutes', 10),
                'company_name': 'CreditRisk Assessment Platform',
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@creditrisk.com'),
                **context
            })
            
            # Create plain text version
            plain_message = strip_tags(html_message)
            
            # Call Resend REST API
            headers = {
                "Authorization": f"Bearer {resend_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "from": resend_from_email,
                "to": [email],
                "subject": f'Your Verification Code: {otp}',
                "html": html_message,
                "text": plain_message
            }
            
            response = requests.post(
                "https://api.resend.com/emails",
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code in [200, 201, 202]:
                response_data = response.json()
                logger.info(f"Resend email OTP sent successfully to {email}, Id: {response_data.get('id')}")
                return True
            else:
                logger.error(f"Resend API returned error {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Resend email OTP failed: {str(e)}")
            return False
    
    async def _send_twilio_sms(self, phone: str, otp: str, context: Dict[str, Any]) -> bool:
        """Send SMS using Twilio API"""
        try:
            # TODO: Implement Twilio integration
            # from twilio.rest import Client
            # client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            
            message_body = f"""
Your CreditRisk verification code is: {otp}

This code expires in {context.get('expiry_minutes', 10)} minutes.
Do not share this code with anyone.

If you didn't request this, please ignore this message.
            """.strip()
            
            logger.info(f"Twilio SMS not implemented yet for {phone}. Would send: {message_body}")
            return False  # Change to True when implemented
            
        except Exception as e:
            logger.error(f"Twilio SMS failed: {str(e)}")
            return False
    
    async def _send_aws_sns_sms(self, phone: str, otp: str, context: Dict[str, Any]) -> bool:
        """Send SMS using AWS SNS (fallback)"""
        try:
            # TODO: Implement AWS SNS integration
            logger.info(f"AWS SNS SMS fallback not implemented yet for {phone}")
            return False
        except Exception as e:
            logger.error(f"AWS SNS SMS failed: {str(e)}")
            return False
    
    async def _send_hubtel_sms(self, phone: str, otp: str, context: Dict[str, Any]) -> bool:
        """Send SMS using Hubtel API (Ghana-specific fallback)"""
        try:
            # TODO: Implement Hubtel integration for Ghana
            logger.info(f"Hubtel SMS fallback not implemented yet for {phone}")
            return False
        except Exception as e:
            logger.error(f"Hubtel SMS failed: {str(e)}")
            return False

class EnterpriseOTPService:
    """Main OTP service with enterprise-grade features"""
    
    def __init__(self):
        self.config = OTPConfig()
        self.security_manager = OTPSecurityManager()
        self.delivery_service = OTPDeliveryService()
        
    def _get_rate_limit_key(self, contact: str, otp_type: str) -> str:
        """Get rate limiting cache key"""
        contact_hash = self.security_manager.hash_contact_info(contact, otp_type)
        return f"otp_rate_limit:{contact_hash}"
    
    def _get_otp_storage_key(self, contact: str, otp_type: str) -> str:
        """Get OTP storage cache key"""
        contact_hash = self.security_manager.hash_contact_info(contact, otp_type)
        return f"otp_data:{contact_hash}"
    
    def _check_rate_limit(self, contact: str, otp_type: str) -> Tuple[bool, int]:
        """Check if request is rate limited"""
        rate_key = self._get_rate_limit_key(contact, otp_type)
        current_requests = cache.get(rate_key, 0)
        
        if current_requests >= self.config.max_requests_per_window:
            ttl = cache.ttl(rate_key)
            return False, ttl if ttl > 0 else self.config.rate_limit_window
        
        # Increment counter
        cache.set(rate_key, current_requests + 1, self.config.rate_limit_window)
        return True, 0
    
    async def send_otp(self, contact: str, otp_type: OTPType, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send OTP with comprehensive validation and security"""
        result = {
            'success': False,
            'message': '',
            'otp_id': None,
            'expires_in_seconds': 0,
            'delivery_info': {},
            'rate_limit_info': {},
            'security_flags': []
        }
        
        try:
            # 1. Validate contact format
            is_valid, format_error = self.security_manager.validate_contact_format(contact, otp_type)
            if not is_valid:
                result['message'] = format_error
                return result
            
            # 2. Check rate limiting
            can_send, wait_time = self._check_rate_limit(contact, otp_type.value)
            if not can_send:
                result.update({
                    'message': f'Rate limit exceeded. Please wait {wait_time} seconds before requesting another code.',
                    'rate_limit_info': {
                        'rate_limited': True,
                        'wait_time_seconds': wait_time,
                        'max_requests': self.config.max_requests_per_window,
                        'window_seconds': self.config.rate_limit_window
                    }
                })
                return result
            
            # 3. Generate secure OTP
            otp_code = self.security_manager.generate_secure_otp(self.config.length)
            otp_id = secrets.token_urlsafe(32)
            
            # 4. Prepare context
            template_context = {
                'expiry_minutes': self.config.expiry_minutes,
                'max_attempts': self.config.max_attempts,
                'otp_id': otp_id,
                'timestamp': timezone.now().isoformat(),
                **(context or {})
            }
            
            # 5. Send OTP via appropriate channel
            if otp_type == OTPType.EMAIL:
                delivery_result = await self.delivery_service.send_email_otp(contact, otp_code, template_context)
            elif otp_type == OTPType.PHONE:
                delivery_result = await self.delivery_service.send_sms_otp(contact, otp_code, template_context)
            else:
                result['message'] = 'Unsupported OTP type'
                return result
            
            # 6. Store OTP data securely if delivery successful
            if delivery_result['success']:
                otp_data = {
                    'otp_code': otp_code,  # In production, hash this
                    'otp_id': otp_id,
                    'contact': contact,
                    'otp_type': otp_type.value,
                    'attempts_left': self.config.max_attempts,
                    'created_at': timezone.now().isoformat(),
                    'expires_at': (timezone.now() + timedelta(minutes=self.config.expiry_minutes)).isoformat(),
                    'status': OTPStatus.PENDING.value,
                    'delivery_info': delivery_result
                }
                
                storage_key = self._get_otp_storage_key(contact, otp_type.value)
                cache.set(storage_key, json.dumps(otp_data), self.config.expiry_minutes * 60)
                
                # Log successful OTP generation (without the actual code)
                logger.info(f"OTP generated and sent successfully", extra={
                    'otp_id': otp_id,
                    'contact_type': otp_type.value,
                    'provider': delivery_result['provider_used'],
                    'delivery_time_ms': delivery_result['delivery_time_ms']
                })
                
                result.update({
                    'success': True,
                    'message': f'Verification code sent to your {otp_type.value}',
                    'otp_id': otp_id,
                    'expires_in_seconds': self.config.expiry_minutes * 60,
                    'delivery_info': {
                        'provider_used': delivery_result['provider_used'],
                        'delivery_time_ms': delivery_result['delivery_time_ms']
                    }
                })
                
                # Add development convenience (remove in production)
                if getattr(settings, 'DEBUG', False):
                    result['dev_otp'] = otp_code  # For testing only
            else:
                result['message'] = f"Failed to send verification code: {delivery_result.get('error', 'Unknown error')}"
                logger.error(f"OTP delivery failed", extra={
                    'contact_type': otp_type.value,
                    'error': delivery_result.get('error'),
                    'delivery_time_ms': delivery_result['delivery_time_ms']
                })
        
        except Exception as e:
            result['message'] = 'Service temporarily unavailable. Please try again later.'
            logger.error(f"OTP service error: {str(e)}", exc_info=True)
        
        return result
    
    def verify_otp(self, contact: str, otp_type: OTPType, provided_code: str, otp_id: Optional[str] = None) -> Dict[str, Any]:
        """Verify OTP with comprehensive security checks"""
        result = {
            'success': False,
            'verified': False,
            'message': '',
            'attempts_left': 0,
            'security_flags': []
        }
        
        try:
            # 1. Validate input
            if not provided_code or len(provided_code) != self.config.length:
                result['message'] = f'Please enter a {self.config.length}-digit code'
                return result
            
            if not provided_code.isdigit():
                result['message'] = 'Verification code must contain only numbers'
                return result
            
            # 2. Retrieve stored OTP data
            storage_key = self._get_otp_storage_key(contact, otp_type.value)
            stored_data = cache.get(storage_key)
            
            if not stored_data:
                result['message'] = 'Verification code has expired or is invalid'
                return result
            
            otp_data = json.loads(stored_data)
            
            # 3. Check if OTP has expired
            expires_at = datetime.fromisoformat(otp_data['expires_at'])
            if timezone.now() > expires_at:
                cache.delete(storage_key)
                result['message'] = 'Verification code has expired. Please request a new one.'
                return result
            
            # 4. Check attempts left
            if otp_data['attempts_left'] <= 0:
                cache.delete(storage_key)
                result['message'] = 'Too many incorrect attempts. Please request a new code.'
                return result
            
            # 5. Verify OTP code
            if provided_code == otp_data['otp_code']:
                # Success - mark as verified and clean up
                otp_data['status'] = OTPStatus.VERIFIED.value
                otp_data['verified_at'] = timezone.now().isoformat()
                cache.delete(storage_key)
                
                # Log successful verification
                logger.info(f"OTP verified successfully", extra={
                    'otp_id': otp_data['otp_id'],
                    'contact_type': otp_type.value,
                    'attempts_used': self.config.max_attempts - otp_data['attempts_left'] + 1
                })
                
                result.update({
                    'success': True,
                    'verified': True,
                    'message': f'{otp_type.value.title()} verified successfully',
                    'attempts_left': 0
                })
            else:
                # Failed attempt - decrement attempts
                otp_data['attempts_left'] -= 1
                otp_data['last_attempt_at'] = timezone.now().isoformat()
                
                if otp_data['attempts_left'] > 0:
                    # Update stored data with decreased attempts
                    cache.set(storage_key, json.dumps(otp_data), 
                             int((expires_at - timezone.now()).total_seconds()))
                    
                    result.update({
                        'message': f'Incorrect code. {otp_data["attempts_left"]} attempts remaining.',
                        'attempts_left': otp_data['attempts_left']
                    })
                else:
                    # No attempts left - delete and block
                    cache.delete(storage_key)
                    result['message'] = 'Too many incorrect attempts. Please request a new code.'
                
                # Log failed attempt
                logger.warning(f"OTP verification failed", extra={
                    'otp_id': otp_data['otp_id'],
                    'contact_type': otp_type.value,
                    'attempts_left': otp_data['attempts_left']
                })
        
        except Exception as e:
            result['message'] = 'Verification failed. Please try again.'
            logger.error(f"OTP verification error: {str(e)}", exc_info=True)
        
        return result

# Global instance
otp_service = EnterpriseOTPService()
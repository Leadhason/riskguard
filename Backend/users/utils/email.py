from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


def send_email_via_resend(subject, html_message, plain_message, recipient_email, from_email=None):
    """Send email using Resend API with fallback to Django"""
    try:
        import requests
        
        # Get Resend configuration
        resend_api_key = getattr(settings, 'RESEND_API_KEY', None)
        resend_from_email = from_email or getattr(settings, 'RESEND_FROM_EMAIL', 'onboarding@resend.dev')
        
        if not resend_api_key:
            logger.warning("Resend API key not configured, falling back to Django email")
            raise Exception("Resend API key not configured")
        
        # Send email using Resend API
        headers = {
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "from": resend_from_email,
            "to": [recipient_email],
            "subject": subject,
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
            logger.info(f"Resend email sent successfully to {recipient_email}, Id: {response_data.get('id')}")
            return True
        else:
            logger.warning(f"Resend API returned error {response.status_code}: {response.text}")
            raise Exception(f"Resend API error: {response.text}")
            
    except Exception as e:
        logger.warning(f"Resend email failed ({str(e)}), falling back to Django email")
        
        # Fallback to Django email
        try:
            result = send_mail(
                subject=subject,
                message=plain_message,
                from_email=from_email or settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Django email sent successfully to {recipient_email}")
            return result == 1
            
        except Exception as django_error:
            logger.error(f"Both Resend and Django email failed: {str(django_error)}")
            raise

# Backward-compatible alias
send_email_via_ses = send_email_via_resend


def send_welcome_email(user):
    """Send welcome email to new user"""
    try:
        subject = f'Welcome to {getattr(settings, "APP_NAME", "RiskGuard Pro")}'
        
        html_message = render_to_string('emails/welcome.html', {
            'user': user,
            'app_name': getattr(settings, 'APP_NAME', 'RiskGuard Pro'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', settings.DEFAULT_FROM_EMAIL)
        })
        
        plain_message = strip_tags(html_message)
        
        # Use SES with Django fallback
        send_email_via_ses(
            subject=subject,
            html_message=html_message,
            plain_message=plain_message,
            recipient_email=user.email
        )
        
        logger.info(f"Welcome email sent to: {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")
        raise


def send_password_reset_email(user, uid, token, request):
    """Send password reset email"""
    try:
        # Build reset URL (Frontend React app URL)
        frontend_base_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        reset_url = f"{frontend_base_url}/reset-password?uid={uid}&token={token}"
        
        subject = 'Password Reset Request'
        
        html_message = render_to_string('emails/password_reset.html', {
            'user': user,
            'reset_url': reset_url,
            'app_name': getattr(settings, 'APP_NAME', 'RiskGuard Pro'),
            'expiry_hours': 1
        })
        
        plain_message = strip_tags(html_message)
        
        # Use SES with Django fallback
        send_email_via_ses(
            subject=subject,
            html_message=html_message,
            plain_message=plain_message,
            recipient_email=user.email
        )
        
        logger.info(f"Password reset email sent to: {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {user.email}: {str(e)}")
        raise


def send_password_changed_notification(user):
    """Send notification when password is changed"""
    try:
        subject = 'Password Changed Successfully'
        
        html_message = render_to_string('emails/password_changed.html', {
            'user': user,
            'app_name': getattr(settings, 'APP_NAME', 'RiskGuard Pro'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', settings.DEFAULT_FROM_EMAIL)
        })
        
        plain_message = strip_tags(html_message)
        
        # Use SES with Django fallback
        send_email_via_ses(
            subject=subject,
            html_message=html_message,
            plain_message=plain_message,
            recipient_email=user.email
        )
        
        logger.info(f"Password change notification sent to: {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send password change notification to {user.email}: {str(e)}")


def send_mfa_enabled_notification(user):
    """Send notification when MFA is enabled"""
    try:
        subject = 'Multi-Factor Authentication Enabled'
        
        html_message = render_to_string('emails/mfa_enabled.html', {
            'user': user,
            'app_name': getattr(settings, 'APP_NAME', 'RiskGuard Pro'),
        })
        
        plain_message = strip_tags(html_message)
        
        # Use SES with Django fallback
        send_email_via_ses(
            subject=subject,
            html_message=html_message,
            plain_message=plain_message,
            recipient_email=user.email
        )
        logger.info(f"MFA enabled notification sent to: {user.email}")

    except Exception as e:
        logger.error(f"Failed to send MFA enabled notification to {user.email}: {str(e)}")


def send_admin_created_user_email(user, temporary_password, admin_user):
    """Send welcome email to admin-created user with temporary password"""
    try:
        # Get user's primary role for display
        user_roles = user.get_roles()
        user_role = user_roles.first().name if user_roles.exists() else user.user_type
        
        # Build login URL
        frontend_base_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        login_url = f"{frontend_base_url}/"
        
        subject = f'Welcome to {getattr(settings, "APP_NAME", "RiskGuard Pro")} - Account Created'
        
        html_message = render_to_string('emails/admin_created_user.html', {
            'user': user,
            'temporary_password': temporary_password,
            'admin_user': admin_user,
            'user_role': user_role,
            'login_url': login_url,
            'app_name': getattr(settings, 'APP_NAME', 'RiskGuard Pro'),
            'creation_date': user.date_joined.strftime('%B %d, %Y at %I:%M %p'),
        })
        
        plain_message = strip_tags(html_message)
        
        # Use SES with Django fallback
        send_email_via_ses(
            subject=subject,
            html_message=html_message,
            plain_message=plain_message,
            recipient_email=user.email
        )
        
        logger.info(f"Admin-created user welcome email sent to: {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send admin-created user email to {user.email}: {str(e)}")
        raise
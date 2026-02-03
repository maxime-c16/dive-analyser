"""
Input validation and sanitization for production security
"""

import re
from typing import Any, Dict, List, Optional
import html
from urllib.parse import quote, unquote


class InputValidator:
    """Validates and sanitizes user input"""

    VALID_DIVE_CODES = re.compile(r'^\d{3,6}[A-Da-d]$')
    VALID_HEIGHTS = {'1m', '3m', '5m', '7m', '10m', '1mp', '3mp', '5mp', '7mp', '10mp'}
    VALID_PERFORMANCE = {'F', 'B', 'M', 'G', 'P'}
    MAX_STRING_LENGTH = 1000
    MAX_JSON_SIZE = 10_000_000  # 10 MB

    @staticmethod
    def validate_dive_code(code: str) -> bool:
        """Validate FINA dive code format"""
        if not code or not isinstance(code, str):
            return False
        if len(code) > 10:
            return False
        return bool(InputValidator.VALID_DIVE_CODES.match(code.strip()))

    @staticmethod
    def validate_height(height: str) -> bool:
        """Validate height value"""
        if not height or not isinstance(height, str):
            return False
        normalized = height.lower().strip()
        return normalized in InputValidator.VALID_HEIGHTS

    @staticmethod
    def validate_performance(performance: str) -> bool:
        """Validate performance rating"""
        if not performance or not isinstance(performance, str):
            return False
        return performance.upper().strip() in InputValidator.VALID_PERFORMANCE

    @staticmethod
    def validate_date(date_str: str) -> bool:
        """Validate ISO date format"""
        if not date_str or not isinstance(date_str, str):
            return False
        # Should be YYYY-MM-DD
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str.strip()))

    @staticmethod
    def validate_sync_id(sync_id: str) -> bool:
        """Validate sync operation ID"""
        if not sync_id or not isinstance(sync_id, str):
            return False
        if len(sync_id) > 50:
            return False
        # Alphanumeric, hyphens, underscores only
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', sync_id))

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format"""
        if not email or not isinstance(email, str):
            return False
        if len(email) > 254:
            return False
        # Basic email validation
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

    @staticmethod
    def validate_uuid(uuid_str: str) -> bool:
        """Validate UUID format"""
        if not uuid_str or not isinstance(uuid_str, str):
            return False
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
        )
        return bool(uuid_pattern.match(uuid_str))

    @staticmethod
    def sanitize_string(text: str, max_length: int = MAX_STRING_LENGTH) -> str:
        """Sanitize and limit string length"""
        if not isinstance(text, str):
            return ''

        # Limit length
        text = text[:max_length]

        # HTML escape
        text = html.escape(text)

        # Remove null bytes
        text = text.replace('\x00', '')

        # Normalize whitespace
        text = ' '.join(text.split())

        return text

    @staticmethod
    def validate_dive_data(dive: Dict[str, Any]) -> bool:
        """Validate complete dive record"""
        required_fields = {'dive_code', 'performance', 'height', 'date'}

        # Check required fields
        if not all(field in dive for field in required_fields):
            return False

        # Validate each field
        if not InputValidator.validate_dive_code(dive['dive_code']):
            return False

        if not InputValidator.validate_performance(dive['performance']):
            return False

        if not InputValidator.validate_height(dive['height']):
            return False

        if not InputValidator.validate_date(dive['date']):
            return False

        return True

    @staticmethod
    def validate_sync_request(data: Dict[str, Any]) -> bool:
        """Validate sync request payload"""
        if not isinstance(data, dict):
            return False

        # Must have videos array
        if 'videos' not in data or not isinstance(data['videos'], list):
            return False

        # Check each video
        for video in data['videos']:
            if not InputValidator.validate_dive_data(video):
                return False

        # Max 500 videos per sync
        if len(data['videos']) > 500:
            return False

        return True

    @staticmethod
    def validate_sql_safe(query_param: str) -> bool:
        """Check if string might contain SQL injection attempts"""
        dangerous_patterns = [
            r'(\b(UNION|SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC)\b)',
            r'(-{2}|;|\/\*|\*\/)',  # Comments and terminators
            r'(\$\(|\`)',  # Command injection
            r'(xp_|sp_)',  # SQL Server procedures
        ]

        if not query_param:
            return True

        query_upper = query_param.upper()
        for pattern in dangerous_patterns:
            if re.search(pattern, query_upper, re.IGNORECASE):
                return False

        return True

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe storage"""
        if not filename:
            return 'file'

        # Remove path separators
        filename = filename.replace('/', '').replace('\\', '')

        # Keep only alphanumeric, dots, hyphens, underscores
        filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

        # Remove leading dots
        filename = filename.lstrip('.')

        # Limit length
        if len(filename) > 255:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            filename = name[:250] + ('.' + ext if ext else '')

        return filename or 'file'

    @staticmethod
    def extract_safe_query_param(param: str, max_length: int = 100) -> Optional[str]:
        """Extract and validate query parameter"""
        if not param:
            return None

        if len(param) > max_length:
            return None

        if not InputValidator.validate_sql_safe(param):
            return None

        # URL decode and sanitize
        try:
            param = unquote(param)
            param = InputValidator.sanitize_string(param, max_length)
            return param if param else None
        except Exception:
            return None


class RateLimitConfig:
    """Rate limiting configuration for endpoints"""

    LIMITS = {
        '/api/v1/sync/batch': '10/minute',
        '/api/v1/sync/status': '30/minute',
        '/api/v1/ws/sync': '100/minute',
        '/api/v1/journey/journey': '30/minute',
        '/api/v1/journey/milestones': '30/minute',
        '/api/v1/journey/phase-analysis': '30/minute',
        '/api/v1/analytics/overall': '30/minute',
        '/api/v1/analytics/monthly': '30/minute',
        '/api/v1/analytics/by-height': '30/minute',
        '/api/v1/analytics/by-direction': '30/minute',
    }

    @classmethod
    def get_limit(cls, endpoint: str) -> str:
        """Get rate limit for endpoint"""
        return cls.LIMITS.get(endpoint, '100/hour')


class SecurityHeaders:
    """Security headers for HTTP responses"""

    HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' fonts.googleapis.com; font-src 'self' fonts.gstatic.com",
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'geolocation=(), microphone=(), camera=()',
    }

    @classmethod
    def get_headers(cls) -> Dict[str, str]:
        """Get all security headers"""
        return cls.HEADERS.copy()


def validate_request_data(data: Dict[str, Any], schema: Dict[str, Any]) -> bool:
    """Validate request data against schema"""
    if not isinstance(data, dict):
        return False

    for field, field_type in schema.items():
        if field not in data:
            return False

        value = data[field]

        if not isinstance(value, field_type):
            return False

    return True

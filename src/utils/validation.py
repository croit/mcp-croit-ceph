#!/usr/bin/env python3
"""
Validation Helper Functions
Reusable validation functions for argument checking and data validation.
"""

from typing import Any, Dict, List, Optional


class ValidationError(ValueError):
    """Custom exception for validation errors"""

    pass


def validate_required_args(arguments: Dict[str, Any], required: List[str]) -> None:
    """
    Validate that all required arguments are present.

    Args:
        arguments: Dictionary of provided arguments
        required: List of required argument names

    Raises:
        ValidationError: If any required arguments are missing

    Examples:
        >>> validate_required_args({"name": "foo"}, ["name", "value"])
        ValidationError: Missing required arguments: value
    """
    missing = [
        arg for arg in required if arg not in arguments or arguments[arg] is None
    ]
    if missing:
        raise ValidationError(f"Missing required arguments: {', '.join(missing)}")


def validate_positive_int(
    value: Any, name: str, min_value: int = 1, max_value: Optional[int] = None
) -> int:
    """
    Validate and return a positive integer.

    Args:
        value: Value to validate
        name: Name of the parameter (for error messages)
        min_value: Minimum allowed value (default: 1)
        max_value: Maximum allowed value (optional)

    Returns:
        Validated integer value

    Raises:
        ValidationError: If value is not a valid positive integer

    Examples:
        >>> validate_positive_int("10", "limit")
        10

        >>> validate_positive_int("-5", "limit")
        ValidationError: limit must be >= 1

        >>> validate_positive_int("1000", "limit", max_value=100)
        ValidationError: limit must be <= 100
    """
    try:
        int_val = int(value)
        if int_val < min_value:
            raise ValidationError(f"{name} must be >= {min_value}")
        if max_value is not None and int_val > max_value:
            raise ValidationError(f"{name} must be <= {max_value}")
        return int_val
    except (TypeError, ValueError) as e:
        raise ValidationError(
            f"Invalid {name}: must be an integer, got {type(value).__name__}"
        )


def validate_non_negative_float(
    value: Any, name: str, max_value: Optional[float] = None
) -> float:
    """
    Validate and return a non-negative float.

    Args:
        value: Value to validate
        name: Name of the parameter (for error messages)
        max_value: Maximum allowed value (optional)

    Returns:
        Validated float value

    Raises:
        ValidationError: If value is not a valid non-negative float

    Examples:
        >>> validate_non_negative_float("1.5", "hours_back")
        1.5

        >>> validate_non_negative_float("-0.5", "hours_back")
        ValidationError: hours_back must be >= 0.0
    """
    try:
        float_val = float(value)
        if float_val < 0:
            raise ValidationError(f"{name} must be >= 0.0")
        if max_value is not None and float_val > max_value:
            raise ValidationError(f"{name} must be <= {max_value}")
        return float_val
    except (TypeError, ValueError):
        raise ValidationError(
            f"Invalid {name}: must be a number, got {type(value).__name__}"
        )


def validate_string(
    value: Any,
    name: str,
    min_length: int = 0,
    max_length: Optional[int] = None,
    allow_empty: bool = True,
) -> str:
    """
    Validate and return a string.

    Args:
        value: Value to validate
        name: Name of the parameter (for error messages)
        min_length: Minimum string length (default: 0)
        max_length: Maximum string length (optional)
        allow_empty: Whether to allow empty strings (default: True)

    Returns:
        Validated string value

    Raises:
        ValidationError: If value is not a valid string

    Examples:
        >>> validate_string("test", "name")
        'test'

        >>> validate_string("", "name", allow_empty=False)
        ValidationError: name cannot be empty
    """
    if not isinstance(value, str):
        raise ValidationError(
            f"Invalid {name}: must be a string, got {type(value).__name__}"
        )

    if not allow_empty and not value:
        raise ValidationError(f"{name} cannot be empty")

    if len(value) < min_length:
        raise ValidationError(f"{name} must be at least {min_length} characters")

    if max_length is not None and len(value) > max_length:
        raise ValidationError(f"{name} must be at most {max_length} characters")

    return value


def validate_choice(value: Any, name: str, choices: List[Any]) -> Any:
    """
    Validate that value is one of the allowed choices.

    Args:
        value: Value to validate
        name: Name of the parameter (for error messages)
        choices: List of allowed values

    Returns:
        Validated value

    Raises:
        ValidationError: If value is not in choices

    Examples:
        >>> validate_choice("http", "protocol", ["http", "https"])
        'http'

        >>> validate_choice("ftp", "protocol", ["http", "https"])
        ValidationError: protocol must be one of: http, https
    """
    if value not in choices:
        choices_str = ", ".join(str(c) for c in choices)
        raise ValidationError(f"{name} must be one of: {choices_str}")
    return value


def validate_dict(
    value: Any, name: str, required_keys: Optional[List[str]] = None
) -> Dict:
    """
    Validate that value is a dictionary with optional required keys.

    Args:
        value: Value to validate
        name: Name of the parameter (for error messages)
        required_keys: List of required keys (optional)

    Returns:
        Validated dictionary

    Raises:
        ValidationError: If value is not a dict or missing required keys

    Examples:
        >>> validate_dict({"name": "test"}, "config")
        {'name': 'test'}

        >>> validate_dict({"name": "test"}, "config", required_keys=["name", "value"])
        ValidationError: config missing required keys: value
    """
    if not isinstance(value, dict):
        raise ValidationError(
            f"Invalid {name}: must be a dictionary, got {type(value).__name__}"
        )

    if required_keys:
        missing = [key for key in required_keys if key not in value]
        if missing:
            raise ValidationError(f"{name} missing required keys: {', '.join(missing)}")

    return value


def validate_list(
    value: Any,
    name: str,
    min_length: int = 0,
    max_length: Optional[int] = None,
    item_type: Optional[type] = None,
) -> List:
    """
    Validate that value is a list with optional constraints.

    Args:
        value: Value to validate
        name: Name of the parameter (for error messages)
        min_length: Minimum list length (default: 0)
        max_length: Maximum list length (optional)
        item_type: Expected type of list items (optional)

    Returns:
        Validated list

    Raises:
        ValidationError: If value is not a valid list

    Examples:
        >>> validate_list([1, 2, 3], "items")
        [1, 2, 3]

        >>> validate_list([1, 2, 3], "items", item_type=str)
        ValidationError: items must contain only str items
    """
    if not isinstance(value, list):
        raise ValidationError(
            f"Invalid {name}: must be a list, got {type(value).__name__}"
        )

    if len(value) < min_length:
        raise ValidationError(f"{name} must contain at least {min_length} items")

    if max_length is not None and len(value) > max_length:
        raise ValidationError(f"{name} must contain at most {max_length} items")

    if item_type is not None:
        invalid_items = [
            i for i, item in enumerate(value) if not isinstance(item, item_type)
        ]
        if invalid_items:
            raise ValidationError(
                f"{name} must contain only {item_type.__name__} items"
            )

    return value


def validate_url(
    value: str, name: str, allowed_schemes: Optional[List[str]] = None
) -> str:
    """
    Basic URL validation.

    Args:
        value: URL string to validate
        name: Name of the parameter (for error messages)
        allowed_schemes: List of allowed URL schemes (e.g., ["http", "https"])

    Returns:
        Validated URL string

    Raises:
        ValidationError: If URL is invalid

    Examples:
        >>> validate_url("https://example.com", "host")
        'https://example.com'

        >>> validate_url("ftp://example.com", "host", allowed_schemes=["http", "https"])
        ValidationError: host must use one of these schemes: http, https
    """
    import re

    if not isinstance(value, str):
        raise ValidationError(f"Invalid {name}: must be a string")

    # Basic URL pattern
    url_pattern = re.compile(r"^(https?|ftp)://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
    if not url_pattern.match(value):
        raise ValidationError(f"Invalid {name}: must be a valid URL")

    if allowed_schemes:
        scheme = value.split("://")[0].lower()
        if scheme not in allowed_schemes:
            schemes_str = ", ".join(allowed_schemes)
            raise ValidationError(
                f"{name} must use one of these schemes: {schemes_str}"
            )

    return value

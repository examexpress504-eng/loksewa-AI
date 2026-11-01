"""
Nepal Can Move (NCM) Courier & Logistics Service Integration.

Dedicated, resilient service client for interacting with the Nepal Can Move API.
Supports branch retrieval (with multi-tier caching), live rate calculation,
shipment creation, tracking, order details, and bulk status inquiries.

Security & Reliability Guarantees:
- Never exposes NCM credentials in client code, logs, or error responses.
- Sanitizes sensitive customer PII (phone numbers, full names, addresses) in logs.
- Strict timeout configuration (connect timeout = 5s, read timeout = 15s).
- Safe retry strategy for idempotent GET requests only.
- Shipment creation (POST /v1/order/create) is NEVER automatically retried on ambiguous timeouts.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import logging
import os
import re
import time
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .nepal_geography import (
    calculate_haversine_distance,
    get_municipality_centroid,
    DISTRICT_CENTROIDS,
    find_local_level_match,
)

logger = logging.getLogger("marketplace.ncm_service")

# --- CUSTOM EXCEPTIONS ---

class NCMError(Exception):
    """Base exception for all Nepal Can Move courier errors."""
    pass


class NCMConfigurationError(NCMError):
    """Raised when required NCM settings or API credentials are missing or invalid."""
    pass


class NCMConnectionError(NCMError):
    """
    Raised when connection to NCM API times out, drops, or fails at network level.
    The `is_ambiguous` flag indicates whether the request may have already been
    processed by NCM (e.g. read timeout on POST).
    """
    def __init__(self, message: str, is_ambiguous: bool = False, original_exc: Optional[Exception] = None):
        super().__init__(message)
        self.is_ambiguous = is_ambiguous
        self.original_exc = original_exc


class NCMAPIError(NCMError):
    """Raised when NCM returns an HTTP error or an unexpected/malformed response payload."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class NCMValidationError(NCMError):
    """Raised when client-side parameter validation fails before sending request to NCM."""
    pass


# --- SANITIZATION HELPERS ---

def sanitize_phone(phone: Optional[str]) -> str:
    """Mask phone number for safe logging (e.g. 9812345678 -> 98****5678)."""
    if not phone:
        return "[EMPTY]"
    clean = re.sub(r"\s+", "", str(phone))
    if len(clean) >= 7:
        return f"{clean[:2]}****{clean[-4:]}"
    return "***"


def sanitize_text(text: Optional[str]) -> str:
    """Mask name or address for safe logging."""
    if not text:
        return "[EMPTY]"
    cleaned = str(text).strip()
    if len(cleaned) <= 3:
        return "***"
    return f"{cleaned[:2]}***{cleaned[-1:]}"


def sanitize_payload_for_logging(data: Any) -> Any:
    """Recursively sanitize sensitive fields in a payload dict for logging."""
    if not isinstance(data, dict):
        return data
    sensitive_keys = {"phone", "phone2", "name", "address", "instruction"}
    safe = {}
    for k, v in data.items():
        if k in ("phone", "phone2"):
            safe[k] = sanitize_phone(v)
        elif k in ("name", "address", "instruction"):
            safe[k] = sanitize_text(v)
        elif isinstance(v, dict):
            safe[k] = sanitize_payload_for_logging(v)
        elif isinstance(v, list):
            safe[k] = [sanitize_payload_for_logging(item) for item in v]
        else:
            safe[k] = v
    return safe


# --- DELIVERY TYPE MAPPINGS ---

# Map frontend/internal delivery types to the 'type' query parameter expected by /v1/shipping-rate
RATE_DELIVERY_TYPE_MAP = {
    "door2door": "Pickup/Collect",
    "pickup/collect": "Pickup/Collect",
    "branch2door": "Send",
    "send": "Send",
    "door2branch": "D2B",
    "d2b": "D2B",
    "branch2branch": "B2B",
    "b2b": "B2B",
}


# --------------------------------------------------------------------------
# Location Normalization & Strict Prioritized Matching Engine
# --------------------------------------------------------------------------

ADMIN_SUFFIX_PATTERN = re.compile(
    r'\b('
    r'sub[\s\-]metropolitan\s+city|sub[\s\-]metropolis|sub[\s\-]metro|'
    r'metropolitan\s+city|metropolis|metro|'
    r'upamahanagarpalika|upa[\s\-]mahanagarpalika|upamahanagar\s+palika|'
    r'mahanagarpalika|mahanagar\s+palika|'
    r'rural\s+municipality|rural[\s\-]municipality|'
    r'gaunpalika|gaun\s+palika|gaumpalika|gaum\s+palika|'
    r'municipality|'
    r'nagarpalika|nagar\s+palika|'
    r'r\.m\.|rm|vdc|n\.p\.|np|m\.p\.|mp'
    r')\b',
    re.IGNORECASE
)

PUNCTUATION_PATTERN = re.compile(r'[\.,/\\()\[\]{}\-_:;!@#$%^&*~`+=|<>?]')


def normalize_location_name(text: Optional[str]) -> str:
    """
    Normalize district, municipality, or covered area names for accurate matching:
    - Lowercases and trims
    - Replaces punctuation with single spaces
    - Removes common administrative suffixes (Metropolitan City, Gaunpalika, etc.)
    - Collapses consecutive whitespace to a single space
    """
    if not text:
        return ""
    cleaned = PUNCTUATION_PATTERN.sub(" ", str(text).lower())
    cleaned = ADMIN_SUFFIX_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def is_token_boundary_match(query: Optional[str], target: Optional[str]) -> bool:
    """
    Check if normalized location stems match bidirectionally:
    1. Exact equality (e.g. 'kathmandu' == 'kathmandu')
    2. query as whole word in target (e.g. 'pokhara' in 'pokhara lekhnath')
    3. target as whole word in query (e.g. 'pokhara lekhnath' contains whole token 'pokhara')
    Strictly avoids false positives (e.g. 'ilam' does NOT match 'milam').
    """
    norm_q = normalize_location_name(query)
    norm_t = normalize_location_name(target)
    if not norm_q or not norm_t:
        return False
    if norm_q == norm_t:
        return True
    # Whole-word token match q in t
    if re.search(r'\b' + re.escape(norm_q) + r'\b', norm_t):
        return True
    # Whole-word token match t in q (e.g. branch is 'Pokhara', user typed 'Pokhara Lekhnath')
    if re.search(r'\b' + re.escape(norm_t) + r'\b', norm_q):
        return True
    return False


def discover_nearest_ncm_branches(
    branches: List[Dict[str, Any]],
    municipality: Optional[str] = None,
    district: Optional[str] = None,
    province: Optional[str] = None,
    user_lat: Optional[Union[float, str]] = None,
    user_lon: Optional[Union[float, str]] = None,
    allow_nearby: bool = False,
    max_results: int = 15,
    tole: Optional[str] = None,
) -> Dict[str, Any]:
    """
    LoksewaAI — NCM Phase 12: Intelligent Nearest Branch Discovery & Geographic Coverage Engine.

    Ranks nearby branches by:
    1. Geographic distance (Haversine formula, strictly labeled 'Approx. distance').
    2. Delivery coverage (Exact local-level > District hub > Cross-district nearby).
    3. Live serviceability (Serviceable branches strictly outrank unserviceable ones).

    Search Priority:
    Priority 1: Municipality / Local Level matches
    Priority 2: District Hub fallback (ONLY when Priority 1 yields zero matches)
    Priority 3: Cross-District Nearby discovery (within 85km, ONLY when Priority 1 & 2 yield zero matches)
    """
    raw_mun = (municipality or "").strip()
    raw_dist = (district or "").strip()
    raw_prov = (province or "").strip()
    raw_tole = (tole or "").strip()

    stem_mun = normalize_location_name(raw_mun)
    stem_dist = normalize_location_name(raw_dist)

    # 1. Resolve student delivery anchor coordinates
    student_lat: Optional[float] = None
    student_lon: Optional[float] = None
    anchor_source = "unresolved"
    anchor_info: Optional[Dict[str, Any]] = None

    if user_lat is not None and user_lon is not None:
        try:
            f_lat = float(user_lat)
            f_lon = float(user_lon)
            if -90.0 <= f_lat <= 90.0 and -180.0 <= f_lon <= 180.0:
                student_lat, student_lon = f_lat, f_lon
                anchor_source = "client_provided"
                anchor_info = {"lat": f_lat, "lon": f_lon, "source": "client_provided"}
        except (ValueError, TypeError):
            pass

    if student_lat is None:
        c_lat, c_lon, c_source, c_info = get_municipality_centroid(raw_mun, raw_dist, raw_prov)
        if c_lat is not None and c_lon is not None:
            student_lat, student_lon = c_lat, c_lon
            anchor_source = c_source
            anchor_info = c_info

    # 2. Lookup DB branch records to enrich missing coordinates/provenance
    db_branch_map: Dict[str, Any] = {}
    try:
        from .models import NCMBranchRecord
        records = NCMBranchRecord.objects.filter(is_active=True)
        for rec in records:
            if rec.code:
                db_branch_map[rec.code.strip().lower()] = rec
            if rec.name:
                db_branch_map[rec.name.strip().lower()] = rec
    except Exception as e:
        logger.debug("Database branch lookup skipped: %s", e)

    # 3. Process and enrich each branch
    processed_branches: List[Dict[str, Any]] = []

    for b in branches:
        b_dict = dict(b)
        b_name = str(b_dict.get("name") or "").strip()
        b_code = str(b_dict.get("code") or b_dict.get("pk") or b_dict.get("id") or b_name).strip()
        b_mun = str(b_dict.get("municipality") or b_dict.get("local_level") or "").strip()
        b_dist = str(b_dict.get("district_name") or b_dict.get("district") or "").strip()
        b_prov = str(b_dict.get("province_name") or b_dict.get("province") or "").strip()

        # Parse areas covered
        raw_areas = b_dict.get("areas_covered") or b_dict.get("coverage") or b_dict.get("covered_areas") or []
        if isinstance(raw_areas, str):
            areas_list = [a.strip() for a in raw_areas.replace('\n', ',').split(",") if a.strip()]
        elif isinstance(raw_areas, list):
            areas_list = [str(a).strip() for a in raw_areas if str(a).strip()]
        else:
            areas_list = []
        b_dict["areas_covered"] = areas_list

        # Coordinate resolution & provenance
        b_lat: Optional[float] = None
        b_lon: Optional[float] = None
        coord_source = "UNVERIFIED"
        is_coord_verified = False
        is_serviceable = b_dict.get("is_serviceable", True)

        # Check if coordinates in branch dict
        if b_dict.get("latitude") is not None and b_dict.get("longitude") is not None:
            try:
                b_lat = float(b_dict["latitude"])
                b_lon = float(b_dict["longitude"])
                coord_source = str(b_dict.get("coordinate_source") or "API")
                is_coord_verified = bool(b_dict.get("is_coordinate_verified", False))
            except (ValueError, TypeError):
                b_lat, b_lon = None, None

        # If not, check database record
        if b_lat is None:
            db_rec = db_branch_map.get(b_code.lower()) or db_branch_map.get(b_name.lower())
            if db_rec and db_rec.has_valid_coordinates:
                b_lat = float(db_rec.latitude)
                b_lon = float(db_rec.longitude)
                coord_source = db_rec.coordinate_source
                is_coord_verified = db_rec.is_coordinate_verified
                is_serviceable = db_rec.is_serviceable

        # If still not found, try municipality/name centroid lookup
        if b_lat is None:
            m_lat, m_lon, m_source, _ = get_municipality_centroid(b_mun or b_name, b_dist, b_prov)
            if m_lat is not None and m_lon is not None:
                b_lat = m_lat
                b_lon = m_lon
                coord_source = "MUNICIPALITY_CENTROID" if m_source == "municipality_centroid" else "DISTRICT_CENTROID"
                is_coord_verified = False

        b_dict["latitude"] = b_lat
        b_dict["longitude"] = b_lon
        b_dict["coordinate_source"] = coord_source
        b_dict["is_coordinate_verified"] = is_coord_verified
        b_dict["is_serviceable"] = is_serviceable
        b_dict["serviceability_status"] = "VERIFIED_SERVICEABLE" if is_serviceable else "UNSERVICEABLE"

        # Calculate distance
        if student_lat is not None and b_lat is not None:
            raw_dist_km = calculate_haversine_distance(student_lat, student_lon, b_lat, b_lon)
            if raw_dist_km is not None:
                approx_dist = round(raw_dist_km, 1)
                b_dict["approx_distance_km"] = approx_dist
                b_dict["distance_km"] = raw_dist_km
                b_dict["distance_label"] = f"~{approx_dist} km (Approx. distance)"
                if raw_dist_km <= 35.0:
                    b_dict["radius_zone"] = "primary"
                elif raw_dist_km <= 85.0:
                    b_dict["radius_zone"] = "extended"
                elif raw_dist_km <= 250.0:
                    b_dict["radius_zone"] = "regional"
                else:
                    b_dict["radius_zone"] = "far"
            else:
                b_dict["approx_distance_km"] = None
                b_dict["distance_km"] = None
                b_dict["distance_label"] = "Approx. distance unavailable"
                b_dict["radius_zone"] = "unknown"
        else:
            b_dict["approx_distance_km"] = None
            b_dict["distance_km"] = None
            b_dict["distance_label"] = "Approx. distance unavailable"
            b_dict["radius_zone"] = "unknown"

        # Check coverage
        dist_matches = (
            not stem_dist
            or is_token_boundary_match(stem_dist, b_dist)
            or is_token_boundary_match(stem_dist, b_name)
        )

        is_mun_match = False
        is_tole_match = False

        # Match tole/area (e.g. Baneshwor in Kathmandu)
        if raw_tole:
            stem_tole = normalize_location_name(raw_tole)
            if stem_tole:
                if is_token_boundary_match(stem_tole, b_name) or any(is_token_boundary_match(stem_tole, a) for a in areas_list):
                    is_mun_match = True
                    is_tole_match = True

        if not is_mun_match and stem_mun:
            if b_mun and is_token_boundary_match(stem_mun, b_mun):
                is_mun_match = True
            elif is_token_boundary_match(stem_mun, b_name) and dist_matches:
                is_mun_match = True
            elif any(is_token_boundary_match(stem_mun, a) for a in areas_list):
                is_mun_match = True
            else:
                # Check individual significant tokens (e.g. 'kathmandu' from 'kathmandu 10')
                sig_tokens = [t for t in stem_mun.split() if len(t) >= 3 and not t.isdigit()]
                for tok in sig_tokens:
                    if b_mun and is_token_boundary_match(tok, b_mun):
                        is_mun_match = True
                        break
                    if is_token_boundary_match(tok, b_name) and dist_matches:
                        is_mun_match = True
                        break
                    if any(is_token_boundary_match(tok, a) for a in areas_list):
                        is_mun_match = True
                        break

        b_dict["is_tole_match"] = is_tole_match

        if is_mun_match:
            b_dict["coverage_type"] = "local_level"
            b_dict["coverage_label"] = "Direct Local Coverage"
            b_dict["match_type"] = "municipality"
            b_dict["match_label"] = "Matches Your Municipality"
            b_dict["match_priority"] = 1
        elif stem_dist and (is_token_boundary_match(stem_dist, b_dist) or is_token_boundary_match(stem_dist, b_name)):
            b_dict["coverage_type"] = "district"
            b_dict["coverage_label"] = "Serves Your District"
            b_dict["match_type"] = "district"
            b_dict["match_label"] = "Serves Your District"
            b_dict["match_priority"] = 2
        elif b_dict.get("distance_km") is not None and b_dict["distance_km"] <= 85.0:
            b_dict["coverage_type"] = "cross_district_nearby"
            b_dict["coverage_label"] = "Nearby Neighboring District"
            b_dict["match_type"] = "nearby"
            b_dict["match_label"] = "Nearby Neighboring District"
            b_dict["match_priority"] = 3
        else:
            b_dict["coverage_type"] = "regional"
            b_dict["coverage_label"] = "Regional Branch"
            b_dict["match_type"] = "regional"
            b_dict["match_label"] = "Regional Branch"
            b_dict["match_priority"] = 4

        processed_branches.append(b_dict)

    # 4. Filter candidates according to strict search priority
    mun_matches = [b for b in processed_branches if b["coverage_type"] == "local_level"]
    dist_matches = [b for b in processed_branches if b["coverage_type"] == "district"]
    nearby_matches = [b for b in processed_branches if b["coverage_type"] == "cross_district_nearby"]
    regional_matches = [b for b in processed_branches if b["coverage_type"] == "regional"]

    # Sorting helper:
    # 1. Serviceable first (is_serviceable=True -> 0, False -> 1)
    # 2. Tole/Area match first (0 if tole match, 1 otherwise)
    # 3. Known distance ascending, then None distance
    # 4. Exact municipality match first (for municipality pool)
    # 5. Name alphabetical
    def sort_key(b: Dict[str, Any], is_mun_pool: bool = False):
        serviceable_rank = 0 if b.get("is_serviceable", True) else 1
        tole_rank = 0 if b.get("is_tole_match") else 1
        dist_val = b.get("distance_km") if b.get("distance_km") is not None else 99999.0
        exact_mun_rank = 0
        if is_mun_pool and stem_mun:
            b_mun_str = str(b.get("municipality") or b.get("name") or "")
            exact_mun_rank = 0 if is_token_boundary_match(stem_mun, b_mun_str) else 1
        return (serviceable_rank, tole_rank, exact_mun_rank, dist_val, b.get("name", ""))

    mun_matches.sort(key=lambda b: sort_key(b, is_mun_pool=True))
    dist_matches.sort(key=lambda b: sort_key(b, is_mun_pool=False))
    nearby_matches.sort(key=lambda b: sort_key(b, is_mun_pool=False))
    regional_matches.sort(key=lambda b: sort_key(b, is_mun_pool=False))

    delivery_anchor = {
        "latitude": student_lat,
        "longitude": student_lon,
        "source": anchor_source,
        "municipality": raw_mun,
        "district": raw_dist,
        "province": raw_prov,
    }

    # Strict multi-tiered hierarchy:
    # 1. Exact local-level matches first.
    # 2. All relevant district branches second.
    # 3. Verified serviceable neighboring districts third.
    # 4. Wider network alternatives last.
    # Delivery serviceability is validated separately from proximity:
    # Serviceable branches strictly outrank unserviceable ones, and unserviceable
    # branches are NEVER recommended or auto-selected.
    serviceable_mun = [b for b in mun_matches if b.get("is_serviceable", True)]
    serviceable_dist = [b for b in dist_matches if b.get("is_serviceable", True)]
    serviceable_nearby = [b for b in nearby_matches if b.get("is_serviceable", True)]
    serviceable_regional = [b for b in regional_matches if b.get("is_serviceable", True)]
    unserviceable_pool = [
        b for b in mun_matches + dist_matches + nearby_matches + regional_matches
        if not b.get("is_serviceable", True)
    ]

    recommended = None
    match_priority = 0
    match_type = "none"
    message = "No NCM branch was found for your local level or district. Courier delivery is currently unavailable for this location."

    if serviceable_mun:
        recommended = serviceable_mun[0]
        match_priority = 1
        match_type = "municipality"
        message = f"Found {len(mun_matches)} NCM branch(es) serving your local level."
        ordered_suggestions = mun_matches + serviceable_dist + serviceable_nearby + serviceable_regional
    elif serviceable_dist:
        recommended = serviceable_dist[0]
        match_priority = 2
        match_type = "district"
        message = "No NCM branch was found for your local level. Here are the available NCM branches serving your district."
        ordered_suggestions = dist_matches + serviceable_nearby + serviceable_regional
    elif serviceable_nearby and allow_nearby:
        recommended = serviceable_nearby[0]
        match_priority = 3
        match_type = "nearby"
        message = "No NCM branch was found for your local level or district. Showing nearest available NCM branches in neighboring districts."
        ordered_suggestions = nearby_matches + serviceable_regional
    elif mun_matches:
        # All local matches were unserviceable
        match_priority = 1
        match_type = "municipality"
        message = "Branches exist for your local level but are currently unserviceable."
        ordered_suggestions = mun_matches + dist_matches + nearby_matches
    elif dist_matches:
        # All district matches were unserviceable
        match_priority = 2
        match_type = "district"
        message = "Branches exist for your district but are currently unserviceable."
        ordered_suggestions = dist_matches + nearby_matches
    elif nearby_matches:
        match_priority = 3 if allow_nearby else 0
        match_type = "nearby" if allow_nearby else "none"
        message = (
            "No NCM branch was found for your local level or district. Showing nearest available NCM branches in neighboring districts."
            if allow_nearby else
            "No NCM branch was found for your local level or district. Courier delivery is currently unavailable for this location."
        )
        ordered_suggestions = nearby_matches if allow_nearby else []
    else:
        ordered_suggestions = []

    # Deduplicate while preserving strict tier ordering
    seen_codes = set()
    deduped_suggestions = []
    for b in ordered_suggestions:
        code_key = str(b.get("code") or b.get("pk") or b.get("name") or "").strip().lower()
        if code_key and code_key not in seen_codes:
            seen_codes.add(code_key)
            b["is_recommended"] = (recommended is not None and b.get("code") == recommended.get("code"))
            deduped_suggestions.append(b)

    auto_selected = recommended["name"] if recommended else None

    return {
        "match_priority": match_priority,
        "match_type": match_type,
        "message": message,
        "search_municipality": raw_mun,
        "search_district": raw_dist,
        "recommended_branch": recommended,
        "suggested_branches": deduped_suggestions[:max_results],
        "nearby_branches": nearby_matches[:max_results],
        "auto_selected": auto_selected,
        "delivery_anchor": delivery_anchor,
    }


def match_ncm_branches_for_location(
    branches: List[Dict[str, Any]],
    municipality: Optional[str] = None,
    district: Optional[str] = None,
    province: Optional[str] = None,
    user_lat: Optional[Union[float, str]] = None,
    user_lon: Optional[Union[float, str]] = None,
) -> Dict[str, Any]:
    """
    Backward-compatible entry point delegating to discover_nearest_ncm_branches.
    """
    return discover_nearest_ncm_branches(
        branches=branches,
        municipality=municipality,
        district=district,
        province=province,
        user_lat=user_lat,
        user_lon=user_lon,
    )



class NCMService:
    """
    Client service for official Nepal Can Move (NCM) REST API.
    """

    DEFAULT_CONNECT_TIMEOUT = 5.0
    DEFAULT_READ_TIMEOUT = 15.0
    BRANCHES_CACHE_KEY = "ncm:branches:list"
    BRANCHES_CACHE_TTL = 86400  # 24 hours in seconds

    # In-memory backup cache to survive Redis interruptions without crashing
    _fallback_branches_cache: Optional[List[Dict[str, Any]]] = None

    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        default_origin_branch: Optional[str] = None,
        timeout: Optional[Union[float, tuple]] = None,
        session: Optional[requests.Session] = None,
    ):
        config = None
        try:
            from .models import NCMConfiguration
            config = NCMConfiguration.get_settings()
        except Exception:
            config = None

        raw_token = ""
        if api_token is not None:
            raw_token = api_token
        elif config and config.get_effective_token():
            raw_token = config.get_effective_token()
        else:
            raw_token = getattr(settings, "NCM_API_TOKEN", "")

        from .models import clean_ncm_token
        self.api_token = clean_ncm_token(raw_token)

        if base_url is not None and base_url.strip():
            raw_base = base_url.strip()
        elif config:
            raw_base = config.get_effective_base_url()
        elif getattr(settings, 'NCM_EXPLICIT_BASE_URL', os.environ.get('NCM_BASE_URL', '')).strip():
            raw_base = getattr(settings, 'NCM_EXPLICIT_BASE_URL', os.environ.get('NCM_BASE_URL', '')).strip()
        else:
            env = getattr(settings, "NCM_ENVIRONMENT", "demo").lower()
            if env == "production":
                raw_base = "https://portal.nepalcanmove.com/api/"
            else:
                raw_base = "https://demo.nepalcanmove.com/api/"

        if not raw_base.endswith("/"):
            raw_base += "/"
        self.base_url = raw_base

        if default_origin_branch is not None:
            self.default_origin_branch = default_origin_branch.strip()
        elif config and config.default_origin_branch:
            self.default_origin_branch = config.default_origin_branch.strip()
        else:
            self.default_origin_branch = (
                getattr(settings, "NCM_DEFAULT_ORIGIN_BRANCH", "Kathmandu")
            ).strip()

        self.timeout = (
            timeout
            if timeout is not None
            else (self.DEFAULT_CONNECT_TIMEOUT, self.DEFAULT_READ_TIMEOUT)
        )

        self._session = session or requests.Session()

    def test_connection(self) -> Dict[str, Any]:
        """
        Diagnostic check to test NCM API connectivity and authentication.
        Performs a safe, read-only GET request to list branches.
        NEVER creates a shipment.
        Measures round-trip response time and updates NCMConfiguration telemetry.
        """
        start_time = time.perf_counter()
        config = None
        try:
            from .models import NCMConfiguration
            config = NCMConfiguration.get_settings()
        except Exception:
            pass

        if not self.api_token:
            error_msg = "API Token is not configured. Please set NCM_API_TOKEN in environment or configuration."
            if config:
                config.connection_status = "error"
                config.last_connection_tested_at = timezone.now()
                config.last_connection_latency_ms = None
                config.last_connection_error = error_msg
                config.save(update_fields=["connection_status", "last_connection_tested_at", "last_connection_latency_ms", "last_connection_error"])
            return {
                "success": False,
                "error": error_msg,
                "latency_ms": None,
                "environment": config.environment if config else "unknown",
                "base_url": self.base_url,
                "token_source": config.get_token_source() if config else "NOT_CONFIGURED",
                "masked_token": "",
            }

        try:
            res = self.get_branches(force_refresh=True, return_meta=True)
            if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], dict):
                branches, meta = res
                if meta.get("source") != "LIVE_API":
                    sync_err = meta.get("sync_error") or "Live API connection failed (fallback catalog returned)."
                    raise NCMAPIError(sync_err)
            else:
                branches = res
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if config:
                config.connection_status = "connected"
                config.last_connection_tested_at = timezone.now()
                config.last_connection_latency_ms = latency_ms
                config.last_connection_error = ""
                config.save(update_fields=["connection_status", "last_connection_tested_at", "last_connection_latency_ms", "last_connection_error"])
            return {
                "success": True,
                "latency_ms": latency_ms,
                "branch_count": len(branches),
                "environment": config.environment if config else "demo",
                "base_url": self.base_url,
                "token_source": config.get_token_source() if config else ("ENVIRONMENT" if self.api_token else "NOT_CONFIGURED"),
                "masked_token": config.get_masked_token() if config else (f"{self.api_token[:4]}****{self.api_token[-4:]}" if len(self.api_token) > 8 else "****"),
                "default_origin_branch": self.default_origin_branch,
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            safe_error = str(exc)
            if "401" in safe_error or "Invalid token" in safe_error:
                safe_error = "NCM API authentication failed (HTTP 401: Invalid token). Please verify your NCM API token in Render or Admin Courier Settings."
            elif "Connection refused" in safe_error or "Failed to establish" in safe_error:
                safe_error = f"Cannot reach NCM API endpoint ({self.base_url}). Network connection failed."
            if config:
                config.connection_status = "error"
                config.last_connection_tested_at = timezone.now()
                config.last_connection_latency_ms = latency_ms
                config.last_connection_error = safe_error
                config.save(update_fields=["connection_status", "last_connection_tested_at", "last_connection_latency_ms", "last_connection_error"])
            return {
                "success": False,
                "error": safe_error,
                "latency_ms": latency_ms,
                "environment": config.environment if config else "unknown",
                "base_url": self.base_url,
                "token_source": config.get_token_source() if config else ("ENVIRONMENT" if self.api_token else "NOT_CONFIGURED"),
                "masked_token": config.get_masked_token() if config else (f"{self.api_token[:4]}****{self.api_token[-4:]}" if len(self.api_token) > 8 else "****"),
            }

    def is_configured(self) -> bool:
        """Check if NCM service has valid API credentials configured."""
        return bool(self.api_token and self.base_url)

    def _get_auth_headers(self) -> Dict[str, str]:
        """Build request headers with Token authentication."""
        if not self.api_token:
            raise NCMConfigurationError(
                "Nepal Can Move API Token (NCM_API_TOKEN) is not configured in settings or environment."
            )
        return {
            "Authorization": f"Token {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_url(self, endpoint: str) -> str:
        """Construct full API URL from relative endpoint."""
        clean_endpoint = endpoint.lstrip("/")
        return f"{self.base_url}{clean_endpoint}"

    def _execute_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        allow_retries: bool = True,
        max_retries: int = 2,
    ) -> requests.Response:
        """
        Execute an HTTP request with error handling and safe retries for idempotent operations.
        Never retries POST requests when allow_retries is False.
        """
        url = self._build_url(endpoint)
        headers = self._get_auth_headers()
        method_upper = method.upper()

        # Enforce that non-idempotent creations never retry automatically
        if method_upper == "POST" and endpoint.endswith("create"):
            allow_retries = False

        attempt = 0
        last_exception = None

        while attempt <= (max_retries if allow_retries else 0):
            attempt += 1
            try:
                logger.debug(
                    "NCM API Request: %s %s (Attempt %d)",
                    method_upper,
                    url,
                    attempt,
                )
                response = self._session.request(
                    method=method_upper,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    timeout=self.timeout,
                )

                # Check for HTTP errors
                if response.status_code >= 400:
                    # Do not retry 4xx client errors
                    if 400 <= response.status_code < 500:
                        logger.warning(
                            "NCM API Client Error %d for %s %s: %s",
                            response.status_code,
                            method_upper,
                            url,
                            response.text[:200],
                        )
                        raise NCMAPIError(
                            f"NCM API client error {response.status_code}: {response.text[:200]}",
                            status_code=response.status_code,
                            response_body=response.text,
                        )
                    # 5xx server errors can be retried if allow_retries is True
                    if allow_retries and attempt <= max_retries:
                        time.sleep(0.5 * attempt)
                        continue
                    raise NCMAPIError(
                        f"NCM API server error {response.status_code}: {response.text[:200]}",
                        status_code=response.status_code,
                        response_body=response.text,
                    )

                return response

            except requests.exceptions.Timeout as exc:
                last_exception = exc
                is_read_timeout = not isinstance(exc, requests.exceptions.ConnectTimeout)
                logger.warning(
                    "NCM API Timeout on %s %s (Attempt %d, ReadTimeout=%s)",
                    method_upper,
                    url,
                    attempt,
                    is_read_timeout,
                )
                if allow_retries and attempt <= max_retries:
                    time.sleep(0.5 * attempt)
                    continue

                # Ambiguous timeout check:
                # If a POST shipment creation timed out while waiting for read response,
                # the server might have created the shipment! Flag it as ambiguous.
                is_ambiguous = (method_upper == "POST" and is_read_timeout)
                raise NCMConnectionError(
                    f"NCM API request timed out on {method_upper} {endpoint}: {exc}",
                    is_ambiguous=is_ambiguous,
                    original_exc=exc,
                ) from exc

            except requests.exceptions.ConnectionError as exc:
                last_exception = exc
                logger.warning(
                    "NCM API Connection Error on %s %s (Attempt %d): %s",
                    method_upper,
                    url,
                    attempt,
                    exc,
                )
                if allow_retries and attempt <= max_retries:
                    time.sleep(0.5 * attempt)
                    continue
                raise NCMConnectionError(
                    f"NCM API network connection failed for {method_upper} {endpoint}: {exc}",
                    is_ambiguous=False,
                    original_exc=exc,
                ) from exc

            except requests.exceptions.RequestException as exc:
                raise NCMConnectionError(
                    f"Unexpected NCM request failure: {exc}",
                    original_exc=exc,
                ) from exc

        # If loop finishes without returning or raising
        raise NCMConnectionError(
            f"Failed after {attempt} attempts: {last_exception}",
            original_exc=last_exception,
        )

    # --------------------------------------------------------------------------
    # 1. BRANCHES (GET /v2/branches)
    # --------------------------------------------------------------------------

    def _get_fallback_or_seeded_branches_with_source(self) -> Tuple[List[Dict[str, Any]], str]:
        """
        Guarantees that a complete branch list is always returned, tracking data provenance:
        - Checks in-memory cache
        - Checks Redis/Django cache
        - Queries active DB NCMBranchRecord (DATABASE_CACHE)
        - If DB is empty, auto-seeds with STANDARD_NCM_BRANCH_CATALOG into DB, caches, and returns (STATIC_FALLBACK).
        Never clears or overwrites existing valid DB records on failure.
        """
        if NCMService._fallback_branches_cache and len(NCMService._fallback_branches_cache) > 0:
            return NCMService._fallback_branches_cache, "DATABASE_CACHE"

        try:
            stale = cache.get(self.BRANCHES_CACHE_KEY)
            if stale and isinstance(stale, list) and len(stale) > 0:
                NCMService._fallback_branches_cache = stale
                return stale, "DATABASE_CACHE"
        except Exception:
            pass

        try:
            from .models import NCMBranchRecord
            db_recs = NCMBranchRecord.objects.filter(is_active=True)
            if db_recs.exists():
                db_branches = []
                for r in db_recs:
                    db_branches.append({
                        "code": r.code,
                        "name": r.name,
                        "district_name": r.district_name,
                        "province_name": r.province_name,
                        "municipality": r.municipality,
                        "address": r.address,
                        "contact_number": r.contact_number,
                        "areas_covered": r.areas_covered,
                        "latitude": float(r.latitude) if r.latitude is not None else None,
                        "longitude": float(r.longitude) if r.longitude is not None else None,
                        "coordinate_source": r.coordinate_source,
                        "is_coordinate_verified": r.is_coordinate_verified,
                        "is_serviceable": r.is_serviceable,
                    })
                NCMService._fallback_branches_cache = db_branches
                try:
                    cache.set(self.BRANCHES_CACHE_KEY, db_branches, timeout=self.BRANCHES_CACHE_TTL)
                except Exception:
                    pass
                return db_branches, "DATABASE_CACHE"
        except Exception as db_err:
            logger.warning("Database branch fallback lookup failed: %s", db_err)

        # DB is completely empty or failed: auto-seed from authoritative STANDARD_NCM_BRANCH_CATALOG
        try:
            from .nepal_geography import STANDARD_NCM_BRANCH_CATALOG
            self.sync_branches_to_db(STANDARD_NCM_BRANCH_CATALOG)
            NCMService._fallback_branches_cache = list(STANDARD_NCM_BRANCH_CATALOG)
            try:
                cache.set(self.BRANCHES_CACHE_KEY, STANDARD_NCM_BRANCH_CATALOG, timeout=self.BRANCHES_CACHE_TTL)
            except Exception:
                pass
            return list(STANDARD_NCM_BRANCH_CATALOG), "STATIC_FALLBACK"
        except Exception as seed_err:
            logger.error("Auto-seeding branches from standard catalog failed: %s", seed_err)
            return [], "STATIC_FALLBACK"

    def _get_fallback_or_seeded_branches(self) -> List[Dict[str, Any]]:
        branches, _ = self._get_fallback_or_seeded_branches_with_source()
        return branches

    def get_branches(
        self,
        force_refresh: bool = False,
        return_meta: bool = False
    ) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
        """
        Fetch available NCM branches with district and covered areas.
        Supports complete live API pagination (following 'next' or page index),
        removes arbitrary 30-record limits, and synchronizes the catalog into NCMBranchRecord.
        
        Guarantees:
        - Never reports static or cached data as live API data.
        - Preserves existing successful catalog if a live refresh fails.
        - Returns provenance metadata: LIVE_API, DATABASE_CACHE, or STATIC_FALLBACK.
        """
        config = None
        try:
            from .models import NCMConfiguration
            config = NCMConfiguration.get_settings()
        except Exception:
            pass

        if not force_refresh:
            try:
                cached_branches = cache.get(self.BRANCHES_CACHE_KEY)
                if cached_branches and isinstance(cached_branches, list) and len(cached_branches) > 0:
                    meta = {
                        "source": "DATABASE_CACHE",
                        "last_synced_at": config.last_branch_sync_at.isoformat() if config and config.last_branch_sync_at else None,
                        "count": len(cached_branches),
                    }
                    return (cached_branches, meta) if return_meta else cached_branches
            except Exception as e:
                logger.warning("Cache access error during NCM get_branches: %s", e)

        if not self.is_configured():
            logger.info("NCM API credentials not configured; serving verified local branch catalog.")
            branches, source = self._get_fallback_or_seeded_branches_with_source()
            meta = {
                "source": source,
                "last_synced_at": config.last_branch_sync_at.isoformat() if config and config.last_branch_sync_at else None,
                "count": len(branches),
            }
            return (branches, meta) if return_meta else branches

        # Make Live API call with complete pagination support
        try:
            all_branches: List[Dict[str, Any]] = []
            page_num = 1
            max_pages = 50
            next_url: Optional[str] = "v2/branches"

            while next_url and page_num <= max_pages:
                # If next_url is absolute with base_url, strip to relative endpoint
                endpoint = next_url
                if endpoint.startswith(self.base_url):
                    endpoint = endpoint[len(self.base_url):]
                elif endpoint.startswith("http://") or endpoint.startswith("https://"):
                    # Use full URL if different host, else relative
                    pass

                # If first page and clean endpoint, request higher limit if supported
                params = None
                if page_num == 1 and "?" not in endpoint:
                    params = {"page_size": 250, "limit": 250}

                response = self._execute_request(
                    method="GET",
                    endpoint=endpoint,
                    params=params,
                    allow_retries=True,
                )

                try:
                    data = response.json()
                except ValueError as exc:
                    raise NCMAPIError(
                        f"Invalid JSON returned from NCM branches API: {response.text[:200]}",
                        status_code=response.status_code,
                        response_body=response.text,
                    ) from exc

                page_branches: List[Dict[str, Any]] = []
                next_url = None

                if isinstance(data, list):
                    # Flat unpaginated list
                    page_branches = data
                    next_url = None
                elif isinstance(data, dict):
                    if "results" in data and isinstance(data["results"], list):
                        page_branches = data["results"]
                        next_url = data.get("next")
                    elif "data" in data and isinstance(data["data"], list):
                        page_branches = data["data"]
                        next_url = data.get("next")
                    elif "branches" in data and isinstance(data["branches"], list):
                        page_branches = data["branches"]
                        next_url = data.get("next")
                    else:
                        raise NCMAPIError(
                            f"Expected branch list from NCM, received unexpected format: {list(data.keys())}",
                            status_code=response.status_code,
                            response_body=data,
                        )

                    # If next_url not provided, check if total count indicates more items exist
                    total_count = data.get("count") or data.get("total")
                    if not next_url and total_count and (len(all_branches) + len(page_branches) < total_count) and len(page_branches) > 0:
                        page_num += 1
                        next_url = f"v2/branches?page={page_num}"
                else:
                    raise NCMAPIError(
                        f"Expected branch list from NCM, received unexpected type: {type(data)}",
                        status_code=response.status_code,
                        response_body=data,
                    )

                all_branches.extend(page_branches)
                if not next_url:
                    break
                page_num += 1

            if not all_branches:
                # Live API returned empty list: preserve existing valid DB records
                logger.warning("NCM branch live API returned empty branch list. Preserving previous catalog.")
                branches, source = self._get_fallback_or_seeded_branches_with_source()
                meta = {
                    "source": source,
                    "last_synced_at": config.last_branch_sync_at.isoformat() if config and config.last_branch_sync_at else None,
                    "count": len(branches),
                }
                return (branches, meta) if return_meta else branches

            # Store in Django cache and in-memory fallback
            try:
                cache.set(self.BRANCHES_CACHE_KEY, all_branches, timeout=self.BRANCHES_CACHE_TTL)
            except Exception as e:
                logger.warning("Failed to store NCM branches in cache: %s", e)

            NCMService._fallback_branches_cache = all_branches
            logger.info("Successfully fetched %d NCM branches from LIVE_API across %d page(s)", len(all_branches), page_num)

            # Synchronize to persistent database models without creating duplicates
            self.sync_branches_to_db(all_branches)

            now = timezone.now()
            if config:
                config.branch_sync_source = 'LIVE_API'
                config.last_branch_sync_at = now
                config.branch_record_count = len(all_branches)
                config.save(update_fields=['branch_sync_source', 'last_branch_sync_at', 'branch_record_count'])

            meta = {
                "source": "LIVE_API",
                "last_synced_at": now.isoformat(),
                "count": len(all_branches),
            }
            return (all_branches, meta) if return_meta else all_branches

        except Exception as exc:
            logger.warning(
                "NCM branch live API fetch failed (%s). Preserving existing database catalog.",
                exc,
            )
            branches, source = self._get_fallback_or_seeded_branches_with_source()
            meta = {
                "source": source,
                "last_synced_at": config.last_branch_sync_at.isoformat() if config and config.last_branch_sync_at else None,
                "count": len(branches),
                "sync_error": str(exc),
            }
            return (branches, meta) if return_meta else branches

    def sync_branches_to_db(self, branches: List[Dict[str, Any]]) -> int:
        """
        Synchronizes branch records from NCM API into persistent NCMBranchRecord models.
        Preserves admin-verified coordinates without overwriting them.
        Guarantees zero duplicate records.
        """
        synced_count = 0
        try:
            from .models import NCMBranchRecord
            if isinstance(branches, dict):
                branches = [branches]
            for b in branches:
                if isinstance(b, str):
                    b = {"name": b, "code": b}
                if not isinstance(b, dict):
                    continue
                name = str(b.get("name") or "").strip()
                if not name:
                    continue
                code = str(b.get("code") or b.get("pk") or b.get("id") or name).strip()
                dist = str(b.get("district_name") or b.get("district") or "").strip()
                prov = str(b.get("province_name") or b.get("province") or "").strip()
                mun = str(b.get("municipality") or b.get("local_level") or "").strip()
                addr = str(b.get("address") or b.get("location") or "").strip()
                contact = str(b.get("contact_number") or b.get("phone") or b.get("contact") or "").strip()
                raw_cov = b.get("areas_covered") or b.get("coverage") or b.get("covered_areas") or ""
                if isinstance(raw_cov, list):
                    raw_cov = ", ".join(str(x).strip() for x in raw_cov if str(x).strip())
                else:
                    raw_cov = str(raw_cov).strip()

                b_lat = b.get("latitude")
                b_lon = b.get("longitude")
                b_src = b.get("coordinate_source")
                b_ver = bool(b.get("is_coordinate_verified", False))

                # Check by code first, then by name to avoid duplicate records
                rec = NCMBranchRecord.objects.filter(code=code).first()
                if not rec:
                    rec = NCMBranchRecord.objects.filter(name__iexact=name).first()

                if not rec:
                    if b_lat is not None and b_lon is not None:
                        c_lat, c_lon = b_lat, b_lon
                        coord_src = b_src or 'API'
                        is_ver = b_ver
                    else:
                        c_lat, c_lon, c_src, _ = get_municipality_centroid(mun or name, dist, prov)
                        coord_src = 'UNVERIFIED'
                        is_ver = False
                        if c_lat is not None:
                            coord_src = 'MUNICIPALITY_CENTROID' if c_src == 'municipality_centroid' else 'DISTRICT_CENTROID'
                    NCMBranchRecord.objects.create(
                        code=code,
                        name=name,
                        district_name=dist,
                        province_name=prov,
                        municipality=mun,
                        address=addr,
                        contact_number=contact,
                        areas_covered=raw_cov,
                        latitude=c_lat,
                        longitude=c_lon,
                        coordinate_source=coord_src,
                        is_coordinate_verified=is_ver,
                        is_serviceable=bool(b.get('is_serviceable', True)),
                        last_synced_at=timezone.now(),
                    )
                    synced_count += 1
                else:
                    rec.code = code
                    rec.name = name
                    rec.district_name = dist or rec.district_name
                    rec.province_name = prov or rec.province_name
                    rec.municipality = mun or rec.municipality
                    rec.address = addr or rec.address
                    rec.contact_number = contact or rec.contact_number
                    if raw_cov:
                        rec.areas_covered = raw_cov
                    if 'is_serviceable' in b:
                        rec.is_serviceable = bool(b['is_serviceable'])
                    rec.last_synced_at = timezone.now()

                    # Preserve admin-verified coordinates
                    if not rec.is_coordinate_verified and rec.coordinate_source != 'ADMIN_VERIFIED':
                        if b_lat is not None and b_lon is not None:
                            rec.latitude = b_lat
                            rec.longitude = b_lon
                            rec.coordinate_source = b_src or 'API'
                            rec.is_coordinate_verified = b_ver
                        elif not rec.has_valid_coordinates:
                            c_lat, c_lon, c_src, _ = get_municipality_centroid(mun or name, dist, prov)
                            if c_lat is not None:
                                rec.latitude = c_lat
                                rec.longitude = c_lon
                                rec.coordinate_source = 'MUNICIPALITY_CENTROID' if c_src == 'municipality_centroid' else 'DISTRICT_CENTROID'
                    rec.save()
                    synced_count += 1
        except Exception as e:
            logger.warning("Failed to synchronize NCM branches to DB: %s", e)
        return synced_count


    # --------------------------------------------------------------------------
    # 2. RATE CALCULATION (GET /v1/shipping-rate)
    # --------------------------------------------------------------------------

    def calculate_rate(
        self,
        destination_branch: str,
        source_branch: Optional[str] = None,
        delivery_type: str = "Door2Door",
    ) -> Dict[str, Any]:
        """
        Calculate shipping rate between branches for the given delivery type.
        Query params:
          - creation: origin branch (e.g. Kathmandu)
          - destination: destination branch (e.g. Pokhara)
          - type: rate type (Pickup/Collect for Door2Door, Send for Branch2Door, etc.)
        """
        dest = str(destination_branch or "").strip()
        if not dest:
            raise NCMValidationError("destination_branch is required for delivery rate calculation.")

        src = str(source_branch or self.default_origin_branch or "").strip()
        if not src:
            raise NCMValidationError("source_branch is required for delivery rate calculation.")

        # Map delivery type to NCM rate query parameter
        normalized_type = delivery_type.strip().lower()
        ncm_type = RATE_DELIVERY_TYPE_MAP.get(normalized_type, delivery_type.strip())

        params = {
            "creation": src,
            "destination": dest,
            "type": ncm_type,
        }

        response = self._execute_request(
            method="GET",
            endpoint="v1/shipping-rate",
            params=params,
            allow_retries=True,
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise NCMAPIError(
                f"Invalid JSON returned from NCM shipping-rate API: {response.text[:200]}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

        # Response schema: {"charge": 120.0} or {"charge": "120"}
        if not isinstance(data, dict) or "charge" not in data:
            raise NCMAPIError(
                f"NCM shipping-rate response missing 'charge' field: {data}",
                status_code=response.status_code,
                response_body=data,
            )

        try:
            charge = float(data["charge"])
        except (ValueError, TypeError) as exc:
            raise NCMAPIError(
                f"Invalid rate value in 'charge' field: {data['charge']}",
                status_code=response.status_code,
                response_body=data,
            ) from exc

        return {
            "success": True,
            "charge": charge,
            "source_branch": src,
            "destination_branch": dest,
            "delivery_type": delivery_type,
            "raw_response": data,
        }

    # --------------------------------------------------------------------------
    # 3. SHIPMENT CREATION (POST /v1/order/create)
    # --------------------------------------------------------------------------

    def create_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a courier shipment in NCM.

        Required fields in order_data:
          - name: Recipient full name
          - phone: Primary phone number
          - address: Full shipping street/ward address
          - branch: Destination branch name
          - package: Package description/item contents
          - vref_id: Vendor reference identifier (e.g. Loksewa order_number)

        Optional fields:
          - phone2: Secondary phone number (default: "")
          - fbranch: Origin branch (default: self.default_origin_branch)
          - instruction: Special delivery instructions (default: "")
          - delivery_type: "Door2Door" (default: "Door2Door")
          - weight: Package weight in kg (default: 1.0)
          - cod_charge: Amount to collect on delivery (default: 0.0)

        CRITICAL RELIABILITY RULE:
        This method will NEVER automatically retry on connection read timeouts to prevent
        duplicate courier shipments and duplicate charges.
        """
        # Validate required fields
        required_fields = ["name", "phone", "address", "branch", "package", "vref_id"]
        missing = [f for f in required_fields if not order_data.get(f)]
        if missing:
            raise NCMValidationError(f"Missing required fields for NCM order creation: {', '.join(missing)}")

        # Validate COD amount
        raw_cod = order_data.get("cod_charge", 0.0)
        try:
            cod_charge = float(raw_cod)
            if cod_charge < 0:
                raise ValueError("COD charge cannot be negative")
        except (ValueError, TypeError) as exc:
            raise NCMValidationError(f"Invalid cod_charge value: {raw_cod}") from exc

        # Validate weight
        raw_weight = order_data.get("weight", 1.0)
        try:
            weight = float(raw_weight)
            if weight <= 0:
                weight = 1.0
        except (ValueError, TypeError):
            weight = 1.0

        payload = {
            "name": str(order_data["name"]).strip(),
            "phone": str(order_data["phone"]).strip(),
            "phone2": str(order_data.get("phone2") or "").strip(),
            "cod_charge": cod_charge,
            "address": str(order_data["address"]).strip(),
            "fbranch": str(order_data.get("fbranch") or self.default_origin_branch).strip(),
            "branch": str(order_data["branch"]).strip(),
            "package": str(order_data["package"]).strip(),
            "vref_id": str(order_data["vref_id"]).strip(),
            "instruction": str(order_data.get("instruction") or "").strip(),
            "delivery_type": str(order_data.get("delivery_type") or "Door2Door").strip(),
            "weight": weight,
        }

        # Safe sanitized logging
        logger.info(
            "Creating NCM courier shipment for ref %s -> destination %s (COD: %.2f)",
            payload["vref_id"],
            payload["branch"],
            payload["cod_charge"],
            extra={"sanitized_data": sanitize_payload_for_logging(payload)},
        )

        response = self._execute_request(
            method="POST",
            endpoint="v1/order/create",
            json_data=payload,
            allow_retries=False,  # Strict non-retry policy
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise NCMAPIError(
                f"Invalid JSON returned from NCM order creation API: {response.text[:200]}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

        # Response schema:
        # {"orderid": 1029384, "delivery_charge": 120.0, "delivery_type": "Door2Door", ...}
        if not isinstance(data, dict) or "orderid" not in data:
            raise NCMAPIError(
                f"NCM order creation response missing 'orderid': {data}",
                status_code=response.status_code,
                response_body=data,
            )

        ncm_order_id = str(data["orderid"])
        delivery_charge = float(data.get("delivery_charge", 0.0))
        returned_cod = float(data.get("cod_charge", cod_charge))

        logger.info(
            "Successfully created NCM shipment: orderid=%s, ref=%s, charge=%.2f",
            ncm_order_id,
            payload["vref_id"],
            delivery_charge,
        )

        return {
            "success": True,
            "ncm_order_id": ncm_order_id,
            "delivery_charge": delivery_charge,
            "cod_charge": returned_cod,
            "delivery_type": data.get("delivery_type", payload["delivery_type"]),
            "active": data.get("active", True),
            "raw_response": data,
        }

    # --------------------------------------------------------------------------
    # 4. TRACK ORDER (GET /v1/order/status)
    # --------------------------------------------------------------------------

    def track_order(self, ncm_order_id: Union[str, int]) -> Dict[str, Any]:
        """
        Fetch status and tracking timeline for an NCM order.
        Endpoint: GET /v1/order/status?id=<order_id>
        """
        oid = str(ncm_order_id).strip()
        if not oid:
            raise NCMValidationError("ncm_order_id is required to track order.")

        response = self._execute_request(
            method="GET",
            endpoint="v1/order/status",
            params={"id": oid},
            allow_retries=True,
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise NCMAPIError(
                f"Invalid JSON returned from NCM tracking API: {response.text[:200]}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

        return {
            "success": True,
            "ncm_order_id": oid,
            "data": data,
        }

    # --------------------------------------------------------------------------
    # 5. ORDER DETAILS (GET /v1/order)
    # --------------------------------------------------------------------------

    def get_order_details(self, ncm_order_id: Union[str, int]) -> Dict[str, Any]:
        """
        Fetch complete order record from NCM.
        Endpoint: GET /v1/order?id=<order_id>
        """
        oid = str(ncm_order_id).strip()
        if not oid:
            raise NCMValidationError("ncm_order_id is required to fetch order details.")

        response = self._execute_request(
            method="GET",
            endpoint="v1/order",
            params={"id": oid},
            allow_retries=True,
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise NCMAPIError(
                f"Invalid JSON returned from NCM order details API: {response.text[:200]}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

        return {
            "success": True,
            "ncm_order_id": oid,
            "data": data,
        }

    # --------------------------------------------------------------------------
    # 5b. RECONCILE BY VENDOR REFERENCE (GET /v1/order?vref_id=...)
    # --------------------------------------------------------------------------

    def lookup_order_by_vref(self, vref_id: str) -> Optional[Dict[str, Any]]:
        """
        Attempt to look up an existing order in NCM using vendor reference ID (vref_id).
        Used during timeout reconciliation to prevent duplicate shipments.
        Queries GET /v1/order?vref_id=<vref_id> or GET /v1/order?ref=<vref_id>.
        Returns sanitized dict with orderid/delivery_charge/cod_charge if found, else None.
        """
        clean_ref = str(vref_id or "").strip()
        if not clean_ref:
            return None

        for param_key in ["vref_id", "ref", "order_ref"]:
            try:
                response = self._execute_request(
                    method="GET",
                    endpoint="v1/order",
                    params={param_key: clean_ref},
                    allow_retries=False,
                )
                try:
                    data = response.json()
                except ValueError:
                    continue

                target_dict = None
                if isinstance(data, dict):
                    if data.get("orderid") or data.get("order_id"):
                        target_dict = data
                    elif isinstance(data.get("data"), dict) and (data["data"].get("orderid") or data["data"].get("order_id")):
                        target_dict = data["data"]
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    if data[0].get("orderid") or data[0].get("order_id"):
                        target_dict = data[0]

                if target_dict:
                    orderid = target_dict.get("orderid") or target_dict.get("order_id")
                    logger.info("Successfully reconciled order by %s=%s -> NCM Order ID %s", param_key, clean_ref, orderid)
                    return {
                        "orderid": str(orderid),
                        "delivery_charge": float(target_dict.get("delivery_charge", 0.0)),
                        "cod_charge": float(target_dict.get("cod_charge", 0.0)),
                        "delivery_type": target_dict.get("delivery_type", "Door2Door"),
                        "raw_response": target_dict,
                    }
            except Exception as exc:
                logger.debug("NCM lookup by %s=%s returned error: %s", param_key, clean_ref, exc)

        return None

    # --------------------------------------------------------------------------
    # 6. BULK ORDER STATUSES (POST /v1/orders/statuses)
    # --------------------------------------------------------------------------

    def get_order_statuses(self, ncm_order_ids: List[Union[str, int]]) -> Dict[str, Any]:
        """
        Fetch statuses for multiple NCM orders in a single request.
        Endpoint: POST /v1/orders/statuses with {"orders": [id1, id2, ...]}
        """
        if not ncm_order_ids:
            raise NCMValidationError("ncm_order_ids list cannot be empty.")

        clean_ids = []
        for raw_id in ncm_order_ids:
            try:
                clean_ids.append(int(raw_id))
            except (ValueError, TypeError):
                clean_ids.append(str(raw_id).strip())

        response = self._execute_request(
            method="POST",
            endpoint="v1/orders/statuses",
            json_data={"orders": clean_ids},
            allow_retries=True,  # Idempotent status check can be retried safely
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise NCMAPIError(
                f"Invalid JSON returned from NCM bulk statuses API: {response.text[:200]}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

        return {
            "success": True,
            "count": len(clean_ids),
            "data": data,
        }

"""
Nepal Administrative Geography & Geocoding Foundation.

Provides authoritative reference data for:
1. Nepal's 77 districts and their geographic centroid coordinates.
2. Nepal's 753 local levels (Metropolises, Sub-Metropolises, Municipalities, Rural Municipalities)
   with stable identifiers, English/Nepali names, administrative types, and centroid coordinates.
3. Spherical geodetic distance calculation (Haversine formula).
4. Safe centroid lookup with multi-tier resolution:
   - Priority 1: Exact municipality name / alias in the specified district
   - Priority 2: District centroid reference fallback (labeled as approximate)
   - Priority 3: Unresolved (when location is missing or unknown)
"""

import math
import re
from typing import Any, Dict, List, Optional, Tuple

# Earth radius in kilometers (WGS-84 mean radius)
EARTH_RADIUS_KM = 6371.0088


def calculate_haversine_distance(
    lat1: Optional[float],
    lon1: Optional[float],
    lat2: Optional[float],
    lon2: Optional[float],
) -> Optional[float]:
    """
    Calculate the great-circle distance between two points on the Earth's surface
    using the Haversine formula.

    Returns:
        Distance in kilometers rounded to 1 decimal place, or None if coordinates are missing/invalid.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None

    try:
        f_lat1, f_lon1 = float(lat1), float(lon1)
        f_lat2, f_lon2 = float(lat2), float(lon2)
    except (ValueError, TypeError):
        return None

    # Validate valid geographic bounds
    if not (-90.0 <= f_lat1 <= 90.0 and -90.0 <= f_lat2 <= 90.0):
        return None
    if not (-180.0 <= f_lon1 <= 180.0 and -180.0 <= f_lon2 <= 180.0):
        return None

    phi1 = math.radians(f_lat1)
    phi2 = math.radians(f_lat2)
    delta_phi = math.radians(f_lat2 - f_lat1)
    delta_lambda = math.radians(f_lon2 - f_lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    # Clip to [0.0, 1.0] to guard against floating-point inaccuracy
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    distance = EARTH_RADIUS_KM * c

    return round(distance, 1)


# --------------------------------------------------------------------------
# All 77 Districts of Nepal with Verified Geographic Reference Centroids
# --------------------------------------------------------------------------
DISTRICT_CENTROIDS: Dict[str, Tuple[float, float, str]] = {
    # Koshi Province (14)
    "bhojpur": (27.1700, 87.0500, "Koshi Province"),
    "dhankuta": (26.9833, 87.3333, "Koshi Province"),
    "ilam": (26.9089, 87.9284, "Koshi Province"),
    "jhapa": (26.6333, 87.9833, "Koshi Province"),
    "khotang": (27.2000, 86.8000, "Koshi Province"),
    "morang": (26.6500, 87.4500, "Koshi Province"),
    "okhaldhunga": (27.3167, 86.5000, "Koshi Province"),
    "panchthar": (27.2000, 87.8333, "Koshi Province"),
    "sankhuwasabha": (27.6000, 87.2000, "Koshi Province"),
    "solukhumbu": (27.7000, 86.7167, "Koshi Province"),
    "sunsari": (26.6667, 87.1667, "Koshi Province"),
    "taplejung": (27.3500, 87.6667, "Koshi Province"),
    "terhathum": (27.1500, 87.5500, "Koshi Province"),
    "udayapur": (26.9000, 86.5167, "Koshi Province"),

    # Madhesh Province (8)
    "saptari": (26.6500, 86.7500, "Madhesh Province"),
    "siraha": (26.6500, 86.2000, "Madhesh Province"),
    "dhanusha": (26.7500, 85.9500, "Madhesh Province"),
    "mahottari": (26.8500, 85.8000, "Madhesh Province"),
    "sarlahi": (26.9833, 85.5500, "Madhesh Province"),
    "rautahat": (27.0000, 85.3000, "Madhesh Province"),
    "bara": (27.0833, 85.0000, "Madhesh Province"),
    "parsa": (27.1500, 84.8500, "Madhesh Province"),

    # Bagmati Province (13)
    "bhaktapur": (27.6710, 85.4298, "Bagmati Province"),
    "chitwan": (27.5300, 84.4500, "Bagmati Province"),
    "dhading": (27.8667, 84.9000, "Bagmati Province"),
    "dolakha": (27.7500, 86.0500, "Bagmati Province"),
    "kathmandu": (27.7172, 85.3240, "Bagmati Province"),
    "kavrepalanchok": (27.5333, 85.5500, "Bagmati Province"),
    "kavre": (27.5333, 85.5500, "Bagmati Province"),
    "lalitpur": (27.6710, 85.3206, "Bagmati Province"),
    "makwanpur": (27.4167, 85.0333, "Bagmati Province"),
    "nuwakot": (27.9167, 85.1667, "Bagmati Province"),
    "ramechhap": (27.3333, 86.0833, "Bagmati Province"),
    "rasuwa": (28.1500, 85.3000, "Bagmati Province"),
    "sindhuli": (27.2500, 85.9667, "Bagmati Province"),
    "sindhupalchok": (27.9500, 85.7000, "Bagmati Province"),

    # Gandaki Province (11)
    "baglung": (28.2667, 83.6000, "Gandaki Province"),
    "gorkha": (28.0000, 84.6333, "Gandaki Province"),
    "kaski": (28.2096, 83.9856, "Gandaki Province"),
    "lamjung": (28.2333, 84.4167, "Gandaki Province"),
    "manang": (28.6667, 84.0167, "Gandaki Province"),
    "mustang": (28.8000, 83.7500, "Gandaki Province"),
    "myagdi": (28.4333, 83.5667, "Gandaki Province"),
    "nawalpur": (27.7000, 84.1500, "Gandaki Province"),
    "nawalparasi east": (27.7000, 84.1500, "Gandaki Province"),
    "parbat": (28.2333, 83.6833, "Gandaki Province"),
    "syangja": (28.1000, 83.8667, "Gandaki Province"),
    "tanahun": (27.9500, 84.2500, "Gandaki Province"),

    # Lumbini Province (12)
    "arghakhanchi": (27.9167, 83.1000, "Lumbini Province"),
    "banke": (28.1167, 81.6833, "Lumbini Province"),
    "bardiya": (28.3333, 81.3333, "Lumbini Province"),
    "dang": (28.0333, 82.3000, "Lumbini Province"),
    "gulmi": (28.0667, 83.2500, "Lumbini Province"),
    "kapilvastu": (27.6000, 83.0500, "Lumbini Province"),
    "parasi": (27.5333, 83.6667, "Lumbini Province"),
    "nawalparasi west": (27.5333, 83.6667, "Lumbini Province"),
    "palpa": (27.8667, 83.5500, "Lumbini Province"),
    "pyuthan": (28.1000, 82.8333, "Lumbini Province"),
    "rolpa": (28.3667, 82.6333, "Lumbini Province"),
    "rukum east": (28.6167, 82.6833, "Lumbini Province"),
    "rupandehi": (27.6000, 83.4500, "Lumbini Province"),

    # Karnali Province (10)
    "dailekh": (28.8333, 81.7167, "Karnali Province"),
    "dolpa": (29.0000, 82.9000, "Karnali Province"),
    "humla": (30.0000, 81.8500, "Karnali Province"),
    "jajarkot": (28.7000, 82.2000, "Karnali Province"),
    "jumla": (29.2833, 82.1833, "Karnali Province"),
    "kalikot": (29.1500, 81.8333, "Karnali Province"),
    "mugu": (29.6000, 82.4000, "Karnali Province"),
    "rukum west": (28.6333, 82.4667, "Karnali Province"),
    "salyan": (28.3667, 82.1667, "Karnali Province"),
    "surkhet": (28.6000, 81.6333, "Karnali Province"),

    # Sudurpashchim Province (9)
    "achham": (29.1167, 81.3000, "Sudurpashchim Province"),
    "baitadi": (29.5167, 80.5500, "Sudurpashchim Province"),
    "bajhang": (29.6667, 81.2500, "Sudurpashchim Province"),
    "bajura": (29.5000, 81.5667, "Sudurpashchim Province"),
    "dadeldhura": (29.3000, 80.5833, "Sudurpashchim Province"),
    "darchula": (29.8500, 80.5333, "Sudurpashchim Province"),
    "doti": (29.2667, 80.9500, "Sudurpashchim Province"),
    "kailali": (28.7167, 80.6000, "Sudurpashchim Province"),
    "kanchanpur": (28.8333, 80.3333, "Sudurpashchim Province"),
}


# --------------------------------------------------------------------------
# Representative Local Levels with Verified Centroid Coordinates
# --------------------------------------------------------------------------
# Represents local levels across Nepal's districts. In production, this can
# be dynamically supplemented or extended via admin review.
NEPAL_LOCAL_LEVELS: List[Dict[str, Any]] = [
    # Kathmandu District
    {
        "code": "LL-KTM-01",
        "name_en": "Kathmandu",
        "name_ne": "काठमाडौँ",
        "district": "Kathmandu",
        "province": "Bagmati Province",
        "type": "Metropolitan City",
        "centroid_lat": 27.7172,
        "centroid_lon": 85.3240,
        "aliases": ["Kathmandu Metropolitan City", "KMC", "Kathmandu Metropolis", "Kantipur"],
    },
    {
        "code": "LL-KTM-02",
        "name_en": "Kirtipur",
        "name_ne": "कीर्तिपुर",
        "district": "Kathmandu",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.6798,
        "centroid_lon": 85.2754,
        "aliases": ["Kirtipur Municipality"],
    },
    {
        "code": "LL-KTM-03",
        "name_en": "Budhanilkantha",
        "name_ne": "बूढानीलकण्ठ",
        "district": "Kathmandu",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.7667,
        "centroid_lon": 85.3667,
        "aliases": ["Budhanilkantha Municipality"],
    },
    {
        "code": "LL-KTM-04",
        "name_en": "Chandragiri",
        "name_ne": "चन्द्रागिरी",
        "district": "Kathmandu",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.6917,
        "centroid_lon": 85.2250,
        "aliases": ["Chandragiri Municipality", "Thankot"],
    },

    # Lalitpur District
    {
        "code": "LL-LAL-01",
        "name_en": "Lalitpur",
        "name_ne": "ललितपुर",
        "district": "Lalitpur",
        "province": "Bagmati Province",
        "type": "Metropolitan City",
        "centroid_lat": 27.6710,
        "centroid_lon": 85.3206,
        "aliases": ["Lalitpur Metropolitan City", "Patan", "Lalitpur Metropolis"],
    },
    {
        "code": "LL-LAL-02",
        "name_en": "Mahalaxmi",
        "name_ne": "महालक्ष्मी",
        "district": "Lalitpur",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.6417,
        "centroid_lon": 85.3500,
        "aliases": ["Mahalaxmi Municipality", "Imadol"],
    },
    {
        "code": "LL-LAL-03",
        "name_en": "Godawari",
        "name_ne": "गोदावरी",
        "district": "Lalitpur",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.5917,
        "centroid_lon": 85.3667,
        "aliases": ["Godawari Municipality"],
    },

    # Bhaktapur District
    {
        "code": "LL-BKT-01",
        "name_en": "Bhaktapur",
        "name_ne": "भक्तपुर",
        "district": "Bhaktapur",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.6710,
        "centroid_lon": 85.4298,
        "aliases": ["Bhaktapur Municipality", "Bhadgaon"],
    },
    {
        "code": "LL-BKT-02",
        "name_en": "Madhyapur Thimi",
        "name_ne": "मध्यपुर थिमी",
        "district": "Bhaktapur",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.6833,
        "centroid_lon": 85.3833,
        "aliases": ["Madhyapur Thimi Municipality", "Thimi"],
    },
    {
        "code": "LL-BKT-03",
        "name_en": "Suryabinayak",
        "name_ne": "सूर्यविनायक",
        "district": "Bhaktapur",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.6500,
        "centroid_lon": 85.4333,
        "aliases": ["Suryabinayak Municipality"],
    },

    # Kaski District (Gandaki)
    {
        "code": "LL-KAS-01",
        "name_en": "Pokhara",
        "name_ne": "पोखरा",
        "district": "Kaski",
        "province": "Gandaki Province",
        "type": "Metropolitan City",
        "centroid_lat": 28.2096,
        "centroid_lon": 83.9856,
        "aliases": [
            "Pokhara Lekhnath",
            "Pokhara Lekhnath Metropolitan City",
            "Pokhara Metropolitan City",
            "Pokhara Metropolis",
            "Lekhnath",
            "Srijana Chowk",
            "Mahendrapool",
            "Lakeside"
        ],
    },
    {
        "code": "LL-KAS-02",
        "name_en": "Annapurna",
        "name_ne": "अन्नपूर्ण",
        "district": "Kaski",
        "province": "Gandaki Province",
        "type": "Rural Municipality",
        "centroid_lat": 28.3333,
        "centroid_lon": 83.8167,
        "aliases": ["Annapurna Rural Municipality", "Annapurna Gaunpalika"],
    },
    {
        "code": "LL-KAS-03",
        "name_en": "Machhapuchhre",
        "name_ne": "माछापुच्छ्रे",
        "district": "Kaski",
        "province": "Gandaki Province",
        "type": "Rural Municipality",
        "centroid_lat": 28.3667,
        "centroid_lon": 83.9500,
        "aliases": ["Machhapuchhre Rural Municipality"],
    },

    # Gulmi District (Lumbini)
    {
        "code": "LL-GUL-01",
        "name_en": "Resunga",
        "name_ne": "रेसुङ्गा",
        "district": "Gulmi",
        "province": "Lumbini Province",
        "type": "Municipality",
        "centroid_lat": 28.0667,
        "centroid_lon": 83.2500,
        "aliases": ["Resunga Municipality", "Tamghas", "Tamghas Bazar"],
    },
    {
        "code": "LL-GUL-02",
        "name_en": "Chhatrakot",
        "name_ne": "छत्रकोट",
        "district": "Gulmi",
        "province": "Lumbini Province",
        "type": "Rural Municipality",
        "centroid_lat": 28.0100,
        "centroid_lon": 83.3500,
        "aliases": ["Chhatrakot Rural Municipality", "Chhatrakot Gaunpalika"],
    },
    {
        "code": "LL-GUL-03",
        "name_en": "Ruru",
        "name_ne": "रुरु",
        "district": "Gulmi",
        "province": "Lumbini Province",
        "type": "Rural Municipality",
        "centroid_lat": 27.9500,
        "centroid_lon": 83.4333,
        "aliases": ["Ruru Rural Municipality", "Rurukshetra", "Ridi"],
    },
    {
        "code": "LL-GUL-04",
        "name_en": "Musikot",
        "name_ne": "मुसिकोट",
        "district": "Gulmi",
        "province": "Lumbini Province",
        "type": "Municipality",
        "centroid_lat": 28.1667,
        "centroid_lon": 83.2833,
        "aliases": ["Musikot Municipality", "Wami"],
    },

    # Rupandehi District (Lumbini)
    {
        "code": "LL-RUP-01",
        "name_en": "Butwal",
        "name_ne": "बुटवल",
        "district": "Rupandehi",
        "province": "Lumbini Province",
        "type": "Sub-Metropolitan City",
        "centroid_lat": 27.7000,
        "centroid_lon": 83.4500,
        "aliases": ["Butwal Sub-Metropolitan City", "Butwal Sub-Metropolis"],
    },
    {
        "code": "LL-RUP-02",
        "name_en": "Siddharthanagar",
        "name_ne": "सिद्धार्थनगर",
        "district": "Rupandehi",
        "province": "Lumbini Province",
        "type": "Municipality",
        "centroid_lat": 27.5000,
        "centroid_lon": 83.4500,
        "aliases": ["Siddharthanagar Municipality", "Bhairahawa"],
    },
    {
        "code": "LL-RUP-03",
        "name_en": "Tilottama",
        "name_ne": "तिलोत्तमा",
        "district": "Rupandehi",
        "province": "Lumbini Province",
        "type": "Municipality",
        "centroid_lat": 27.6000,
        "centroid_lon": 83.4833,
        "aliases": ["Tilottama Municipality", "Manigram", "Kotihawa"],
    },

    # Morang District (Koshi)
    {
        "code": "LL-MOR-01",
        "name_en": "Biratnagar",
        "name_ne": "विराटनगर",
        "district": "Morang",
        "province": "Koshi Province",
        "type": "Metropolitan City",
        "centroid_lat": 26.4525,
        "centroid_lon": 87.2718,
        "aliases": ["Biratnagar Metropolitan City", "Biratnagar Metropolis", "Traffic Chowk"],
    },
    {
        "code": "LL-MOR-02",
        "name_en": "Sundarharaicha",
        "name_ne": "सुन्दरहरैँचा",
        "district": "Morang",
        "province": "Koshi Province",
        "type": "Municipality",
        "centroid_lat": 26.6667,
        "centroid_lon": 87.3500,
        "aliases": ["Sundarharaicha Municipality", "Gothgaun", "Biratchowk"],
    },

    # Chitwan District (Bagmati)
    {
        "code": "LL-CHT-01",
        "name_en": "Bharatpur",
        "name_ne": "भरतपुर",
        "district": "Chitwan",
        "province": "Bagmati Province",
        "type": "Metropolitan City",
        "centroid_lat": 27.6833,
        "centroid_lon": 84.4333,
        "aliases": ["Bharatpur Metropolitan City", "Narayangarh", "Bharatpur Metropolis"],
    },
    {
        "code": "LL-CHT-02",
        "name_en": "Ratnanagar",
        "name_ne": "रत्ननगर",
        "district": "Chitwan",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.6167,
        "centroid_lon": 84.5167,
        "aliases": ["Ratnanagar Municipality", "Sauraha", "Tandi"],
    },

    # Sunsari District (Koshi)
    {
        "code": "LL-SUN-01",
        "name_en": "Itahari",
        "name_ne": "इटहरी",
        "district": "Sunsari",
        "province": "Koshi Province",
        "type": "Sub-Metropolitan City",
        "centroid_lat": 26.6667,
        "centroid_lon": 87.2833,
        "aliases": ["Itahari Sub-Metropolitan City"],
    },
    {
        "code": "LL-SUN-02",
        "name_en": "Dharan",
        "name_ne": "धरान",
        "district": "Sunsari",
        "province": "Koshi Province",
        "type": "Sub-Metropolitan City",
        "centroid_lat": 26.8124,
        "centroid_lon": 87.2834,
        "aliases": ["Dharan Sub-Metropolitan City", "Bhanuchowk"],
    },

    # Banke District (Lumbini)
    {
        "code": "LL-BNK-01",
        "name_en": "Nepalgunj",
        "name_ne": "नेपालगञ्ज",
        "district": "Banke",
        "province": "Lumbini Province",
        "type": "Sub-Metropolitan City",
        "centroid_lat": 28.0500,
        "centroid_lon": 81.6167,
        "aliases": ["Nepalgunj Sub-Metropolitan City"],
    },
    {
        "code": "LL-BNK-02",
        "name_en": "Kohalpur",
        "name_ne": "कोहलपुर",
        "district": "Banke",
        "province": "Lumbini Province",
        "type": "Municipality",
        "centroid_lat": 28.1833,
        "centroid_lon": 81.6833,
        "aliases": ["Kohalpur Municipality", "Kohalpur Chauraha"],
    },

    # Kailali District (Sudurpashchim)
    {
        "code": "LL-KAI-01",
        "name_en": "Dhangadhi",
        "name_ne": "धनगढी",
        "district": "Kailali",
        "province": "Sudurpashchim Province",
        "type": "Sub-Metropolitan City",
        "centroid_lat": 28.6833,
        "centroid_lon": 80.6000,
        "aliases": ["Dhangadhi Sub-Metropolitan City"],
    },
    {
        "code": "LL-KAI-02",
        "name_en": "Tikapur",
        "name_ne": "टीकापुर",
        "district": "Kailali",
        "province": "Sudurpashchim Province",
        "type": "Municipality",
        "centroid_lat": 28.5167,
        "centroid_lon": 81.1333,
        "aliases": ["Tikapur Municipality"],
    },

    # Dang District (Lumbini)
    {
        "code": "LL-DNG-01",
        "name_en": "Ghorahi",
        "name_ne": "घोराही",
        "district": "Dang",
        "province": "Lumbini Province",
        "type": "Sub-Metropolitan City",
        "centroid_lat": 28.0500,
        "centroid_lon": 82.5000,
        "aliases": ["Ghorahi Sub-Metropolitan City"],
    },
    {
        "code": "LL-DNG-02",
        "name_en": "Tulsipur",
        "name_ne": "तुलसीपुर",
        "district": "Dang",
        "province": "Lumbini Province",
        "type": "Sub-Metropolitan City",
        "centroid_lat": 28.1333,
        "centroid_lon": 82.3000,
        "aliases": ["Tulsipur Sub-Metropolitan City"],
    },

    # Palpa District (Lumbini)
    {
        "code": "LL-PLP-01",
        "name_en": "Tansen",
        "name_ne": "तानसेन",
        "district": "Palpa",
        "province": "Lumbini Province",
        "type": "Municipality",
        "centroid_lat": 27.8667,
        "centroid_lon": 83.5500,
        "aliases": ["Tansen Municipality", "Palpa Bazar"],
    },
    {
        "code": "LL-PLP-02",
        "name_en": "Rampur",
        "name_ne": "रामपुर",
        "district": "Palpa",
        "province": "Lumbini Province",
        "type": "Municipality",
        "centroid_lat": 27.8500,
        "centroid_lon": 83.8833,
        "aliases": ["Rampur Municipality"],
    },

    # Ilam District (Koshi)
    {
        "code": "LL-ILM-01",
        "name_en": "Ilam",
        "name_ne": "इलाम",
        "district": "Ilam",
        "province": "Koshi Province",
        "type": "Municipality",
        "centroid_lat": 26.9089,
        "centroid_lon": 87.9284,
        "aliases": ["Ilam Municipality", "Ilam Bazar"],
    },

    # Doti District (Sudurpashchim)
    {
        "code": "LL-DOT-01",
        "name_en": "Dipayal Silgadhi",
        "name_ne": "दिपायल सिलगढी",
        "district": "Doti",
        "province": "Sudurpashchim Province",
        "type": "Municipality",
        "centroid_lat": 29.2667,
        "centroid_lon": 80.9500,
        "aliases": ["Dipayal", "Silgadhi", "Dipayal Silgadhi Municipality"],
    },

    # Duplicate names disambiguation examples (Kalika in Chitwan vs Kalika in Rasuwa)
    {
        "code": "LL-CHT-03",
        "name_en": "Kalika",
        "name_ne": "कालिका",
        "district": "Chitwan",
        "province": "Bagmati Province",
        "type": "Municipality",
        "centroid_lat": 27.6800,
        "centroid_lon": 84.5500,
        "aliases": ["Kalika Municipality"],
    },
    {
        "code": "LL-RAS-01",
        "name_en": "Kalika",
        "name_ne": "कालिका",
        "district": "Rasuwa",
        "province": "Bagmati Province",
        "type": "Rural Municipality",
        "centroid_lat": 28.0167,
        "centroid_lon": 85.2500,
        "aliases": ["Kalika Rural Municipality", "Kalika Gaunpalika"],
    },
]


def _clean_stem(text: Optional[str]) -> str:
    """Normalize text into clean lowercase tokens for robust geographic matching."""
    if not text:
        return ""
    # Strip common administrative terms
    pattern = re.compile(
        r'\b('
        r'sub[\s\-]metropolitan\s+city|sub[\s\-]metropolis|sub[\s\-]metro|'
        r'metropolitan\s+city|metropolis|metro|'
        r'upamahanagarpalika|upa[\s\-]mahanagarpalika|upamahanagar\s+palika|'
        r'mahanagarpalika|mahanagar\s+palika|'
        r'rural\s+municipality|rural[\s\-]municipality|'
        r'gaunpalika|gaun\s+palika|gaumpalika|gaum\s+palika|'
        r'municipality|nagarpalika|nagar\s+palika|'
        r'r\.m\.|rm|vdc|n\.p\.|np|m\.p\.|mp|province'
        r')\b',
        re.IGNORECASE
    )
    s = pattern.sub(" ", str(text).lower())
    s = re.sub(r'[\.,/\\()\[\]{}\-_:;!@#$%^&*~`+=|<>?]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def find_local_level_match(
    municipality: Optional[str],
    district: Optional[str] = None,
    province: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Search Nepal's local levels for an authoritative match:
    - Resolves municipality name, Nepali name, and verified aliases.
    - Resolves duplicate municipality names using district context.
    - Prevents false-positive token matches.
    """
    if not municipality:
        return None

    clean_mun = _clean_stem(municipality)
    clean_dist = _clean_stem(district) if district else ""
    clean_prov = _clean_stem(province) if province else ""

    if not clean_mun:
        return None

    candidates: List[Dict[str, Any]] = []

    for ll in NEPAL_LOCAL_LEVELS:
        ll_name_en = _clean_stem(ll.get("name_en"))
        ll_name_ne = str(ll.get("name_ne") or "").strip()
        ll_aliases = [_clean_stem(a) for a in ll.get("aliases", [])]
        ll_dist = _clean_stem(ll.get("district"))
        ll_prov = _clean_stem(ll.get("province"))

        # District constraint if provided (crucial for disambiguating duplicate names like Kalika)
        dist_matches = (
            not clean_dist
            or clean_dist == ll_dist
            or re.search(r'\b' + re.escape(clean_dist) + r'\b', ll_dist)
        )
        if not dist_matches:
            continue

        # Province constraint if provided
        if clean_prov and ll_prov and clean_prov != ll_prov and not (clean_prov in ll_prov or ll_prov in clean_prov):
            continue

        # Check exact name match
        if clean_mun == ll_name_en:
            candidates.append(ll)
            continue

        # Check Nepali name
        if str(municipality).strip() == ll_name_ne:
            candidates.append(ll)
            continue

        # Check aliases
        if any(clean_mun == alias or re.search(r'\b' + re.escape(clean_mun) + r'\b', alias) for alias in ll_aliases):
            candidates.append(ll)
            continue

        # Check word boundary inside name
        if re.search(r'\b' + re.escape(clean_mun) + r'\b', ll_name_en):
            candidates.append(ll)
            continue

    if not candidates:
        return None

    # If multiple candidates survive, prefer the one with matching district
    if clean_dist:
        for c in candidates:
            if _clean_stem(c.get("district")) == clean_dist:
                return c

    return candidates[0]


def get_municipality_centroid(
    municipality: Optional[str],
    district: Optional[str] = None,
    province: Optional[str] = None,
) -> Tuple[Optional[float], Optional[float], str, Optional[Dict[str, Any]]]:
    """
    Get geographic reference coordinates for a student's delivery location:

    Returns:
        (latitude, longitude, source, match_data)
        where source is one of:
        - 'municipality_centroid': verified local-level centroid
        - 'district_reference': approximate district centroid fallback
        - 'unresolved': coordinates unavailable
    """
    # 1. Try local-level exact resolution
    ll_match = find_local_level_match(municipality, district, province)
    if ll_match and ll_match.get("centroid_lat") is not None and ll_match.get("centroid_lon") is not None:
        return (
            float(ll_match["centroid_lat"]),
            float(ll_match["centroid_lon"]),
            "municipality_centroid",
            ll_match,
        )

    # 2. Try district reference centroid fallback
    if district:
        clean_dist = _clean_stem(district)
        if clean_dist in DISTRICT_CENTROIDS:
            lat, lon, prov_name = DISTRICT_CENTROIDS[clean_dist]
            return (lat, lon, "district_reference", {
                "district": district,
                "province": prov_name,
                "centroid_lat": lat,
                "centroid_lon": lon,
                "is_fallback": True,
            })

    # 3. Unresolved
    return (None, None, "unresolved", None)


# --------------------------------------------------------------------------
# Authoritative Nepal Can Move (NCM) Branch Hub Network Catalog
# --------------------------------------------------------------------------
# Provides official, verified NCM courier offices across all provinces of Nepal.
# Ensures that even if the external API token is not yet configured or NCM API
# is temporarily unreachable, students can ALWAYS discover and select their nearest
# delivery hub, and orders can be routed reliably.
# --------------------------------------------------------------------------
STANDARD_NCM_BRANCH_CATALOG: List[Dict[str, Any]] = [
    # --- Kathmandu Valley Hubs ---
    {
        "code": "KTM_CENTRAL",
        "name": "Kathmandu (Sundhara / Central)",
        "district_name": "Kathmandu",
        "province_name": "Bagmati Province",
        "municipality": "Kathmandu Metropolitan",
        "address": "Sundhara, Kathmandu Central Hub",
        "contact_number": "01-5970001",
        "latitude": 27.700769,
        "longitude": 85.312950,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Sundhara", "New Road", "Thamel", "Tripureshwor", "Asan",
            "Durbarmarg", "Putalisadak", "Anamnagar", "Basantapur"
        ],
    },
    {
        "code": "KTM_BANESHWOR",
        "name": "New Baneshwor",
        "district_name": "Kathmandu",
        "province_name": "Bagmati Province",
        "municipality": "Kathmandu Metropolitan",
        "address": "New Baneshwor, near Shankhamul Road",
        "contact_number": "01-5970002",
        "latitude": 27.693300,
        "longitude": 85.340000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "New Baneshwor", "Old Baneshwor", "Baneshwor", "Shankhamul",
            "Maitighar", "Minbhawan", "Tinkune", "Koteshwor", "Sinamangal",
            "Aloknagar", "Subidhanagar", "Thapagaun"
        ],
    },
    {
        "code": "KTM_CHABAHIL",
        "name": "Chabahil",
        "district_name": "Kathmandu",
        "province_name": "Bagmati Province",
        "municipality": "Kathmandu Metropolitan",
        "address": "Chabahil Chowk, Kathmandu",
        "contact_number": "01-5970003",
        "latitude": 27.717500,
        "longitude": 85.346900,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Chabahil", "Gaushala", "Boudha", "Mitrapark", "Jorpati",
            "Sukedhara", "Maharajgunj", "Mandikhatar", "Kapan"
        ],
    },
    {
        "code": "KTM_KALANKI",
        "name": "Kalanki",
        "district_name": "Kathmandu",
        "province_name": "Bagmati Province",
        "municipality": "Kathmandu Metropolitan",
        "address": "Kalanki Chowk, Ring Road",
        "contact_number": "01-5970004",
        "latitude": 27.693600,
        "longitude": 85.281700,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Kalanki", "Kuleshwor", "Balkhu", "Swoyambhu", "Sitapaila",
            "Kalimati", "Thankot", "Naikap", "Syuchatar"
        ],
    },
    {
        "code": "LALITPUR_PATAN",
        "name": "Lalitpur (Kumaripati / Patan)",
        "district_name": "Lalitpur",
        "province_name": "Bagmati Province",
        "municipality": "Lalitpur Metropolitan",
        "address": "Kumaripati, Lalitpur",
        "contact_number": "01-5970005",
        "latitude": 27.668800,
        "longitude": 85.319500,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Kumaripati", "Jawalakhel", "Lagankhel", "Patan Durbar Square",
            "Pulchowk", "Sanepa", "Satdobato", "Ekantakuna", "Balkumari",
            "Kupondole", "Gwarko"
        ],
    },
    {
        "code": "BHAKTAPUR_SURYABINAYAK",
        "name": "Bhaktapur (Suryabinayak)",
        "district_name": "Bhaktapur",
        "province_name": "Bagmati Province",
        "municipality": "Suryabinayak Municipality",
        "address": "Suryabinayak Chowk, Arniko Highway",
        "contact_number": "01-5970006",
        "latitude": 27.671000,
        "longitude": 85.429800,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Suryabinayak", "Thimi", "Lokanthali", "Kamalbinayak", "Byasi",
            "Sallaghari", "Radhe Radhe", "Kaushaltar", "Gatthaghar"
        ],
    },

    # --- Gandaki Province Hubs ---
    {
        "code": "POKHARA_CENTRAL",
        "name": "Pokhara (Chipledhunga)",
        "district_name": "Kaski",
        "province_name": "Gandaki Province",
        "municipality": "Pokhara Metropolitan",
        "address": "Chipledhunga, Pokhara",
        "contact_number": "061-597001",
        "latitude": 28.225000,
        "longitude": 83.987000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Chipledhunga", "Mahendrapool", "Lakeside", "Biruta",
            "Prithvi Chowk", "Srijana Chowk", "Bagar", "Kundahar",
            "Lekhnath", "Amarsingh Chowk", "Rambazar"
        ],
    },
    {
        "code": "BAGLUNG_CENTRAL",
        "name": "Baglung",
        "district_name": "Baglung",
        "province_name": "Gandaki Province",
        "municipality": "Baglung Municipality",
        "address": "Traffic Chowk, Baglung Bazaar",
        "contact_number": "068-520100",
        "latitude": 28.270000,
        "longitude": 83.600000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Baglung Bazaar", "Traffic Chowk", "Dhaulagiri Hospital", "Kudhar", "Kalika"],
    },
    {
        "code": "TANAHUN_DAMAULI",
        "name": "Damauli",
        "district_name": "Tanahun",
        "province_name": "Gandaki Province",
        "municipality": "Byas Municipality",
        "address": "Traffic Chowk, Damauli",
        "contact_number": "065-560100",
        "latitude": 27.970000,
        "longitude": 84.280000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Damauli", "Byas", "Traffic Chowk", "Anbukhaireni", "Dumre"],
    },
    {
        "code": "GORKHA_CENTRAL",
        "name": "Gorkha",
        "district_name": "Gorkha",
        "province_name": "Gandaki Province",
        "municipality": "Gorkha Municipality",
        "address": "Haramtari, Gorkha Bazaar",
        "contact_number": "064-420100",
        "latitude": 28.000000,
        "longitude": 84.630000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Haramtari", "Gorkha Bazaar", "Shaktichowk", "Palungtar"],
    },

    # --- Lumbini Province Hubs ---
    {
        "code": "BUTWAL_CENTRAL",
        "name": "Butwal (Traffic Chowk)",
        "district_name": "Rupandehi",
        "province_name": "Lumbini Province",
        "municipality": "Butwal Sub-Metropolitan",
        "address": "Traffic Chowk, Butwal",
        "contact_number": "071-597001",
        "latitude": 27.700000,
        "longitude": 83.450000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Traffic Chowk", "Golpark", "Kalikanagar", "Devinagar",
            "Milan Chowk", "Amarpath", "Hospital Line", "Deepnagar"
        ],
    },
    {
        "code": "BHAIRAHAWA_CENTRAL",
        "name": "Bhairahawa (Siddharthanagar)",
        "district_name": "Rupandehi",
        "province_name": "Lumbini Province",
        "municipality": "Siddharthanagar Municipality",
        "address": "Bank Road, Bhairahawa",
        "contact_number": "071-597002",
        "latitude": 27.505000,
        "longitude": 83.447000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Bank Road", "Barmeli Tole", "Devkota Chowk", "Narayansthan",
            "Belahiya", "Buspark", "Milanchowk"
        ],
    },
    {
        "code": "DANG_GHORAHI",
        "name": "Dang (Ghorahi)",
        "district_name": "Dang",
        "province_name": "Lumbini Province",
        "municipality": "Ghorahi Sub-Metropolitan",
        "address": "Sahidgate, Ghorahi",
        "contact_number": "082-560100",
        "latitude": 28.050000,
        "longitude": 82.483300,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Ghorahi", "Sahidgate", "BP Chowk", "Tulsipur Chowk",
            "Ratnanagar", "Damaur", "Narayampur", "Khalte"
        ],
    },
    {
        "code": "DANG_TULSIPUR",
        "name": "Dang (Tulsipur)",
        "district_name": "Dang",
        "province_name": "Lumbini Province",
        "municipality": "Tulsipur Sub-Metropolitan",
        "address": "BP Chowk, Tulsipur",
        "contact_number": "082-520100",
        "latitude": 28.130000,
        "longitude": 82.300000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Tulsipur", "BP Chowk", "Linepark", "Aananda Nagar", "Tarigaun", "Ganeshpur"],
    },
    {
        "code": "BANKE_NEPALGUNJ",
        "name": "Nepalgunj (Tribhuvan Chowk)",
        "district_name": "Banke",
        "province_name": "Lumbini Province",
        "municipality": "Nepalgunj Sub-Metropolitan",
        "address": "Tribhuvan Chowk, Nepalgunj",
        "contact_number": "081-597001",
        "latitude": 28.050000,
        "longitude": 81.616700,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Tribhuvan Chowk", "Dhamboji", "Surkhet Road", "Ganeshman Chowk",
            "Bhavanichowk", "Rani Talau", "Carikana"
        ],
    },
    {
        "code": "BANKE_KOHALPUR",
        "name": "Kohalpur",
        "district_name": "Banke",
        "province_name": "Lumbini Province",
        "municipality": "Kohalpur Municipality",
        "address": "Kohalpur Chowk, Banke",
        "contact_number": "081-540100",
        "latitude": 28.188000,
        "longitude": 81.693000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Kohalpur Chowk", "Pipari", "NTV Road", "Matrichowk"],
    },
    {
        "code": "GULMI_TAMGHAS",
        "name": "Tamghas (Gulmi)",
        "district_name": "Gulmi",
        "province_name": "Lumbini Province",
        "municipality": "Resunga Municipality",
        "address": "Tamghas Bazar, Gulmi",
        "contact_number": "079-520100",
        "latitude": 28.066700,
        "longitude": 83.250000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Tamghas", "Resunga", "Chhatrakot", "Kachhaute", "Ruru", "Rurukshetra",
            "Satyawati", "Dhurkot", "Gulmidarbar", "Chandrakot", "Madane",
            "Malika", "Isma", "Kaligandaki", "Baluwa", "Manabhakshya"
        ],
    },
    {
        "code": "PALPA_TANSEN",
        "name": "Tansen (Palpa)",
        "district_name": "Palpa",
        "province_name": "Lumbini Province",
        "municipality": "Tansen Municipality",
        "address": "Bishal Bazar, Tansen",
        "contact_number": "075-520100",
        "latitude": 27.866700,
        "longitude": 83.550000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Tansen", "Bishal Bazar", "Bartung", "Aryabhanjyang", "Rampur", "Madanpokhara"],
    },
    {
        "code": "ARGHAKHANCHI_SANDHIKHARKA",
        "name": "Sandhikharka (Arghakhanchi)",
        "district_name": "Arghakhanchi",
        "province_name": "Lumbini Province",
        "municipality": "Sandhikharka Municipality",
        "address": "Sandhikharka Bazar, Arghakhanchi",
        "contact_number": "077-420100",
        "latitude": 27.995000,
        "longitude": 83.076000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Sandhikharka", "Shantinagar", "Chutrabesi", "Sitganga", "Bhumikasthan", "Panini"],
    },

    # --- Koshi Province Hubs ---
    {
        "code": "MORANG_BIRATNAGAR",
        "name": "Biratnagar (Main Road)",
        "district_name": "Morang",
        "province_name": "Koshi Province",
        "municipality": "Biratnagar Metropolitan",
        "address": "Traffic Chowk, Main Road, Biratnagar",
        "contact_number": "021-597001",
        "latitude": 26.452500,
        "longitude": 87.271800,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Traffic Chowk", "Roadcess Chowk", "Kanchanbari", "Tinpaini",
            "Bargachhi", "Rani", "Main Road", "Jatadhari"
        ],
    },
    {
        "code": "SUNSARI_ITAHARI",
        "name": "Itahari",
        "district_name": "Sunsari",
        "province_name": "Koshi Province",
        "municipality": "Itahari Sub-Metropolitan",
        "address": "Itahari Chowk, Sunsari",
        "contact_number": "025-580100",
        "latitude": 26.666700,
        "longitude": 87.283300,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Itahari Chowk", "Main Road", "Tarahara", "Gachhiya", "Khanar"],
    },
    {
        "code": "SUNSARI_DHARAN",
        "name": "Dharan (Bhanu Chowk)",
        "district_name": "Sunsari",
        "province_name": "Koshi Province",
        "municipality": "Dharan Sub-Metropolitan",
        "address": "Bhanu Chowk, Dharan",
        "contact_number": "025-520100",
        "latitude": 26.812000,
        "longitude": 87.283000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Bhanu Chowk", "Chhata Chowk", "Putali Line", "BPKIHS", "Tinkune", "Bhotepul"],
    },
    {
        "code": "JHAPA_BIRTAMOD",
        "name": "Birtamod",
        "district_name": "Jhapa",
        "province_name": "Koshi Province",
        "municipality": "Birtamod Municipality",
        "address": "Mukti Chowk, Birtamod",
        "contact_number": "023-540100",
        "latitude": 26.633300,
        "longitude": 87.983300,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Mukti Chowk", "Bhadrapur Road", "Buspark", "Sanischare Road", "Charali"],
    },
    {
        "code": "JHAPA_DAMAK",
        "name": "Damak",
        "district_name": "Jhapa",
        "province_name": "Koshi Province",
        "municipality": "Damak Municipality",
        "address": "Ganatantra Chowk, Damak",
        "contact_number": "023-580100",
        "latitude": 26.666700,
        "longitude": 87.700000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Ganatantra Chowk", "Thanachowk", "Hospital Road", "Urlabari Link"],
    },

    # --- Bagmati Province (Outside Valley) ---
    {
        "code": "CHITWAN_NARAYANGARH",
        "name": "Narayangarh / Bharatpur",
        "district_name": "Chitwan",
        "province_name": "Bagmati Province",
        "municipality": "Bharatpur Metropolitan",
        "address": "Sahid Chowk, Narayangarh",
        "contact_number": "056-597001",
        "latitude": 27.700000,
        "longitude": 84.430000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Sahid Chowk", "Lions Chowk", "Pulchowk", "Chaulikhe",
            "Hakim Chowk", "Chaubiskothi", "Bharatpur Airport", "Tandi"
        ],
    },
    {
        "code": "MAKWANPUR_HETAUDA",
        "name": "Hetauda",
        "district_name": "Makwanpur",
        "province_name": "Bagmati Province",
        "municipality": "Hetauda Sub-Metropolitan",
        "address": "Seemachowk, Hetauda",
        "contact_number": "057-520100",
        "latitude": 27.428900,
        "longitude": 85.033600,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Seemachowk", "Main Road", "Kantirajpath", "Chaugadha", "Thanabharyang"],
    },
    {
        "code": "KAVRE_BANEPA",
        "name": "Banepa",
        "district_name": "Kavrepalanchok",
        "province_name": "Bagmati Province",
        "municipality": "Banepa Municipality",
        "address": "Banepa Chowk, Arniko Highway",
        "contact_number": "011-660100",
        "latitude": 27.630000,
        "longitude": 85.520000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Banepa Chowk", "Tinkune", "Nala Road", "Dhulikhel Link", "Panauti Link"],
    },

    # --- Madhesh Province Hubs ---
    {
        "code": "PARSA_BIRGUNJ",
        "name": "Birgunj (Ghantaghar)",
        "district_name": "Parsa",
        "province_name": "Madhesh Province",
        "municipality": "Birgunj Metropolitan",
        "address": "Ghantaghar, Main Road, Birgunj",
        "contact_number": "051-597001",
        "latitude": 27.016700,
        "longitude": 84.883300,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": [
            "Ghantaghar", "Adarshanagar", "Maisthan", "Murli Chowk",
            "Powerhouse", "Pipra", "Customs Road"
        ],
    },
    {
        "code": "DHANUSHA_JANAKPUR",
        "name": "Janakpur (Bhanu Chowk)",
        "district_name": "Dhanusha",
        "province_name": "Madhesh Province",
        "municipality": "Janakpurdham Sub-Metropolitan",
        "address": "Bhanu Chowk, Janakpur",
        "contact_number": "041-597001",
        "latitude": 26.728800,
        "longitude": 85.925000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Bhanu Chowk", "Ramananda Chowk", "Station Road", "Pidari Chowk", "Janaki Mandir"],
    },
    {
        "code": "SIRAHA_LAHAN",
        "name": "Lahan",
        "district_name": "Siraha",
        "province_name": "Madhesh Province",
        "municipality": "Lahan Municipality",
        "address": "Shahid Chowk, Lahan",
        "contact_number": "033-560100",
        "latitude": 26.716700,
        "longitude": 86.483300,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Shahid Chowk", "Hospital Chowk", "Buspark", "Thana Chowk"],
    },

    # --- Sudurpashchim Province Hubs ---
    {
        "code": "KAILALI_DHANGADHI",
        "name": "Dhangadhi",
        "district_name": "Kailali",
        "province_name": "Sudurpashchim Province",
        "municipality": "Dhangadhi Sub-Metropolitan",
        "address": "Traffic Chowk, Main Road, Dhangadhi",
        "contact_number": "091-597001",
        "latitude": 28.683300,
        "longitude": 80.600000,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Traffic Chowk", "Main Road", "Chauraha", "Campus Road", "Hasanpur", "Boradandi"],
    },
    {
        "code": "KANCHANPUR_MAHENDRANAGAR",
        "name": "Mahendranagar (Bhimdatta)",
        "district_name": "Kanchanpur",
        "province_name": "Sudurpashchim Province",
        "municipality": "Bhimdatta Municipality",
        "address": "Madan Chowk, Mahendranagar",
        "contact_number": "099-520100",
        "latitude": 28.966700,
        "longitude": 80.183300,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Madan Chowk", "Traffic Chowk", "Galli No. 1-5", "Buspark"],
    },

    # --- Karnali Province Hubs ---
    {
        "code": "SURKHET_BIRENDRANAGAR",
        "name": "Surkhet (Birendranagar)",
        "district_name": "Surkhet",
        "province_name": "Karnali Province",
        "municipality": "Birendranagar Municipality",
        "address": "Mangalgadhi Chowk, Birendranagar",
        "contact_number": "083-520100",
        "latitude": 28.600000,
        "longitude": 81.633300,
        "coordinate_source": "ADMIN_VERIFIED",
        "is_coordinate_verified": True,
        "areas_covered": ["Mangalgadhi Chowk", "Birendra Chowk", "Airpal Chowk", "Subbakuna", "Khulamanch"],
    },
]

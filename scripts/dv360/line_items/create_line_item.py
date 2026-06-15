"""
scripts/dv360/line_items/create_line_item.py
Crea un Line Item en DV360 con targeting completo.

Soporta tres formatos:
  DISPLAY  — Display estandar (LINE_ITEM_TYPE_DISPLAY_DEFAULT)
  VIDEO    — Video instream/outstream (LINE_ITEM_TYPE_VIDEO_DEFAULT)
  YOUTUBE  — YouTube & Partners (LINE_ITEM_TYPE_YOUTUBE_AND_PARTNERS_VIDEO_SEQUENCE)
  YOUTUBE_BUMPER       — Bumper 6s (LINE_ITEM_TYPE_YOUTUBE_AND_PARTNERS_BUMPER)
  YOUTUBE_NON_SKIP     — Non-skippable 15s (LINE_ITEM_TYPE_YOUTUBE_AND_PARTNERS_NON_SKIPPABLE)
  YOUTUBE_VIEW         — TrueView in-stream (LINE_ITEM_TYPE_YOUTUBE_AND_PARTNERS_VIEW)

Jerarquia: Campaign -> Insertion Order -> Line Item -> Creatives

SA: llyc-ops-writer-sa (DEC_084). NUNCA llyc-agents-sa.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from googleapiclient.errors import HttpError

from scripts.dv360._common.auth import build_writer_service, get_advertiser_id
from scripts.dv360._common.audit import log_action, confirm_action

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

_EUR_TO_MICROS = 1_000_000

# ── Tipos de Line Item ────────────────────────────────────────────────────────

LINE_ITEM_TYPES = {
    "DISPLAY":            "LINE_ITEM_TYPE_DISPLAY_DEFAULT",
    "VIDEO":              "LINE_ITEM_TYPE_VIDEO_DEFAULT",
    "YOUTUBE":            "LINE_ITEM_TYPE_YOUTUBE_AND_PARTNERS_VIDEO_SEQUENCE",
    "YOUTUBE_BUMPER":     "LINE_ITEM_TYPE_YOUTUBE_AND_PARTNERS_BUMPER",
    "YOUTUBE_NON_SKIP":   "LINE_ITEM_TYPE_YOUTUBE_AND_PARTNERS_NON_SKIPPABLE",
    "YOUTUBE_VIEW":       "LINE_ITEM_TYPE_YOUTUBE_AND_PARTNERS_VIEW",
}

# ── Bid strategies por tipo de LI ─────────────────────────────────────────────

BID_STRATEGIES = {
    "FIXED":       "fixed",
    "MAXIMIZE":    "maximizeSpend",
    "TARGET_CPA":  "performanceGoalAutoBid",
    "TARGET_CPV":  "performanceGoalAutoBid",  # Cost Per View para YouTube
    "TARGET_CPM":  "performanceGoalAutoBid",  # CPM objetivo
}

# ── Targeting maps ────────────────────────────────────────────────────────────

DEVICE_TYPES = {
    "DESKTOP":   "DEVICE_TYPE_DESKTOP",
    "MOBILE":    "DEVICE_TYPE_SMART_PHONE",
    "TABLET":    "DEVICE_TYPE_TABLET",
    "CONNECTED": "DEVICE_TYPE_CONNECTED_TV",
}

ENVIRONMENTS = {
    "DESKTOP_WEB": "ENVIRONMENT_TYPE_BROWSER",
    "MOBILE_WEB":  "ENVIRONMENT_TYPE_BROWSER",
    "APP":         "ENVIRONMENT_TYPE_APP",
    "ALL":         "ENVIRONMENT_TYPE_ALL",
}

CONTENT_LABELS = {
    "G":  "CONTENT_RATING_TIER_G",
    "PG": "CONTENT_RATING_TIER_PG",
    "T":  "CONTENT_RATING_TIER_T",
    "MA": "CONTENT_RATING_TIER_MA",
}

GENDER_TYPES = {
    "MALE":    "GENDER_MALE",
    "FEMALE":  "GENDER_FEMALE",
    "UNKNOWN": "GENDER_UNKNOWN",
}

AGE_RANGES = {
    "18-24": "AGE_RANGE_18_24",
    "25-34": "AGE_RANGE_25_34",
    "35-44": "AGE_RANGE_35_44",
    "45-54": "AGE_RANGE_45_54",
    "55-64": "AGE_RANGE_55_64",
    "65+":   "AGE_RANGE_65_PLUS",
}

VIEWABILITY_TARGETS = {
    "50": "VIEWABILITY_50_PERCENT_OR_MORE",
    "60": "VIEWABILITY_60_PERCENT_OR_MORE",
    "70": "VIEWABILITY_70_PERCENT_OR_MORE",
    "80": "VIEWABILITY_80_PERCENT_OR_MORE",
}

PARENTAL_STATUS = {
    "PARENT":     "PARENTAL_STATUS_PARENT",
    "NOT_PARENT": "PARENTAL_STATUS_NOT_A_PARENT",
    "UNKNOWN":    "PARENTAL_STATUS_UNKNOWN",
}

FREQUENCY_CAP_UNITS = {
    "MINUTES": "TIME_UNIT_MINUTES",
    "HOURS":   "TIME_UNIT_HOURS",
    "DAYS":    "TIME_UNIT_DAYS",
    "WEEKS":   "TIME_UNIT_WEEKS",
    "MONTHS":  "TIME_UNIT_MONTHS",
}

POSITION_TYPES = {
    "ATF":     "POSITION_ABOVE_THE_FOLD",
    "BTF":     "POSITION_BELOW_THE_FOLD",
    "UNKNOWN": "POSITION_UNKNOWN",
}

BROWSERS = {
    "CHROME":  "BROWSER_CHROME",
    "SAFARI":  "BROWSER_SAFARI",
    "FIREFOX": "BROWSER_FIREFOX",
    "EDGE":    "BROWSER_EDGE",
    "OPERA":   "BROWSER_OPERA",
}

OS_TYPES = {
    "ANDROID":  "OPERATING_SYSTEM_ANDROID",
    "IOS":      "OPERATING_SYSTEM_IOS",
    "WINDOWS":  "OPERATING_SYSTEM_WINDOWS",
    "MACOS":    "OPERATING_SYSTEM_MAC_OS_X",
    "CHROMEOS": "OPERATING_SYSTEM_CHROME_OS",
}

CONNECTION_SPEEDS = {
    "WIFI": "CONNECTION_SPEED_WIFI",
    "4G":   "CONNECTION_SPEED_4G",
    "5G":   "CONNECTION_SPEED_5G",
    "3G":   "CONNECTION_SPEED_3G",
    "ALL":  "CONNECTION_SPEED_ALL",
}

SENSITIVE_CATEGORIES = {
    "POLITICS":  "SENSITIVE_CATEGORY_POLITICS",
    "RELIGION":  "SENSITIVE_CATEGORY_RELIGION",
    "GAMBLING":  "SENSITIVE_CATEGORY_GAMBLING",
    "TRAGEDY":   "SENSITIVE_CATEGORY_TRAGEDY",
    "WEAPONS":   "SENSITIVE_CATEGORY_WEAPONS",
    "ADULT":     "SENSITIVE_CATEGORY_ADULT",
    "DRUGS":     "SENSITIVE_CATEGORY_ILLEGAL_DRUGS",
    "VIOLENCE":  "SENSITIVE_CATEGORY_VIOLENCE",
    "HATE":      "SENSITIVE_CATEGORY_HATE_SPEECH",
    "TOBACCO":   "SENSITIVE_CATEGORY_TOBACCO",
}

BRAND_SAFETY_CATEGORIES = {
    "ADULT":    "BRAND_SAFETY_ADULT",
    "WEAPONS":  "BRAND_SAFETY_ARMS",
    "VIOLENCE": "BRAND_SAFETY_CRIME_VIOLENCE",
    "DRUGS":    "BRAND_SAFETY_DRUGS",
    "HATE":     "BRAND_SAFETY_HATE_SPEECH",
    "TRAGEDY":  "BRAND_SAFETY_TRAGEDY",
    "TOBACCO":  "BRAND_SAFETY_TOBACCO",
}

# YouTube: tipos de contenido donde mostrar el anuncio
YOUTUBE_CONTENT_CATEGORIES = {
    "BEAUTY":       "YOUTUBE_AND_PARTNERS_CONTENT_CATEGORY_BEAUTY",
    "FOOD":         "YOUTUBE_AND_PARTNERS_CONTENT_CATEGORY_FOOD",
    "GAMING":       "YOUTUBE_AND_PARTNERS_CONTENT_CATEGORY_GAMING",
    "NEWS":         "YOUTUBE_AND_PARTNERS_CONTENT_CATEGORY_NEWS",
    "SPORTS":       "YOUTUBE_AND_PARTNERS_CONTENT_CATEGORY_SPORTS",
    "TECHNOLOGY":   "YOUTUBE_AND_PARTNERS_CONTENT_CATEGORY_TECHNOLOGY",
    "TRAVEL":       "YOUTUBE_AND_PARTNERS_CONTENT_CATEGORY_TRAVEL",
}


def _eur_to_micros(eur: float) -> int:
    return int(eur * _EUR_TO_MICROS)


def _parse_date(date_str: str) -> dict:
    parts = date_str.split("-")
    return {"year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])}


def _is_youtube(li_type: str) -> bool:
    return li_type.upper().startswith("YOUTUBE")


def build_targeting_settings(
    content_labels: list | None,
    brand_safety_categories: list | None,
    sensitive_categories: list | None,
    keyword_includes: list | None,
    keyword_excludes: list | None,
    iab_categories: list | None,
    environment: str | None,
    viewability_target: str | None,
    positions: list | None,
    audience_list_ids: list | None,
    audience_inmarket: list | None,
    audience_affinity: list | None,
    audience_expansion: bool,
    genders: list | None,
    age_ranges: list | None,
    parental_status: list | None,
    geo_regions: list | None,
    geo_cities: list | None,
    geo_zip_codes: list | None,
    geo_exclude: list | None,
    language_codes: list | None,
    daypart_matrix: dict | None,
    device_types: list | None,
    operating_systems: list | None,
    browsers: list | None,
    connection_speeds: list | None,
    youtube_content_categories: list | None,
    youtube_channel_ids: list | None,
    youtube_video_ids: list | None,
    li_type: str = "DISPLAY",
) -> list:
    targeting = []

    # ── Brand Safety ──────────────────────────────────────────────────────────
    if content_labels:
        for label in content_labels:
            mapped = CONTENT_LABELS.get(label.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_DIGITAL_CONTENT_LABEL_EXCLUSION",
                    "digitalContentLabelExclusionDetails": {
                        "excludedContentRatingTier": mapped,
                    },
                })

    if brand_safety_categories:
        for cat in brand_safety_categories:
            mapped = BRAND_SAFETY_CATEGORIES.get(cat.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_SENSITIVE_CATEGORY_EXCLUSION",
                    "sensitiveCategoryExclusionDetails": {
                        "excludedSensitiveCategory": mapped,
                    },
                })

    if sensitive_categories:
        for cat in sensitive_categories:
            mapped = SENSITIVE_CATEGORIES.get(cat.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_SENSITIVE_CATEGORY_EXCLUSION",
                    "sensitiveCategoryExclusionDetails": {
                        "excludedSensitiveCategory": mapped,
                    },
                })

    # ── Content ───────────────────────────────────────────────────────────────
    if keyword_includes:
        for kw in keyword_includes:
            targeting.append({
                "targetingType": "TARGETING_TYPE_KEYWORD",
                "keywordDetails": {"keyword": kw, "negative": False},
            })

    if keyword_excludes:
        for kw in keyword_excludes:
            targeting.append({
                "targetingType": "TARGETING_TYPE_KEYWORD",
                "keywordDetails": {"keyword": kw, "negative": True},
            })

    if iab_categories:
        for cat in iab_categories:
            targeting.append({
                "targetingType": "TARGETING_TYPE_CATEGORY",
                "categoryDetails": {"displayName": cat, "negative": False},
            })

    if environment and not _is_youtube(li_type):
        mapped = ENVIRONMENTS.get(environment.upper())
        if mapped:
            targeting.append({
                "targetingType": "TARGETING_TYPE_ENVIRONMENT",
                "environmentDetails": {"environment": mapped},
            })

    if viewability_target and not _is_youtube(li_type):
        mapped = VIEWABILITY_TARGETS.get(str(viewability_target))
        if mapped:
            targeting.append({
                "targetingType": "TARGETING_TYPE_VIEWABILITY",
                "viewabilityDetails": {"viewability": mapped},
            })

    if positions and not _is_youtube(li_type):
        for pos in positions:
            mapped = POSITION_TYPES.get(pos.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_ON_SCREEN_POSITION",
                    "onScreenPositionDetails": {"onScreenPosition": mapped},
                })

    # ── YouTube-specific content ──────────────────────────────────────────────
    if _is_youtube(li_type):
        if youtube_content_categories:
            for cat in youtube_content_categories:
                mapped = YOUTUBE_CONTENT_CATEGORIES.get(cat.upper())
                if mapped:
                    targeting.append({
                        "targetingType": "TARGETING_TYPE_YOUTUBE_AND_PARTNERS_CONTENT_CATEGORY",
                        "youtubeAndPartnersContentCategoryDetails": {
                            "contentCategory": mapped,
                        },
                    })

        if youtube_channel_ids:
            for channel_id in youtube_channel_ids:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_YOUTUBE_CHANNEL",
                    "youtubeChannelDetails": {
                        "channelId": channel_id,
                        "negative": False,
                    },
                })

        if youtube_video_ids:
            for video_id in youtube_video_ids:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_YOUTUBE_VIDEO",
                    "youtubeVideoDetails": {
                        "videoId": video_id,
                        "negative": False,
                    },
                })

    # ── Audience ──────────────────────────────────────────────────────────────
    if audience_list_ids:
        targeting.append({
            "targetingType": "TARGETING_TYPE_AUDIENCE_GROUP",
            "audienceGroupDetails": {
                "includedFirstAndThirdPartyAudienceGroups": [
                    {
                        "firstAndThirdPartyAudiences": [
                            {
                                "firstAndThirdPartyAudienceId": aid,
                                "recency": "AUDIENCE_RECENCY_NO_LIMIT",
                            }
                            for aid in audience_list_ids
                        ]
                    }
                ]
            },
        })

    if audience_inmarket:
        for audience in audience_inmarket:
            targeting.append({
                "targetingType": "TARGETING_TYPE_AUDIENCE_GROUP",
                "audienceGroupDetails": {
                    "includedGoogleAudienceGroup": {
                        "settings": [{"targetingOptionId": audience, "negative": False}]
                    }
                },
            })

    if audience_affinity:
        for audience in audience_affinity:
            targeting.append({
                "targetingType": "TARGETING_TYPE_AUDIENCE_GROUP",
                "audienceGroupDetails": {
                    "includedGoogleAudienceGroup": {
                        "settings": [{"targetingOptionId": audience, "negative": False}]
                    }
                },
            })

    if genders:
        for gender in genders:
            mapped = GENDER_TYPES.get(gender.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_GENDER",
                    "genderDetails": {"gender": mapped},
                })

    if age_ranges:
        for age in age_ranges:
            mapped = AGE_RANGES.get(age)
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_AGE_RANGE",
                    "ageRangeDetails": {"ageRange": mapped},
                })

    if parental_status:
        for status in parental_status:
            mapped = PARENTAL_STATUS.get(status.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_PARENTAL_STATUS",
                    "parentalStatusDetails": {"parentalStatus": mapped},
                })

    # ── Geography ─────────────────────────────────────────────────────────────
    if geo_regions:
        for region in geo_regions:
            targeting.append({
                "targetingType": "TARGETING_TYPE_GEO_REGION",
                "geoRegionDetails": {
                    "displayName": region,
                    "geoRegionType": "GEO_REGION_TYPE_REGION",
                    "negative": False,
                },
            })

    if geo_cities:
        for city in geo_cities:
            targeting.append({
                "targetingType": "TARGETING_TYPE_GEO_REGION",
                "geoRegionDetails": {
                    "displayName": city,
                    "geoRegionType": "GEO_REGION_TYPE_CITY",
                    "negative": False,
                },
            })

    if geo_zip_codes:
        for zip_code in geo_zip_codes:
            targeting.append({
                "targetingType": "TARGETING_TYPE_GEO_REGION",
                "geoRegionDetails": {
                    "displayName": zip_code,
                    "geoRegionType": "GEO_REGION_TYPE_POSTAL_CODE",
                    "negative": False,
                },
            })

    if geo_exclude:
        for region in geo_exclude:
            targeting.append({
                "targetingType": "TARGETING_TYPE_GEO_REGION",
                "geoRegionDetails": {"displayName": region, "negative": True},
            })

    if language_codes:
        for lang in language_codes:
            targeting.append({
                "targetingType": "TARGETING_TYPE_LANGUAGE",
                "languageDetails": {"displayName": lang, "negative": False},
            })

    # ── Day & Time ────────────────────────────────────────────────────────────
    if daypart_matrix:
        day_map = {
            "MONDAY":    "DAYOFWEEK_MONDAY",
            "TUESDAY":   "DAYOFWEEK_TUESDAY",
            "WEDNESDAY": "DAYOFWEEK_WEDNESDAY",
            "THURSDAY":  "DAYOFWEEK_THURSDAY",
            "FRIDAY":    "DAYOFWEEK_FRIDAY",
            "SATURDAY":  "DAYOFWEEK_SATURDAY",
            "SUNDAY":    "DAYOFWEEK_SUNDAY",
        }
        dayparts = []
        for day, hours in daypart_matrix.items():
            day_mapped = day_map.get(day.upper())
            if day_mapped and hours:
                for hour in hours:
                    dayparts.append({
                        "dayOfWeek": day_mapped,
                        "startHour": hour,
                        "endHour": hour + 1,
                    })
        if dayparts:
            targeting.append({
                "targetingType": "TARGETING_TYPE_DAYPART",
                "dayPartDetails": {
                    "dayParts": dayparts,
                    "timeZoneResolution": "TIME_ZONE_RESOLUTION_END_USER",
                },
            })

    # ── Technology ────────────────────────────────────────────────────────────
    if device_types:
        for device in device_types:
            mapped = DEVICE_TYPES.get(device.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_DEVICE_TYPE",
                    "deviceTypeDetails": {"deviceType": mapped},
                })

    if operating_systems:
        for os_name in operating_systems:
            targeting.append({
                "targetingType": "TARGETING_TYPE_OPERATING_SYSTEM",
                "operatingSystemDetails": {"displayName": os_name, "negative": False},
            })

    if browsers and not _is_youtube(li_type):
        for browser in browsers:
            targeting.append({
                "targetingType": "TARGETING_TYPE_BROWSER",
                "browserDetails": {"displayName": browser, "negative": False},
            })

    if connection_speeds:
        for speed in connection_speeds:
            mapped = CONNECTION_SPEEDS.get(speed.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_CONNECTION_SPEED",
                    "connectionSpeedDetails": {"connectionSpeed": mapped},
                })

    return targeting


def build_bid_strategy(
    li_type: str,
    bid_strategy: str,
    bid_eur: float | None,
    bid_max_eur: float | None,
    target_cpa_eur: float | None,
    target_cpv_eur: float | None,
) -> dict:
    """
    Construye la bid strategy segun el tipo de LI.

    Display/Video: FIXED (CPM), MAXIMIZE, TARGET_CPA
    YouTube: TARGET_CPV (Cost Per View), TARGET_CPM, MAXIMIZE
    """
    if _is_youtube(li_type):
        if bid_strategy.upper() == "TARGET_CPV" and target_cpv_eur:
            return {
                "performanceGoalAutoBid": {
                    "performanceGoalType": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPV",
                    "performanceGoalAmountMicros": str(_eur_to_micros(target_cpv_eur)),
                }
            }
        elif bid_strategy.upper() == "TARGET_CPM" and bid_eur:
            return {
                "performanceGoalAutoBid": {
                    "performanceGoalType": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPM",
                    "performanceGoalAmountMicros": str(_eur_to_micros(bid_eur)),
                }
            }
        else:
            # YouTube default: maximize views
            strategy = {
                "performanceGoalType": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPV"
            }
            if bid_max_eur:
                strategy["maxAverageCpmBidAmountMicros"] = str(_eur_to_micros(bid_max_eur))
            return {"maximizeSpendAutoBid": strategy}

    else:
        # Display / Video
        if bid_strategy.upper() == "FIXED" and bid_eur:
            return {"fixedBid": {"bidAmountMicros": str(_eur_to_micros(bid_eur))}}
        elif bid_strategy.upper() == "TARGET_CPA" and target_cpa_eur:
            return {
                "performanceGoalAutoBid": {
                    "performanceGoalType": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPA",
                    "performanceGoalAmountMicros": str(_eur_to_micros(target_cpa_eur)),
                }
            }
        else:
            strategy = {
                "performanceGoalType": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPA"
            }
            if bid_max_eur:
                strategy["maxAverageCpmBidAmountMicros"] = str(_eur_to_micros(bid_max_eur))
            return {"maximizeSpendAutoBid": strategy}


def build_li_body(
    advertiser_id: str,
    campaign_id: str,
    io_id: str,
    name: str,
    li_type: str,
    budget_eur: float,
    start_date: str,
    end_date: str,
    bid_strategy_body: dict,
    frequency_cap: int | None,
    frequency_cap_unit: str | None,
    creative_ids: list,
    audience_expansion: bool,
    youtube_target_frequency: int | None,
) -> dict:
    """Construye el body completo del Line Item."""

    li_type_mapped = LINE_ITEM_TYPES.get(li_type.upper())
    if not li_type_mapped:
        raise ValueError(f"line_item_type '{li_type}' no valido. Opciones: {list(LINE_ITEM_TYPES)}")

    body = {
        "advertiserId": advertiser_id,
        "campaignId": campaign_id,
        "insertionOrderId": io_id,
        "displayName": name,
        "lineItemType": li_type_mapped,
        "entityStatus": "ENTITY_STATUS_DRAFT",
        "flight": {
            "flightDateType": "LINE_ITEM_FLIGHT_DATE_TYPE_CUSTOM",
            "dateRange": {
                "startDate": _parse_date(start_date),
                "endDate": _parse_date(end_date),
            },
        },
        "budget": {
            "budgetAllocationType": "LINE_ITEM_BUDGET_ALLOCATION_TYPE_FIXED",
            "budgetUnit": "BUDGET_UNIT_CURRENCY",
            "maxAmount": str(_eur_to_micros(budget_eur)),
        },
        "pacing": {
            "pacingPeriod": "PACING_PERIOD_DAILY",
            "pacingType": "PACING_TYPE_EVEN",
        },
        "bidStrategy": bid_strategy_body,
        "targetingExpansion": {
            "targetingExpansionLevel": "TARGETING_EXPANSION_LEVEL_LEAST_EXPANSION"
            if audience_expansion
            else "TARGETING_EXPANSION_LEVEL_NO_EXPANSION",
            "excludeFirstPartyAudience": not audience_expansion,
        },
    }

    # Frequency cap
    if frequency_cap and frequency_cap_unit:
        unit_mapped = FREQUENCY_CAP_UNITS.get(frequency_cap_unit.upper())
        if unit_mapped:
            body["frequencyCap"] = {
                "maxImpressions": frequency_cap,
                "timeUnit": unit_mapped,
                "timeUnitCount": 1,
            }
    else:
        body["frequencyCap"] = {"unlimited": True}

    # YouTube: target frequency (impactos objetivo por usuario)
    if _is_youtube(li_type) and youtube_target_frequency:
        body["youtubeAndPartnersSettings"] = {
            "targetFrequency": {
                "targetCount": youtube_target_frequency,
                "timeUnit": "TIME_UNIT_WEEKS",
            }
        }

    # Creatividades
    if creative_ids:
        body["creativeIds"] = creative_ids

    return body


def create_line_item(
    client_id: str,
    campaign_id: str,
    io_id: str,
    name: str,
    li_type: str = "DISPLAY",
    budget_eur: float = 0,
    start_date: str = None,
    end_date: str = None,
    bid_strategy: str = "FIXED",
    bid_eur: float | None = None,
    bid_max_eur: float | None = None,
    target_cpa_eur: float | None = None,
    target_cpv_eur: float | None = None,
    frequency_cap: int | None = None,
    frequency_cap_unit: str | None = None,
    creative_ids: list = None,
    audience_expansion: bool = False,
    youtube_target_frequency: int | None = None,
    content_labels_exclude: list | None = None,
    brand_safety_exclude: list | None = None,
    sensitive_categories_exclude: list | None = None,
    keyword_includes: list | None = None,
    keyword_excludes: list | None = None,
    iab_categories: list | None = None,
    environment: str | None = None,
    viewability_target: str | None = None,
    positions: list | None = None,
    audience_list_ids: list | None = None,
    audience_inmarket: list | None = None,
    audience_affinity: list | None = None,
    genders: list | None = None,
    age_ranges: list | None = None,
    parental_status: list | None = None,
    geo_regions: list | None = None,
    geo_cities: list | None = None,
    geo_zip_codes: list | None = None,
    geo_exclude: list | None = None,
    language_codes: list | None = None,
    daypart_matrix: dict | None = None,
    device_types: list | None = None,
    operating_systems: list | None = None,
    browsers: list | None = None,
    connection_speeds: list | None = None,
    youtube_content_categories: list | None = None,
    youtube_channel_ids: list | None = None,
    youtube_video_ids: list | None = None,
    dry_run: bool = False,
) -> dict:
    """Crea un Line Item en DV360 con soporte para Display, Video y YouTube."""

    if creative_ids is None:
        creative_ids = []

    advertiser_id = get_advertiser_id(client_id)

    bid_strategy_body = build_bid_strategy(
        li_type=li_type,
        bid_strategy=bid_strategy,
        bid_eur=bid_eur,
        bid_max_eur=bid_max_eur,
        target_cpa_eur=target_cpa_eur,
        target_cpv_eur=target_cpv_eur,
    )

    targeting = build_targeting_settings(
        content_labels=content_labels_exclude,
        brand_safety_categories=brand_safety_exclude,
        sensitive_categories=sensitive_categories_exclude,
        keyword_includes=keyword_includes,
        keyword_excludes=keyword_excludes,
        iab_categories=iab_categories,
        environment=environment,
        viewability_target=viewability_target,
        positions=positions,
        audience_list_ids=audience_list_ids,
        audience_inmarket=audience_inmarket,
        audience_affinity=audience_affinity,
        audience_expansion=audience_expansion,
        genders=genders,
        age_ranges=age_ranges,
        parental_status=parental_status,
        geo_regions=geo_regions,
        geo_cities=geo_cities,
        geo_zip_codes=geo_zip_codes,
        geo_exclude=geo_exclude,
        language_codes=language_codes,
        daypart_matrix=daypart_matrix,
        device_types=device_types,
        operating_systems=operating_systems,
        browsers=browsers,
        connection_speeds=connection_speeds,
        youtube_content_categories=youtube_content_categories,
        youtube_channel_ids=youtube_channel_ids,
        youtube_video_ids=youtube_video_ids,
        li_type=li_type,
    )

    body = build_li_body(
        advertiser_id=advertiser_id,
        campaign_id=campaign_id,
        io_id=io_id,
        name=name,
        li_type=li_type,
        budget_eur=budget_eur,
        start_date=start_date,
        end_date=end_date,
        bid_strategy_body=bid_strategy_body,
        frequency_cap=frequency_cap,
        frequency_cap_unit=frequency_cap_unit,
        creative_ids=creative_ids,
        audience_expansion=audience_expansion,
        youtube_target_frequency=youtube_target_frequency,
    )

    format_label = li_type.upper()
    action_msg = (
        f"Crear Line Item [{format_label}] '{name}' "
        f"(IO {io_id}, budget {budget_eur} EUR, "
        f"bid {bid_strategy}, {len(targeting)} targeting options) "
        f"en advertiser {advertiser_id} cliente {client_id}. "
        "Se crea en DRAFT."
    )

    if not confirm_action(action_msg, dry_run=dry_run):
        return {"status": "cancelled", "data": {}}

    if dry_run:
        return {
            "status": "dry_run",
            "data": {
                "advertiser_id": advertiser_id,
                "li_type": li_type,
                "body": body,
                "targeting_options_count": len(targeting),
                "targeting_options": targeting,
                "note": f"LI [{format_label}] se crearia en DRAFT. Revisar antes de ejecutar.",
            },
        }

    try:
        svc = build_writer_service(client_id=client_id)

        li_result = (
            svc.advertisers()
            .lineItems()
            .create(advertiserId=advertiser_id, body=body)
            .execute()
        )
        li_id = li_result.get("lineItemId")

        targeting_errors = []
        for t_option in targeting:
            try:
                svc.advertisers().lineItems().assignedTargetingOptions().create(
                    advertiserId=advertiser_id,
                    lineItemId=li_id,
                    targetingType=t_option["targetingType"],
                    body=t_option,
                ).execute()
            except HttpError as te:
                targeting_errors.append({
                    "targeting_type": t_option["targetingType"],
                    "error": f"{te.resp.status}: {te.reason}",
                })

        outcome = {
            "status": "ok" if not targeting_errors else "partial",
            "data": {
                "line_item_id": li_id,
                "li_type": li_type,
                "campaign_id": li_result.get("campaignId"),
                "io_id": li_result.get("insertionOrderId"),
                "name": li_result.get("displayName"),
                "entity_status": li_result.get("entityStatus"),
                "targeting_options_applied": len(targeting) - len(targeting_errors),
                "targeting_errors": targeting_errors,
            },
        }

    except HttpError as e:
        outcome = {
            "status": "error",
            "error": f"DV360 API {e.resp.status}: {e.reason}",
            "data": {},
        }
    except Exception as e:
        outcome = {
            "status": "error",
            "error": str(e),
            "data": {},
        }

    log_action(
        script="create_line_item",
        action="create_line_item",
        client_id=client_id,
        args={
            "campaign_id": campaign_id,
            "io_id": io_id,
            "name": name,
            "li_type": li_type,
            "budget_eur": budget_eur,
            "bid_strategy": bid_strategy,
            "targeting_options": len(targeting),
            "advertiser_id": advertiser_id,
        },
        result=outcome,
        dry_run=dry_run,
    )

    if outcome["status"] in ("ok", "partial"):
        li_id = outcome["data"]["line_item_id"]
        print(f"\n✅ Line Item [{format_label}] creado en DRAFT. line_item_id: {li_id}")
        if targeting_errors:
            print(f"⚠️  {len(targeting_errors)} opciones de targeting fallaron.")
        print(f"\nActivar cuando este listo:")
        print(f"  python scripts/dv360/line_items/activate_line_item.py --client {client_id} --line-item-id {li_id}")

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea un Line Item en DV360 (Display, Video, YouTube).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Tipos de Line Item (--li-type):
  DISPLAY           Display estandar
  VIDEO             Video instream/outstream
  YOUTUBE           YouTube TrueView in-stream
  YOUTUBE_BUMPER    YouTube Bumper 6s
  YOUTUBE_NON_SKIP  YouTube Non-skippable 15s
  YOUTUBE_VIEW      YouTube TrueView for reach

Bid strategies:
  FIXED        CPM fijo (Display/Video, requiere --bid-eur)
  MAXIMIZE     Maximizar conversiones (Display/Video, opcional --bid-max-eur)
  TARGET_CPA   CPA objetivo (Display/Video, requiere --target-cpa-eur)
  TARGET_CPV   CPV objetivo (YouTube, requiere --target-cpv-eur)
  TARGET_CPM   CPM objetivo (YouTube, requiere --bid-eur)

Ejemplos:
  # Display con puja fija y targeting completo
  python scripts/dv360/line_items/create_line_item.py \\
    --client vidal-vidal --campaign-id 123 --io-id 456 \\
    --name "LI_Display_InMarket_Desktop" --li-type DISPLAY \\
    --budget-eur 1000 --start-date 2026-07-01 --end-date 2026-09-30 \\
    --bid-strategy FIXED --bid-eur 2.50 \\
    --geo-regions "Spain" --device-types DESKTOP --age-ranges 25-34 35-44 \\
    --brand-safety-exclude ADULT VIOLENCE --viewability-target 60 \\
    --dry-run

  # YouTube TrueView con CPV objetivo
  python scripts/dv360/line_items/create_line_item.py \\
    --client vidal-vidal --campaign-id 123 --io-id 456 \\
    --name "LI_YouTube_TrueView_Joyeria" --li-type YOUTUBE \\
    --budget-eur 2000 --start-date 2026-07-01 --end-date 2026-09-30 \\
    --bid-strategy TARGET_CPV --target-cpv-eur 0.05 \\
    --geo-regions "Spain" --genders FEMALE --age-ranges 25-34 35-44 45-54 \\
    --youtube-content-categories BEAUTY FASHION \\
    --frequency-cap 3 --frequency-cap-unit WEEKS \\
    --dry-run

  # YouTube Bumper con CPM objetivo
  python scripts/dv360/line_items/create_line_item.py \\
    --client vidal-vidal --campaign-id 123 --io-id 456 \\
    --name "LI_YouTube_Bumper_Awareness" --li-type YOUTUBE_BUMPER \\
    --budget-eur 500 --start-date 2026-07-01 --end-date 2026-07-31 \\
    --bid-strategy TARGET_CPM --bid-eur 8.0 \\
    --geo-regions "Spain" --device-types MOBILE \\
    --dry-run
        """,
    )

    parser.add_argument("--client", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--io-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--li-type", choices=list(LINE_ITEM_TYPES), default="DISPLAY")
    parser.add_argument("--budget-eur", required=True, type=float)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--bid-strategy", choices=list(BID_STRATEGIES), default="FIXED")
    parser.add_argument("--bid-eur", type=float, default=None)
    parser.add_argument("--bid-max-eur", type=float, default=None)
    parser.add_argument("--target-cpa-eur", type=float, default=None)
    parser.add_argument("--target-cpv-eur", type=float, default=None)
    parser.add_argument("--frequency-cap", type=int, default=None)
    parser.add_argument("--frequency-cap-unit", choices=list(FREQUENCY_CAP_UNITS), default=None)
    parser.add_argument("--creative-ids", nargs="+", default=[])
    parser.add_argument("--audience-expansion", action="store_true")
    parser.add_argument("--youtube-target-frequency", type=int, default=None)
    parser.add_argument("--content-labels-exclude", nargs="+", choices=list(CONTENT_LABELS), default=None)
    parser.add_argument("--brand-safety-exclude", nargs="+", choices=list(BRAND_SAFETY_CATEGORIES), default=None)
    parser.add_argument("--sensitive-categories-exclude", nargs="+", choices=list(SENSITIVE_CATEGORIES), default=None)
    parser.add_argument("--keyword-includes", nargs="+", default=None)
    parser.add_argument("--keyword-excludes", nargs="+", default=None)
    parser.add_argument("--iab-categories", nargs="+", default=None)
    parser.add_argument("--environment", choices=list(ENVIRONMENTS), default=None)
    parser.add_argument("--viewability-target", choices=list(VIEWABILITY_TARGETS), default=None)
    parser.add_argument("--positions", nargs="+", choices=list(POSITION_TYPES), default=None)
    parser.add_argument("--audience-list-ids", nargs="+", default=None)
    parser.add_argument("--audience-inmarket", nargs="+", default=None)
    parser.add_argument("--audience-affinity", nargs="+", default=None)
    parser.add_argument("--genders", nargs="+", choices=list(GENDER_TYPES), default=None)
    parser.add_argument("--age-ranges", nargs="+", choices=list(AGE_RANGES), default=None)
    parser.add_argument("--parental-status", nargs="+", choices=list(PARENTAL_STATUS), default=None)
    parser.add_argument("--geo-regions", nargs="+", default=None)
    parser.add_argument("--geo-cities", nargs="+", default=None)
    parser.add_argument("--geo-zip-codes", nargs="+", default=None)
    parser.add_argument("--geo-exclude", nargs="+", default=None)
    parser.add_argument("--language-codes", nargs="+", default=None)
    parser.add_argument("--daypart-matrix", type=str, default=None)
    parser.add_argument("--device-types", nargs="+", choices=list(DEVICE_TYPES), default=None)
    parser.add_argument("--operating-systems", nargs="+", choices=list(OS_TYPES), default=None)
    parser.add_argument("--browsers", nargs="+", choices=list(BROWSERS), default=None)
    parser.add_argument("--connection-speeds", nargs="+", choices=list(CONNECTION_SPEEDS), default=None)
    parser.add_argument("--youtube-content-categories", nargs="+", choices=list(YOUTUBE_CONTENT_CATEGORIES), default=None)
    parser.add_argument("--youtube-channel-ids", nargs="+", default=None)
    parser.add_argument("--youtube-video-ids", nargs="+", default=None)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    daypart_matrix = None
    if args.daypart_matrix:
        try:
            daypart_matrix = json.loads(args.daypart_matrix)
        except json.JSONDecodeError as e:
            print(f"Error parseando --daypart-matrix: {e}")
            sys.exit(1)

    result = create_line_item(
        client_id=args.client,
        campaign_id=args.campaign_id,
        io_id=args.io_id,
        name=args.name,
        li_type=args.li_type,
        budget_eur=args.budget_eur,
        start_date=args.start_date,
        end_date=args.end_date,
        bid_strategy=args.bid_strategy,
        bid_eur=args.bid_eur,
        bid_max_eur=args.bid_max_eur,
        target_cpa_eur=args.target_cpa_eur,
        target_cpv_eur=args.target_cpv_eur,
        frequency_cap=args.frequency_cap,
        frequency_cap_unit=args.frequency_cap_unit,
        creative_ids=args.creative_ids,
        audience_expansion=args.audience_expansion,
        youtube_target_frequency=args.youtube_target_frequency,
        content_labels_exclude=args.content_labels_exclude,
        brand_safety_exclude=args.brand_safety_exclude,
        sensitive_categories_exclude=args.sensitive_categories_exclude,
        keyword_includes=args.keyword_includes,
        keyword_excludes=args.keyword_excludes,
        iab_categories=args.iab_categories,
        environment=args.environment,
        viewability_target=args.viewability_target,
        positions=args.positions,
        audience_list_ids=args.audience_list_ids,
        audience_inmarket=args.audience_inmarket,
        audience_affinity=args.audience_affinity,
        genders=args.genders,
        age_ranges=args.age_ranges,
        parental_status=args.parental_status,
        geo_regions=args.geo_regions,
        geo_cities=args.geo_cities,
        geo_zip_codes=args.geo_zip_codes,
        geo_exclude=args.geo_exclude,
        language_codes=args.language_codes,
        daypart_matrix=daypart_matrix,
        device_types=args.device_types,
        operating_systems=args.operating_systems,
        browsers=args.browsers,
        connection_speeds=args.connection_speeds,
        youtube_content_categories=args.youtube_content_categories,
        youtube_channel_ids=args.youtube_channel_ids,
        youtube_video_ids=args.youtube_video_ids,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "partial", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()

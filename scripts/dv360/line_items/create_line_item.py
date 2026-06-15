"""
scripts/dv360/line_items/create_line_item.py
Crea un Line Item de Display en DV360 con targeting completo.

Jerarquia: Campaign → Insertion Order → Line Item → Creatives

El LI es la unidad de ejecucion tactica. Aqui se configura la puja exacta
y el targeting completo: brand safety, contenido, audiencia, geografia,
dayparting, tecnologia y asignacion de creatividades.

Uso:
    python scripts/dv360/line_items/create_line_item.py \\
        --client vidal-vidal \\
        --campaign-id 123456 \\
        --io-id 789012 \\
        --name "LI_Display_InMarket_Automocion_Desktop" \\
        --bid-eur 2.50 \\
        --budget-eur 1000 \\
        --start-date 2026-07-01 \\
        --end-date 2026-09-30 \\
        --geo-regions ES-MD ES-CT \\
        --device-types DESKTOP \\
        --audience-inmarket "Automotive/Cars & Trucks" \\
        --dry-run

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

# ── Valores validos ────────────────────────────────────────────────────────────

BID_STRATEGIES = {
    "FIXED":    "fixed",
    "MAXIMIZE": "maximizeSpend",
    "TARGET_CPA": "performanceGoalAutoBid",
}

DEVICE_TYPES = {
    "DESKTOP":    "DEVICE_TYPE_DESKTOP",
    "MOBILE":     "DEVICE_TYPE_SMART_PHONE",
    "TABLET":     "DEVICE_TYPE_TABLET",
    "CONNECTED":  "DEVICE_TYPE_CONNECTED_TV",
}

ENVIRONMENTS = {
    "DESKTOP_WEB":  "ENVIRONMENT_TYPE_BROWSER",
    "MOBILE_WEB":   "ENVIRONMENT_TYPE_BROWSER",
    "APP":          "ENVIRONMENT_TYPE_APP",
    "ALL":          "ENVIRONMENT_TYPE_ALL",
}

CONTENT_LABELS = {
    "G":   "CONTENT_RATING_TIER_G",
    "PG":  "CONTENT_RATING_TIER_PG",
    "T":   "CONTENT_RATING_TIER_T",
    "MA":  "CONTENT_RATING_TIER_MA",
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
    "50":  "VIEWABILITY_50_PERCENT_OR_MORE",
    "60":  "VIEWABILITY_60_PERCENT_OR_MORE",
    "70":  "VIEWABILITY_70_PERCENT_OR_MORE",
    "80":  "VIEWABILITY_80_PERCENT_OR_MORE",
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
    "ANDROID":   "OPERATING_SYSTEM_ANDROID",
    "IOS":       "OPERATING_SYSTEM_IOS",
    "WINDOWS":   "OPERATING_SYSTEM_WINDOWS",
    "MACOS":     "OPERATING_SYSTEM_MAC_OS_X",
    "CHROMEOS":  "OPERATING_SYSTEM_CHROME_OS",
}

CONNECTION_SPEEDS = {
    "WIFI":   "CONNECTION_SPEED_WIFI",
    "4G":     "CONNECTION_SPEED_4G",
    "5G":     "CONNECTION_SPEED_5G",
    "3G":     "CONNECTION_SPEED_3G",
    "ALL":    "CONNECTION_SPEED_ALL",
}

SENSITIVE_CATEGORIES = {
    "POLITICS":    "SENSITIVE_CATEGORY_POLITICS",
    "RELIGION":    "SENSITIVE_CATEGORY_RELIGION",
    "GAMBLING":    "SENSITIVE_CATEGORY_GAMBLING",
    "TRAGEDY":     "SENSITIVE_CATEGORY_TRAGEDY",
    "WEAPONS":     "SENSITIVE_CATEGORY_WEAPONS",
    "ADULT":       "SENSITIVE_CATEGORY_ADULT",
    "DRUGS":       "SENSITIVE_CATEGORY_ILLEGAL_DRUGS",
    "VIOLENCE":    "SENSITIVE_CATEGORY_VIOLENCE",
    "HATE":        "SENSITIVE_CATEGORY_HATE_SPEECH",
    "TOBACCO":     "SENSITIVE_CATEGORY_TOBACCO",
}

BRAND_SAFETY_CATEGORIES = {
    "ADULT":      "BRAND_SAFETY_ADULT",
    "WEAPONS":    "BRAND_SAFETY_ARMS",
    "VIOLENCE":   "BRAND_SAFETY_CRIME_VIOLENCE",
    "DRUGS":      "BRAND_SAFETY_DRUGS",
    "HATE":       "BRAND_SAFETY_HATE_SPEECH",
    "TRAGEDY":    "BRAND_SAFETY_TRAGEDY",
    "TOBACCO":    "BRAND_SAFETY_TOBACCO",
}


def _eur_to_micros(eur: float) -> int:
    return int(eur * _EUR_TO_MICROS)


def _parse_date(date_str: str) -> dict:
    parts = date_str.split("-")
    return {"year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])}


def build_targeting_settings(
    # Brand Safety
    content_labels: list[str] | None,
    brand_safety_categories: list[str] | None,
    sensitive_categories: list[str] | None,
    # Content
    keyword_includes: list[str] | None,
    keyword_excludes: list[str] | None,
    iab_categories: list[str] | None,
    environment: str | None,
    viewability_target: str | None,
    positions: list[str] | None,
    # Audience
    audience_list_ids: list[str] | None,
    audience_inmarket: list[str] | None,
    audience_affinity: list[str] | None,
    audience_expansion: bool,
    genders: list[str] | None,
    age_ranges: list[str] | None,
    parental_status: list[str] | None,
    # Geography
    geo_regions: list[str] | None,
    geo_cities: list[str] | None,
    geo_zip_codes: list[str] | None,
    geo_exclude: list[str] | None,
    language_codes: list[str] | None,
    # Day & Time
    daypart_matrix: dict | None,
    # Technology
    device_types: list[str] | None,
    operating_systems: list[str] | None,
    browsers: list[str] | None,
    connection_speeds: list[str] | None,
) -> list[dict]:
    """
    Construye la lista de targeting options para el LI.

    Cada targeting option es un dict con targetingType y assignedTargetingOptionDetails.
    Se aplica la logica AND entre categorias y OR dentro de cada categoria.

    Returns:
        Lista de assigned targeting options lista para la API
    """
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
                "keywordDetails": {
                    "keyword": kw,
                    "negative": False,
                },
            })

    if keyword_excludes:
        for kw in keyword_excludes:
            targeting.append({
                "targetingType": "TARGETING_TYPE_KEYWORD",
                "keywordDetails": {
                    "keyword": kw,
                    "negative": True,
                },
            })

    if iab_categories:
        for cat in iab_categories:
            targeting.append({
                "targetingType": "TARGETING_TYPE_CATEGORY",
                "categoryDetails": {
                    "displayName": cat,
                    "negative": False,
                },
            })

    if environment:
        mapped = ENVIRONMENTS.get(environment.upper())
        if mapped:
            targeting.append({
                "targetingType": "TARGETING_TYPE_ENVIRONMENT",
                "environmentDetails": {
                    "environment": mapped,
                },
            })

    if viewability_target:
        mapped = VIEWABILITY_TARGETS.get(str(viewability_target))
        if mapped:
            targeting.append({
                "targetingType": "TARGETING_TYPE_VIEWABILITY",
                "viewabilityDetails": {
                    "viewability": mapped,
                },
            })

    if positions:
        for pos in positions:
            mapped = POSITION_TYPES.get(pos.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_ON_SCREEN_POSITION",
                    "onScreenPositionDetails": {
                        "onScreenPosition": mapped,
                    },
                })

    # ── Audience ──────────────────────────────────────────────────────────────

    if audience_list_ids:
        # First-party / remarketing lists
        audience_group = {
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
        }
        targeting.append({
            "targetingType": "TARGETING_TYPE_AUDIENCE_GROUP",
            "audienceGroupDetails": audience_group,
        })

    if audience_inmarket:
        for audience in audience_inmarket:
            targeting.append({
                "targetingType": "TARGETING_TYPE_AUDIENCE_GROUP",
                "audienceGroupDetails": {
                    "includedGoogleAudienceGroup": {
                        "settings": [
                            {
                                "targetingOptionId": audience,
                                "negative": False,
                            }
                        ]
                    }
                },
            })

    if audience_affinity:
        for audience in audience_affinity:
            targeting.append({
                "targetingType": "TARGETING_TYPE_AUDIENCE_GROUP",
                "audienceGroupDetails": {
                    "includedGoogleAudienceGroup": {
                        "settings": [
                            {
                                "targetingOptionId": audience,
                                "negative": False,
                            }
                        ]
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
                "geoRegionDetails": {
                    "displayName": region,
                    "negative": True,
                },
            })

    if language_codes:
        for lang in language_codes:
            targeting.append({
                "targetingType": "TARGETING_TYPE_LANGUAGE",
                "languageDetails": {
                    "displayName": lang,
                    "negative": False,
                },
            })

    # ── Day & Time (Dayparting) ───────────────────────────────────────────────

    if daypart_matrix:
        # daypart_matrix formato: {"MONDAY": [9, 10, 11, 18, 19], "TUESDAY": [...]}
        # Horas en formato 0-23
        day_map = {
            "MONDAY": "DAYOFWEEK_MONDAY",
            "TUESDAY": "DAYOFWEEK_TUESDAY",
            "WEDNESDAY": "DAYOFWEEK_WEDNESDAY",
            "THURSDAY": "DAYOFWEEK_THURSDAY",
            "FRIDAY": "DAYOFWEEK_FRIDAY",
            "SATURDAY": "DAYOFWEEK_SATURDAY",
            "SUNDAY": "DAYOFWEEK_SUNDAY",
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

    # ── Technology ───────────────────────────────────────────────────────────

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
            mapped = OS_TYPES.get(os_name.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_OPERATING_SYSTEM",
                    "operatingSystemDetails": {
                        "displayName": os_name,
                        "negative": False,
                    },
                })

    if browsers:
        for browser in browsers:
            mapped = BROWSERS.get(browser.upper())
            if mapped:
                targeting.append({
                    "targetingType": "TARGETING_TYPE_BROWSER",
                    "browserDetails": {
                        "displayName": browser,
                        "negative": False,
                    },
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


def build_li_body(
    advertiser_id: str,
    campaign_id: str,
    io_id: str,
    name: str,
    budget_eur: float,
    start_date: str,
    end_date: str,
    bid_strategy: str,
    bid_eur: float | None,
    bid_max_eur: float | None,
    target_cpa_eur: float | None,
    frequency_cap: int | None,
    frequency_cap_unit: str | None,
    creative_ids: list[str],
    targeting: list[dict],
    audience_expansion: bool,
) -> dict:
    """
    Construye el body completo para lineItems.create.
    """
    body = {
        "advertiserId": advertiser_id,
        "campaignId": campaign_id,
        "insertionOrderId": io_id,
        "displayName": name,
        "lineItemType": "LINE_ITEM_TYPE_DISPLAY_DEFAULT",
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
        "targetingExpansion": {
            "targetingExpansionLevel": "TARGETING_EXPANSION_LEVEL_NO_EXPANSION"
            if not audience_expansion
            else "TARGETING_EXPANSION_LEVEL_LEAST_EXPANSION",
            "excludeFirstPartyAudience": not audience_expansion,
        },
    }

    # Bid strategy
    if bid_strategy.upper() == "FIXED" and bid_eur:
        body["bidStrategy"] = {
            "fixedBid": {
                "bidAmountMicros": str(_eur_to_micros(bid_eur)),
            }
        }
    elif bid_strategy.upper() == "MAXIMIZE":
        strategy = {"performanceGoalType": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPA"}
        if bid_max_eur:
            strategy["maxAverageCpmBidAmountMicros"] = str(_eur_to_micros(bid_max_eur))
        body["bidStrategy"] = {"maximizeSpendAutoBid": strategy}
    elif bid_strategy.upper() == "TARGET_CPA" and target_cpa_eur:
        body["bidStrategy"] = {
            "performanceGoalAutoBid": {
                "performanceGoalType": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPA",
                "performanceGoalAmountMicros": str(_eur_to_micros(target_cpa_eur)),
            }
        }

    # Frequency cap a nivel LI
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

    # Creatividades asignadas
    if creative_ids:
        body["creativeIds"] = creative_ids

    return body, targeting


def create_line_item(
    client_id: str,
    campaign_id: str,
    io_id: str,
    name: str,
    budget_eur: float,
    start_date: str,
    end_date: str,
    bid_strategy: str = "FIXED",
    bid_eur: float | None = None,
    bid_max_eur: float | None = None,
    target_cpa_eur: float | None = None,
    frequency_cap: int | None = None,
    frequency_cap_unit: str | None = None,
    creative_ids: list[str] = None,
    audience_expansion: bool = False,
    # Brand Safety
    content_labels_exclude: list[str] | None = None,
    brand_safety_exclude: list[str] | None = None,
    sensitive_categories_exclude: list[str] | None = None,
    # Content
    keyword_includes: list[str] | None = None,
    keyword_excludes: list[str] | None = None,
    iab_categories: list[str] | None = None,
    environment: str | None = None,
    viewability_target: str | None = None,
    positions: list[str] | None = None,
    # Audience
    audience_list_ids: list[str] | None = None,
    audience_inmarket: list[str] | None = None,
    audience_affinity: list[str] | None = None,
    genders: list[str] | None = None,
    age_ranges: list[str] | None = None,
    parental_status: list[str] | None = None,
    # Geography
    geo_regions: list[str] | None = None,
    geo_cities: list[str] | None = None,
    geo_zip_codes: list[str] | None = None,
    geo_exclude: list[str] | None = None,
    language_codes: list[str] | None = None,
    # Dayparting
    daypart_matrix: dict | None = None,
    # Technology
    device_types: list[str] | None = None,
    operating_systems: list[str] | None = None,
    browsers: list[str] | None = None,
    connection_speeds: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Crea un Line Item de Display en DV360 con targeting completo.

    El LI se crea siempre en DRAFT para revision.
    Usar activate_line_item.py para activarlo tras revision.
    """
    if creative_ids is None:
        creative_ids = []

    advertiser_id = get_advertiser_id(client_id)

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
    )

    body, targeting_list = build_li_body(
        advertiser_id=advertiser_id,
        campaign_id=campaign_id,
        io_id=io_id,
        name=name,
        budget_eur=budget_eur,
        start_date=start_date,
        end_date=end_date,
        bid_strategy=bid_strategy,
        bid_eur=bid_eur,
        bid_max_eur=bid_max_eur,
        target_cpa_eur=target_cpa_eur,
        frequency_cap=frequency_cap,
        frequency_cap_unit=frequency_cap_unit,
        creative_ids=creative_ids,
        targeting=targeting,
        audience_expansion=audience_expansion,
    )

    action_msg = (
        f"Crear Line Item '{name}' "
        f"(IO {io_id}, budget {budget_eur} EUR, "
        f"bid {bid_strategy} {bid_eur or target_cpa_eur or 'auto'} EUR, "
        f"{len(targeting_list)} targeting options) "
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
                "body": body,
                "targeting_options_count": len(targeting_list),
                "targeting_options": targeting_list,
                "note": "LI se crearia en DRAFT. Revisar body y targeting antes de ejecutar.",
            },
        }

    try:
        svc = build_writer_service(client_id=client_id)

        # 1. Crear el Line Item
        li_result = (
            svc.advertisers()
            .lineItems()
            .create(advertiserId=advertiser_id, body=body)
            .execute()
        )
        li_id = li_result.get("lineItemId")

        # 2. Asignar targeting options (llamada separada en v4)
        targeting_errors = []
        if targeting_list:
            for t_option in targeting_list:
                try:
                    svc.advertisers().lineItems().targetingOptions().create(
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
                "campaign_id": li_result.get("campaignId"),
                "io_id": li_result.get("insertionOrderId"),
                "name": li_result.get("displayName"),
                "entity_status": li_result.get("entityStatus"),
                "targeting_options_applied": len(targeting_list) - len(targeting_errors),
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
            "budget_eur": budget_eur,
            "bid_strategy": bid_strategy,
            "bid_eur": bid_eur,
            "targeting_options": len(targeting_list),
            "advertiser_id": advertiser_id,
        },
        result=outcome,
        dry_run=dry_run,
    )

    if outcome["status"] in ("ok", "partial"):
        li_id = outcome["data"]["line_item_id"]
        print(f"\n✅ Line Item creado en DRAFT. line_item_id: {li_id}")
        if targeting_errors:
            print(f"⚠️  {len(targeting_errors)} opciones de targeting fallaron. Revisar targeting_errors.")
        print("Siguiente paso: asignar creatividades si no se hizo en la creacion.")
        print(f"\nCuando este listo, activar el LI:")
        print(
            f"  python scripts/dv360/line_items/activate_line_item.py "
            f"--client {client_id} --line-item-id {li_id}"
        )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea un Line Item de Display en DV360 con targeting completo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Bid strategies (--bid-strategy):
  FIXED       Puja fija CPM (requiere --bid-eur)
  MAXIMIZE    Maximizar conversiones/clicks (opcional --bid-max-eur como techo CPM)
  TARGET_CPA  Puja automatica con CPA objetivo (requiere --target-cpa-eur)

Device types (--device-types):
  DESKTOP MOBILE TABLET CONNECTED

Environments (--environment):
  DESKTOP_WEB MOBILE_WEB APP ALL

Content labels a excluir (--content-labels-exclude):
  G PG T MA

Brand safety a excluir (--brand-safety-exclude):
  ADULT WEAPONS VIOLENCE DRUGS HATE TRAGEDY TOBACCO

Generos (--genders):
  MALE FEMALE UNKNOWN

Edades (--age-ranges):
  18-24 25-34 35-44 45-54 55-64 65+

Viewability (--viewability-target):
  50 60 70 80  (porcentaje minimo predicho)

Posiciones (--positions):
  ATF BTF UNKNOWN

Sistemas operativos (--operating-systems):
  ANDROID IOS WINDOWS MACOS CHROMEOS

Navegadores (--browsers):
  CHROME SAFARI FIREFOX EDGE OPERA

Conexion (--connection-speeds):
  WIFI 4G 5G 3G ALL

Daypart matrix (--daypart-matrix):
  JSON con dias y horas (0-23):
  '{"MONDAY":[9,10,11,17,18,19],"FRIDAY":[9,10,11]}'

Ejemplos:
  # LI basico con targeting geografico y de dispositivo
  python scripts/dv360/line_items/create_line_item.py \\
    --client vidal-vidal \\
    --campaign-id 123456 \\
    --io-id 789012 \\
    --name "LI_Display_InMarket_Desktop_Madrid" \\
    --budget-eur 1000 \\
    --start-date 2026-07-01 \\
    --end-date 2026-09-30 \\
    --bid-strategy FIXED \\
    --bid-eur 2.50 \\
    --geo-regions "Madrid" \\
    --device-types DESKTOP \\
    --age-ranges 25-34 35-44 \\
    --brand-safety-exclude ADULT VIOLENCE \\
    --viewability-target 60 \\
    --dry-run

  # LI con puja automatica y audience inmarket
  python scripts/dv360/line_items/create_line_item.py \\
    --client vidal-vidal \\
    --campaign-id 123456 \\
    --io-id 789012 \\
    --name "LI_Display_Maximize_InMarket_Joyeria" \\
    --budget-eur 2000 \\
    --start-date 2026-07-01 \\
    --end-date 2026-09-30 \\
    --bid-strategy MAXIMIZE \\
    --bid-max-eur 5.0 \\
    --geo-regions "Spain" \\
    --audience-inmarket "Jewelry & Watches" \\
    --genders FEMALE \\
    --age-ranges 25-34 35-44 45-54 \\
    --environment DESKTOP_WEB \\
    --viewability-target 60 \\
    --brand-safety-exclude ADULT VIOLENCE \\
    --frequency-cap 5 \\
    --frequency-cap-unit DAYS \\
    --dry-run
        """,
    )
    # Identificacion
    parser.add_argument("--client", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--io-id", required=True)
    parser.add_argument("--name", required=True)

    # Budget y fechas
    parser.add_argument("--budget-eur", required=True, type=float)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)

    # Bid
    parser.add_argument("--bid-strategy", choices=["FIXED", "MAXIMIZE", "TARGET_CPA"], default="FIXED")
    parser.add_argument("--bid-eur", type=float, default=None, help="CPM fijo en EUR (para FIXED)")
    parser.add_argument("--bid-max-eur", type=float, default=None, help="Techo CPM en EUR (para MAXIMIZE)")
    parser.add_argument("--target-cpa-eur", type=float, default=None, help="CPA objetivo en EUR (para TARGET_CPA)")

    # Frequency
    parser.add_argument("--frequency-cap", type=int, default=None)
    parser.add_argument("--frequency-cap-unit", choices=["MINUTES","HOURS","DAYS","WEEKS","MONTHS"], default=None)

    # Creatividades
    parser.add_argument("--creative-ids", nargs="+", default=[], help="IDs de creatividades a asignar")
    parser.add_argument("--audience-expansion", action="store_true", help="Activar Optimized Targeting (expansion de audiencia)")

    # Brand Safety
    parser.add_argument("--content-labels-exclude", nargs="+", choices=["G","PG","T","MA"], default=None)
    parser.add_argument("--brand-safety-exclude", nargs="+", choices=list(BRAND_SAFETY_CATEGORIES), default=None)
    parser.add_argument("--sensitive-categories-exclude", nargs="+", choices=list(SENSITIVE_CATEGORIES), default=None)

    # Content
    parser.add_argument("--keyword-includes", nargs="+", default=None)
    parser.add_argument("--keyword-excludes", nargs="+", default=None)
    parser.add_argument("--iab-categories", nargs="+", default=None, help="Categorias IAB (ej. 'Sports/Soccer')")
    parser.add_argument("--environment", choices=["DESKTOP_WEB","MOBILE_WEB","APP","ALL"], default=None)
    parser.add_argument("--viewability-target", choices=["50","60","70","80"], default=None)
    parser.add_argument("--positions", nargs="+", choices=["ATF","BTF","UNKNOWN"], default=None)

    # Audience
    parser.add_argument("--audience-list-ids", nargs="+", default=None, help="IDs de listas first-party/remarketing")
    parser.add_argument("--audience-inmarket", nargs="+", default=None, help="Audiencias In-Market de Google")
    parser.add_argument("--audience-affinity", nargs="+", default=None, help="Audiencias de Afinidad de Google")
    parser.add_argument("--genders", nargs="+", choices=["MALE","FEMALE","UNKNOWN"], default=None)
    parser.add_argument("--age-ranges", nargs="+", choices=["18-24","25-34","35-44","45-54","55-64","65+"], default=None)
    parser.add_argument("--parental-status", nargs="+", choices=["PARENT","NOT_PARENT","UNKNOWN"], default=None)

    # Geography
    parser.add_argument("--geo-regions", nargs="+", default=None, help="Regiones/paises (ej. 'Spain' 'Madrid')")
    parser.add_argument("--geo-cities", nargs="+", default=None, help="Ciudades especificas")
    parser.add_argument("--geo-zip-codes", nargs="+", default=None, help="Codigos postales")
    parser.add_argument("--geo-exclude", nargs="+", default=None, help="Geografias a excluir")
    parser.add_argument("--language-codes", nargs="+", default=None, help="Idiomas (ej. 'Spanish' 'English')")

    # Dayparting
    parser.add_argument("--daypart-matrix", type=str, default=None,
                        help="JSON con dias y horas: '{\"MONDAY\":[9,10,11]}'")

    # Technology
    parser.add_argument("--device-types", nargs="+", choices=["DESKTOP","MOBILE","TABLET","CONNECTED"], default=None)
    parser.add_argument("--operating-systems", nargs="+", choices=list(OS_TYPES), default=None)
    parser.add_argument("--browsers", nargs="+", choices=list(BROWSERS), default=None)
    parser.add_argument("--connection-speeds", nargs="+", choices=["WIFI","4G","5G","3G","ALL"], default=None)

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
        budget_eur=args.budget_eur,
        start_date=args.start_date,
        end_date=args.end_date,
        bid_strategy=args.bid_strategy,
        bid_eur=args.bid_eur,
        bid_max_eur=args.bid_max_eur,
        target_cpa_eur=args.target_cpa_eur,
        frequency_cap=args.frequency_cap,
        frequency_cap_unit=args.frequency_cap_unit,
        creative_ids=args.creative_ids,
        audience_expansion=args.audience_expansion,
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
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "partial", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()

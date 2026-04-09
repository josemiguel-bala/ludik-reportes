#!/usr/bin/env python3
"""Valida que un JSON de reporte tenga TODOS los campos requeridos."""
import json, sys

REQUIRED_STRUCTURE = {
    "brand": str, "period": str, "fx_rate": (int,float), "metricool_id": str,
    "portada": {"tag": str, "footer": str, "kpis": list},
    "cierre": {"tagline": str, "team": str, "location": str, "contact": str, "confidential": str},
    "objectives": list,
    "summary_kpis": {"objectives": str, "reach": str, "tk_views": str, "new_followers": str, "investment": str},
    "community": {
        "facebook": {"start": (int,float), "end": (int,float)},
        "instagram": {"start": (int,float), "end": (int,float)},
        "tiktok": {"start": (int,float), "end": (int,float)},
    },
    "reach": {"total_impressions": (int,float), "estimated_unique_reach": (int,float), "frequency": (int,float),
              "meta_ads_impressions": (int,float), "meta_ads_reach": (int,float),
              "tiktok_ads_impressions": (int,float), "tiktok_organic_views": (int,float)},
    "engagement": {"tiktok_organic": dict, "meta_ads_clicks": (int,float), "total_meaningful_interactions": (int,float)},
    "investment": {"meta_ads_usd": (int,float), "meta_ads_soles": (int,float),
                   "tiktok_ads_usd": (int,float), "tiktok_ads_soles": (int,float),
                   "total_usd": (int,float), "total_soles": (int,float),
                   "meta_pct": (int,float), "tiktok_pct": (int,float)},
    "efficiency": {"meta_cpm_usd": (int,float), "tiktok_cpm_usd": (int,float), "blended_cpm_usd": (int,float)},
    "sentiment": {"total": (int,float), "positive_pct": (int,float), "neutral_pct": (int,float),
                  "negative_pct": (int,float), "net_score": (int,float)},
    "bhs": {"total": (int,float), "benchmark": str, "dimensions": dict},
    "competitors_ig": list,
    "insights": {"community": str, "reach": str, "engagement": str, "sentiment": str, "investment": str, "competition": str},
    "story": {"act1": {"number": str, "title": str}, "act2": {"number": str, "title": str}, "act3": {"number": str, "title": str}, "act4": {"number": str, "title": str}, "act5": {"number": str, "title": str}},
    "content": {"top_tiktok": list},
    "technical_texts": {"resumen": str, "contenido_insight": str, "bhs_explicacion": str},
    "recommendations": list,
    "charts": {"months6": list, "reach_mix_labels": list, "reach_mix_data": list,
               "cpm_meta": list, "cpm_tk": list, "bhs_radar": list},
}

def validate(data, schema, path=""):
    errors = []
    for key, expected in schema.items():
        full_path = f"{path}.{key}" if path else key
        if key not in data:
            errors.append(f"  FALTA: {full_path}")
        elif isinstance(expected, dict):
            if isinstance(data[key], dict):
                errors.extend(validate(data[key], expected, full_path))
            else:
                errors.append(f"  TIPO MAL: {full_path} debe ser dict, es {type(data[key]).__name__}")
        elif isinstance(expected, tuple):
            if not isinstance(data[key], expected):
                errors.append(f"  TIPO MAL: {full_path} debe ser {expected}, es {type(data[key]).__name__}: {data[key]}")
        elif expected == list:
            if not isinstance(data[key], list):
                errors.append(f"  TIPO MAL: {full_path} debe ser list")
        elif expected == str:
            if not isinstance(data[key], str):
                errors.append(f"  TIPO MAL: {full_path} debe ser str, es {type(data[key]).__name__}")
    return errors

if __name__ == "__main__":
    files = sys.argv[1:] or ["data/ISANA_2026-03.json", "data/BUK_2026-03.json", "data/DEPILE_2026-03.json"]
    all_ok = True
    for f in files:
        try:
            data = json.load(open(f))
            errors = validate(data, REQUIRED_STRUCTURE)
            if errors:
                print(f"\n✗ {f} — {len(errors)} problemas:")
                for e in errors: print(e)
                all_ok = False
            else:
                print(f"✓ {f} — OK")
        except Exception as e:
            print(f"✗ {f} — ERROR: {e}")
            all_ok = False
    if all_ok:
        print("\n✓ Todos los JSONs válidos y completos")
    sys.exit(0 if all_ok else 1)

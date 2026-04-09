#!/usr/bin/env python3
"""
LUDiK Report Data Pipeline v1.0
Jala TODA la data de Metricool + CSVs de Ads → genera JSON limpio.
Cada campo tiene source verificable. Nunca inventa datos.

Uso:
  python3 pull_data.py BUK 2026-03
  python3 pull_data.py ISANA 2026-03
  python3 pull_data.py --all 2026-03    (todas las marcas)
"""
import json, os, sys, csv, glob
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════
APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
INPUTS_DIR = DATA_DIR / "inputs"
BRANDS_FILE = APP_DIR / "brands.json"

with open(BRANDS_FILE) as f:
    BRANDS = {b["id"]: b for b in json.load(f)["brands"]}

# ═══════════════════════════════════════════════
# METRICOOL MCP STUB
# Este script NO llama directamente al API.
# Genera un archivo de instrucciones para que
# Claude ejecute los MCP calls y guarde los raw JSONs.
# ═══════════════════════════════════════════════

def get_period_range(period_str):
    """'2026-03' → ('2026-03-01', '2026-03-31')"""
    y, m = period_str.split("-")
    start = f"{y}-{m}-01"
    if int(m) == 12:
        end = f"{y}-12-31"
    else:
        from calendar import monthrange
        _, last = monthrange(int(y), int(m))
        end = f"{y}-{m}-{last:02d}"
    return start, end

def get_6month_range(period_str):
    """Returns start of 6 months ago"""
    y, m = int(period_str[:4]), int(period_str[5:7])
    for _ in range(5):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return f"{y}-{m:02d}-01"


# ═══════════════════════════════════════════════
# CSV PARSERS
# ═══════════════════════════════════════════════

def parse_meta_ads_csv(filepath):
    """Parse Meta Ads campaign CSV. Returns dict with spend, impressions, reach."""
    result = {"spend_usd": 0, "impressions": 0, "reach": 0, "clicks": 0,
              "link_clicks": 0, "post_engagements": 0, "thru_plays": 0,
              "video_3s_views": 0, "campaigns": [], "source": str(filepath)}
    try:
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                spend = row.get("Importe gastado (USD)", "0").replace(",", ".")
                try:
                    spend = float(spend)
                except:
                    spend = 0
                if spend <= 0:
                    continue
                imp = int(row.get("Impresiones", "0").replace(",", "").replace(".", "") or 0)
                reach = int(row.get("Alcance", "0").replace(",", "").replace(".", "") or 0)
                clicks = int(row.get("Clics (todos)", "0").replace(",", "").replace(".", "") or 0)
                link_clicks = int(row.get("Clics en el enlace", "0").replace(",", "").replace(".", "") or 0)

                result["spend_usd"] += spend
                result["impressions"] += imp
                result["reach"] += reach
                result["clicks"] += clicks
                result["link_clicks"] += link_clicks
                result["campaigns"].append({
                    "name": row.get("Nombre de la campaña", ""),
                    "spend_usd": round(spend, 2),
                    "impressions": imp,
                    "reach": reach
                })
    except Exception as e:
        result["error"] = str(e)
    result["spend_usd"] = round(result["spend_usd"], 2)
    return result


def parse_tiktok_ads_csv(filepath):
    """Parse TikTok Ads CSV. Returns dict with spend, impressions."""
    result = {"spend_usd": 0, "impressions": 0, "results": 0,
              "ads": [], "source": str(filepath)}
    try:
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Ad name", "").startswith("Total"):
                    continue
                cost_str = row.get("Cost", "0").replace(",", ".")
                try:
                    cost = float(cost_str)
                except:
                    cost = 0
                if cost <= 0:
                    continue
                imp = int(row.get("Impressions", "0").replace(",", "").replace(".", "") or 0)
                results = int(row.get("Results", "0").replace(",", "").replace(".", "") or 0)
                result["spend_usd"] += cost
                result["impressions"] += imp
                result["results"] += results
                result["ads"].append({
                    "name": row.get("Ad name", "")[:50],
                    "cost": round(cost, 2),
                    "impressions": imp
                })
    except Exception as e:
        result["error"] = str(e)
    result["spend_usd"] = round(result["spend_usd"], 2)
    return result


def parse_comments_csvs(folder):
    """Parse all TTCommentExporter CSVs + any IG comment CSVs."""
    comments = []
    for f in glob.glob(str(folder / "TTCommentExporter*.csv")):
        try:
            with open(f, encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    text = row.get("Comment Body", row.get("text", "")).strip()
                    if text:
                        comments.append({"text": text, "source": "tiktok", "file": os.path.basename(f)})
        except:
            pass
    # IG comments (various formats)
    for f in glob.glob(str(folder / "*.csv")):
        bn = os.path.basename(f)
        if bn.startswith("TTComment") or "Anuncios" in bn or "Campañas" in bn or "Campaign" in bn:
            continue
        try:
            with open(f, encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                fields = reader.fieldnames or []
                if "text" in fields or "userName" in fields:
                    for row in reader:
                        text = row.get("text", "").strip()
                        if text:
                            comments.append({"text": text, "source": "instagram", "file": bn})
        except:
            pass
    return comments


# ═══════════════════════════════════════════════
# ADS HISTORY LOADER
# ═══════════════════════════════════════════════

def load_ads_history(brand_id, current_period):
    """Load 6 months of ads data from CSVs."""
    y, m = int(current_period[:4]), int(current_period[5:7])
    months = []
    for i in range(5, -1, -1):
        tm = m - i
        ty = y
        while tm <= 0:
            tm += 12
            ty -= 1
        months.append(f"{ty}-{tm:02d}")

    history = []
    for period in months:
        month_dir = INPUTS_DIR / brand_id / period
        meta_spend = 0
        meta_imp = 0
        meta_reach = 0
        tk_spend = 0
        tk_imp = 0

        # Meta Ads campaigns CSV
        for f in sorted(glob.glob(str(month_dir / "*Campañas*META*.csv")) +
                        glob.glob(str(month_dir / "*Campaña*META*.csv"))):
            data = parse_meta_ads_csv(f)
            meta_spend += data["spend_usd"]
            meta_imp += data["impressions"]
            meta_reach += data["reach"]

        # TikTok Ads CSV
        for f in sorted(glob.glob(str(month_dir / "*ik*tok*Campaign*.csv")) +
                        glob.glob(str(month_dir / "*ik*tok*Anuncios*.csv")) +
                        glob.glob(str(month_dir / "TIktok*.csv")) +
                        glob.glob(str(month_dir / "Tik tok*.csv"))):
            data = parse_tiktok_ads_csv(f)
            tk_spend += data["spend_usd"]
            tk_imp += data["impressions"]

        history.append({
            "period": period,
            "meta_spend_usd": round(meta_spend, 2),
            "meta_impressions": meta_imp,
            "meta_reach": meta_reach,
            "tk_spend_usd": round(tk_spend, 2),
            "tk_impressions": tk_imp,
            "total_spend_usd": round(meta_spend + tk_spend, 2),
            "total_impressions": meta_imp + tk_imp
        })
    return history


# ═══════════════════════════════════════════════
# CALCULATIONS
# ═══════════════════════════════════════════════

def calc_cpm(spend, impressions):
    """CPM = spend / impressions × 1000"""
    if not impressions or impressions == 0:
        return None
    return round(spend / impressions * 1000, 2)


def calc_er(interactions, reach_or_followers):
    """ER = interactions / base × 100"""
    if not reach_or_followers or reach_or_followers == 0:
        return None
    return round(interactions / reach_or_followers * 100, 2)


def calc_indice_valor(saves, shares, comments, likes, reach):
    """IV = (saves×3 + shares×2 + comments×1.5 + likes×1) / reach × 1000"""
    if not reach or reach == 0:
        return None
    return round((saves * 3 + shares * 2 + comments * 1.5 + likes) / reach * 1000, 2)


def calc_bhs(dimensions):
    """BHS = weighted average of 7 dimensions."""
    weights = {
        "crecimiento": 0.10, "alcance": 0.10, "engagement": 0.20,
        "sentimiento": 0.15, "eficiencia": 0.10, "metas": 0.10,
        "posicion_comp": 0.25
    }
    total = sum(dimensions.get(k, 0) * w for k, w in weights.items())
    return round(total)


# ═══════════════════════════════════════════════
# METRICOOL CALLS MANIFEST
# ═══════════════════════════════════════════════

def generate_metricool_manifest(brand_id, period):
    """
    Generates list of ALL Metricool API calls needed.
    This manifest can be executed by Claude MCP or by a script.
    """
    brand = BRANDS[brand_id]
    blog_id = int(brand["metricool_id"])
    tz = "America/Lima"
    start, end = get_period_range(period)
    hist_start = get_6month_range(period)

    calls = [
        # Current month analytics
        {"tool": "get_analytics", "params": {"blog_id": blog_id, "start": start, "end": end,
         "timezone": tz, "network": "facebook", "metric": ["pageFollows", "page_posts_impressions", "page_actions_post_reactions_total", "pageViews"]},
         "output": f"raw/fb_analytics_{period}.json"},

        {"tool": "get_analytics", "params": {"blog_id": blog_id, "start": start, "end": end,
         "timezone": tz, "network": "instagram", "metric": ["followers"]},
         "output": f"raw/ig_analytics_{period}.json"},

        {"tool": "get_analytics", "params": {"blog_id": blog_id, "start": start, "end": end,
         "timezone": tz, "network": "tiktok", "metric": ["followers_count", "video_views", "profile_views", "likes", "comments", "shares"]},
         "output": f"raw/tk_analytics_{period}.json"},

        # Historical (6 months)
        {"tool": "get_analytics", "params": {"blog_id": blog_id, "start": hist_start, "end": end,
         "timezone": tz, "network": "facebook", "metric": ["pageFollows"]},
         "output": f"raw/fb_followers_hist.json"},

        {"tool": "get_analytics", "params": {"blog_id": blog_id, "start": hist_start, "end": end,
         "timezone": tz, "network": "instagram", "metric": ["followers"]},
         "output": f"raw/ig_followers_hist.json"},

        {"tool": "get_analytics", "params": {"blog_id": blog_id, "start": hist_start, "end": end,
         "timezone": tz, "network": "instagram", "metric": ["postsCount", "postsInteractions"]},
         "output": f"raw/ig_er_hist.json"},

        # Posts/videos
        {"tool": "get_tiktok_videos", "params": {"blog_id": blog_id, "init_date": start, "end_date": end},
         "output": f"raw/tk_videos_{period}.json"},

        {"tool": "get_instagram_reels", "params": {"blog_id": blog_id, "init_date": start, "end_date": end},
         "output": f"raw/ig_reels_{period}.json"},

        {"tool": "get_instagram_posts", "params": {"blog_id": blog_id, "init_date": start, "end_date": end},
         "output": f"raw/ig_posts_{period}.json"},

        {"tool": "get_facebook_posts", "params": {"blog_id": blog_id, "init_date": start, "end_date": end},
         "output": f"raw/fb_posts_{period}.json"},

        # Competitors
        {"tool": "get_network_competitors", "params": {"blog_id": blog_id, "network": "instagram",
         "init_date": start, "end_date": end, "limit": 10, "timezone": tz},
         "output": f"raw/competitors_ig_{period}.json"},

        {"tool": "get_network_competitors", "params": {"blog_id": blog_id, "network": "facebook",
         "init_date": start, "end_date": end, "limit": 10, "timezone": tz},
         "output": f"raw/competitors_fb_{period}.json"},

        # Best time to post
        {"tool": "get_best_time_to_post", "params": {"blog_id": blog_id, "start": start, "end": end,
         "provider": "tiktok", "timezone": tz},
         "output": f"raw/best_time_tk_{period}.json"},

        {"tool": "get_best_time_to_post", "params": {"blog_id": blog_id, "start": start, "end": end,
         "provider": "facebook", "timezone": tz},
         "output": f"raw/best_time_meta_{period}.json"},

        # Metrics available (run once to know what's available)
        {"tool": "get_metrics", "params": {"network": "facebook"}, "output": "raw/metrics_fb.json"},
        {"tool": "get_metrics", "params": {"network": "instagram"}, "output": "raw/metrics_ig.json"},
        {"tool": "get_metrics", "params": {"network": "tiktok"}, "output": "raw/metrics_tk.json"},
    ]
    return calls


# ═══════════════════════════════════════════════
# MAIN: BUILD JSON FROM RAW DATA
# ═══════════════════════════════════════════════

def build_report_json(brand_id, period, raw_dir=None):
    """
    Builds the report JSON from:
    1. Raw Metricool JSONs (saved from MCP calls)
    2. CSV files from data/inputs/BRAND/YYYY-MM/
    3. Calculated fields

    Every field gets a _source annotation.
    Fields that can't be filled → null (NEVER fabricated).
    """
    brand = BRANDS[brand_id]
    start, end = get_period_range(period)
    fx = brand.get("fx_rate", 3.78)

    if raw_dir is None:
        raw_dir = INPUTS_DIR / brand_id / period

    # ── Load CSVs ──
    month_dir = INPUTS_DIR / brand_id / period

    # Current month ads
    meta_ads = {"spend_usd": 0, "impressions": 0, "reach": 0, "clicks": 0, "link_clicks": 0}
    for f in sorted(glob.glob(str(month_dir / "*Campañas*META*.csv")) +
                    glob.glob(str(month_dir / "*Campaña*META*.csv"))):
        data = parse_meta_ads_csv(f)
        meta_ads["spend_usd"] += data["spend_usd"]
        meta_ads["impressions"] += data["impressions"]
        meta_ads["reach"] += data["reach"]
        meta_ads["clicks"] += data["clicks"]
        meta_ads["link_clicks"] += data["link_clicks"]

    tk_ads = {"spend_usd": 0, "impressions": 0}
    for f in sorted(glob.glob(str(month_dir / "*ik*tok*Campaign*.csv")) +
                    glob.glob(str(month_dir / "*ik*tok*Anuncios*.csv")) +
                    glob.glob(str(month_dir / "TIktok*.csv")) +
                    glob.glob(str(month_dir / "Tik tok*.csv"))):
        data = parse_tiktok_ads_csv(f)
        tk_ads["spend_usd"] += data["spend_usd"]
        tk_ads["impressions"] += data["impressions"]

    meta_ads["spend_usd"] = round(meta_ads["spend_usd"], 2)
    tk_ads["spend_usd"] = round(tk_ads["spend_usd"], 2)

    # Comments
    comments = parse_comments_csvs(month_dir)

    # Historical ads
    ads_history = load_ads_history(brand_id, period)

    # ── Build skeleton ──
    total_usd = meta_ads["spend_usd"] + tk_ads["spend_usd"]
    total_soles = round(total_usd * fx, 2)
    meta_soles = round(meta_ads["spend_usd"] * fx, 2)
    tk_soles = round(tk_ads["spend_usd"] * fx, 2)
    meta_pct = round(meta_ads["spend_usd"] / total_usd * 100, 1) if total_usd > 0 else 0
    tk_pct = round(100 - meta_pct, 1)

    report = {
        "brand": brand["name"],
        "brand_id": brand_id,
        "period": period,
        "period_label": None,  # Set by template JS
        "fx_rate": fx,
        "metricool_id": brand["metricool_id"],

        "_data_sources": {
            "meta_ads_csv": [os.path.basename(f) for f in glob.glob(str(month_dir / "*META*.csv"))],
            "tk_ads_csv": [os.path.basename(f) for f in glob.glob(str(month_dir / "*ik*tok*.csv")) + glob.glob(str(month_dir / "TIktok*.csv"))],
            "comments_csv": [os.path.basename(f) for f in glob.glob(str(month_dir / "TTComment*.csv"))],
            "metricool_brand_id": brand["metricool_id"],
            "generated_at": datetime.now().isoformat(),
            "note": "Fields marked null = data not available. NEVER fabricated."
        },

        "portada": {
            "tag": "LUDiK Analytics · Reporte Mensual v2.2",
            "footer": f"Confidencial · Preparado por el equipo LUDiK para {brand['name']}",
            "kpis": [
                {"value": "–", "label": "Alcance Total"},
                {"value": "–", "label": "Nuevos Seguidores"},
                {"value": f"S/ {total_soles:,.0f}", "label": "Inversión"},
                {"value": "–", "label": "Objetivos Cumplidos"},
                {"value": "–", "label": "Brand Health Score"}
            ]
        },

        "cierre": {
            "tagline": "Data-driven decisions for modern brands",
            "team": "Equipo LUDiK",
            "location": "Barcelona · Lima",
            "contact": "hola@ludik.io · ludik.io",
            "confidential": f"Este reporte es confidencial y fue preparado exclusivamente para {brand['name']}"
        },

        "objectives": [],  # MANUAL — set by strategist
        "summary_kpis": {
            "objectives": "–",
            "reach": "–",
            "tk_views": "–",
            "new_followers": "–",
            "investment": f"S/ {total_soles:,.0f}"
        },

        "community": {
            "facebook": {"start": None, "end": None, "delta": None, "delta_pct": None, "_source": "metricool:pageFollows"},
            "instagram": {"start": None, "end": None, "delta": None, "delta_pct": None, "_source": "metricool:followers"},
            "tiktok": {"start": None, "end": None, "delta": None, "delta_pct": None, "_source": "metricool:followers_count"},
            "total_new": None
        },

        "reach": {
            "total_impressions": None,  # calculated after Metricool data
            "estimated_unique_reach": None,
            "frequency": None,
            "meta_ads_impressions": meta_ads["impressions"],
            "meta_ads_reach": meta_ads["reach"],
            "tiktok_ads_impressions": tk_ads["impressions"],
            "tiktok_organic_views": None,  # from Metricool TK videos
            "ig_organic_views": None,  # from Metricool IG reels+posts
            "fb_organic_impressions": None,  # from Metricool FB posts
            "_source": "csv:meta_ads + csv:tk_ads + metricool"
        },

        "engagement": {
            "tiktok_organic": None,  # from Metricool TK videos
            "meta_ads_clicks": meta_ads["clicks"],
            "meta_ads_link_clicks": meta_ads["link_clicks"],
            "meta_ads_post_engagements": None,
            "ig_organic_interactions": None,
            "fb_organic_interactions": None,
            "total_meaningful_interactions": None,
            "_source": "csv:meta_ads + metricool"
        },

        "investment": {
            "meta_ads_usd": meta_ads["spend_usd"],
            "meta_ads_soles": meta_soles,
            "tiktok_ads_usd": tk_ads["spend_usd"],
            "tiktok_ads_soles": tk_soles,
            "total_usd": round(total_usd, 2),
            "total_soles": total_soles,
            "meta_pct": meta_pct,
            "tiktok_pct": tk_pct,
            "_source": "csv:meta_campaigns + csv:tk_campaigns"
        },

        "efficiency": {
            "meta_cpm_usd": calc_cpm(meta_ads["spend_usd"], meta_ads["impressions"]),
            "meta_cpm_soles": calc_cpm(meta_soles, meta_ads["impressions"]),
            "tiktok_cpm_usd": calc_cpm(tk_ads["spend_usd"], tk_ads["impressions"]),
            "tiktok_cpm_soles": calc_cpm(tk_soles, tk_ads["impressions"]),
            "blended_cpm_usd": calc_cpm(total_usd, meta_ads["impressions"] + tk_ads["impressions"]),
            "blended_cpm_soles": calc_cpm(total_soles, meta_ads["impressions"] + tk_ads["impressions"]),
            "_source": "calculated from csv"
        },

        "sentiment": {
            "total": len(comments),
            "positive_pct": None,  # MANUAL or NLP
            "neutral_pct": None,
            "negative_pct": None,
            "net_score": None,
            "categories": [],
            "_source": f"csv:{len(comments)} comments parsed, sentiment=MANUAL",
            "_raw_comments_count": len(comments)
        },

        "bhs": {
            "total": None,
            "benchmark": "70-75",
            "dimensions": {
                "crecimiento": None, "alcance": None, "engagement": None,
                "sentimiento": None, "eficiencia": None, "metas": None, "posicion_comp": None
            },
            "_source": "calculated — requires manual review"
        },

        "competitors_ig": [],  # from Metricool get_network_competitors
        "insights": {
            "community": None, "reach": None, "engagement": None,
            "sentiment": None, "investment": None, "competition": None,
            "_source": "MANUAL — written by strategist or AI"
        },

        "story": {
            "act1": None, "act2": None, "act3": None, "act4": None, "act5": None,
            "_source": "MANUAL — written by strategist or AI"
        },

        "content": {
            "top_tiktok": [],  # from Metricool TK videos (sorted by views)
            "worst_tiktok": [],
            "worst_overall": [],
            "ig_reels": [],
            "total_pieces": {"tiktok": 0, "ig_reels": 0, "ig_posts": 0, "fb_posts": 0, "total": 0}
        },

        "technical_texts": {
            "resumen": None, "audiencia": None, "contenido_insight": None,
            "contenido_fail": None, "contenido_horario": None, "riesgo_fb": None,
            "indice_valor": None, "temas_recurrentes": None, "bhs_explicacion": None,
            "_source": "MANUAL — written by strategist or AI"
        },

        "recommendations": [],

        "charts": {
            "months6": [h["period"] for h in ads_history],
            "community_total": [],  # filled from Metricool
            "fb_followers_labels": [],
            "fb_followers": [],
            "ig_followers": [],
            "tk_followers": [],
            "reach_organic": [None] * 6,
            "reach_paid": [h["total_impressions"] for h in ads_history],
            "reach_mix_labels": [],
            "reach_mix_data": [],
            "fb_reach_weekly": {"total": [], "ads": []},
            "ig_reach_weekly": {"total": [], "ads": []},
            "tk_reach_weekly": {"total": [], "ads": []},
            "er_fb": [None] * 6,
            "er_ig": [None] * 6,
            "er_tk": [None] * 6,
            "tk_top_videos_labels": [],
            "tk_top_videos_data": [],
            "formatos_labels": [],
            "formatos_data": [],
            "meta_days": [],
            "tk_hours": [],
            "sent_categories_data": [],
            "sent_net_score_history": [None] * 6,
            "fb_age": [],
            "ig_age": [],
            "tk_age": [],
            "gender_female": [],
            "gender_male": [],
            "cpm_meta": [calc_cpm(h["meta_spend_usd"], h["meta_impressions"]) for h in ads_history],
            "cpm_tk": [calc_cpm(h["tk_spend_usd"], h["tk_impressions"]) for h in ads_history],
            "budget_labels": [],
            "budget_data": [],
            "comp_followers_labels": [],
            "comp_followers_data": [],
            "comp_er_labels": [],
            "comp_er_data": [],
            "bhs_radar": [],
            "bhs_benchmark": [70, 70, 70, 70, 70, 70, 70],
            "bhs_history": [None] * 6
        }
    }

    return report


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 pull_data.py BRAND_ID YYYY-MM")
        print("     python3 pull_data.py --all YYYY-MM")
        print("     python3 pull_data.py --manifest BRAND_ID YYYY-MM")
        sys.exit(1)

    if sys.argv[1] == "--manifest":
        brand_id = sys.argv[2]
        period = sys.argv[3]
        calls = generate_metricool_manifest(brand_id, period)
        print(json.dumps(calls, indent=2, ensure_ascii=False))
        print(f"\n→ {len(calls)} Metricool API calls needed for {brand_id} {period}")

    elif sys.argv[1] == "--all":
        period = sys.argv[2]
        for brand_id in BRANDS:
            print(f"\n{'='*50}")
            print(f"Processing {brand_id} {period}...")
            report = build_report_json(brand_id, period)
            outfile = DATA_DIR / f"{brand_id}_{period}.json"
            with open(outfile, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"  → {outfile}")
            nulls = sum(1 for k, v in report.items() if v is None)
            print(f"  → {nulls} fields need Metricool data or manual input")

    else:
        brand_id = sys.argv[1]
        period = sys.argv[2]

        if brand_id not in BRANDS:
            print(f"Error: Brand '{brand_id}' not found. Available: {list(BRANDS.keys())}")
            sys.exit(1)

        print(f"Building report for {brand_id} {period}...")
        report = build_report_json(brand_id, period)

        outfile = DATA_DIR / f"{brand_id}_{period}_base.json"
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"✓ Saved: {outfile}")

        # Show what's missing
        def count_nulls(obj, prefix=""):
            count = 0
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k.startswith("_"):
                        continue
                    if v is None:
                        print(f"  ⚠ {prefix}{k}: null — needs Metricool or manual")
                        count += 1
                    elif isinstance(v, (dict, list)):
                        count += count_nulls(v, f"{prefix}{k}.")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    if v is None:
                        count += 1
            return count

        n = count_nulls(report)
        print(f"\n→ {n} fields need data (Metricool API or manual input)")
        print(f"→ Run: python3 pull_data.py --manifest {brand_id} {period}")
        print(f"  to see all Metricool calls needed")

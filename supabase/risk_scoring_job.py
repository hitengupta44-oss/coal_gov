"""
Risk-scoring analytics job -- populates ai_risk_flags.

WHY THIS EXISTS
---------------
frontend/pages/dashboard/corporate.js already calls getHighRiskMines(), and
backend/app.py's get_high_risk_mines() already reads straight from
ai_risk_flags -- that wiring was built already. This script is the missing
piece: the thing that actually computes and writes the flags. Run it once
after seeding (load_seed_data.py + seed_compliance_tracking.py), then on a
schedule (cron / Supabase scheduled function / GitHub Action) to keep it
fresh as new accidents/inspections/compliance data comes in.

    pip install supabase python-dotenv pandas groq --break-system-packages
    python risk_scoring_job.py

FOUR FLAG TYPES (matches the ai_risk_flags.flag_type check constraint)
-----------------------------------------------------------------------
1. Anomalous Accident Rate
   Mines with a fatal-accident count (from the individual, mine-matched
   incidents in coal_dataset_2.xlsx -- the only accident source with real
   mine_id linkage) more than 1 standard deviation above the mean across
   all mines that have at least one recorded fatal accident.
   LIMITATION: most accident sources in this dataset are national/
   subsidiary-level aggregates with no mine_id, so this only sees the ~85
   mines matched from coal_dataset_2.xlsx. Extending mine-level accident
   coverage would directly improve this flag.

2. Recurring Violation
   Mines with 2+ unresolved (Open/Overdue) High or Critical severity
   geo_inspections findings. "Recurring" = more than one, not a one-off.

3. Compliance Gap
   Mines where the overdue share of applicable compliance_tracking items
   exceeds 15%, or there are 3+ overdue items outright.

4. Environmental Threshold Breach
   Mines near a monitored city in air_quality_records that exceeds a CPCB
   NAAQS annual limit (PM10 > 60, PM2.5 > 40, SO2 > 50, NO2 > 40 ug/m3).
   Uses GRADUATED confidence rather than a flat state-wide flag:
     - DISTRICT-LEVEL match (higher confidence, higher risk_score): the
       breaching city's name matches a mine's district exactly (e.g. an
       air-quality station literally named "Dhanbad" matching mines whose
       district is Dhanbad). Only ~17 of 400 monitored cities happen to
       share a name with a mine district, but where they do, this is a
       real geographic link, not a guess.
     - STATE-LEVEL proxy (lower confidence, dampened risk_score): for
       mines in a breaching state whose district didn't get a direct city
       match. Still not mine-specific, but now clearly the fallback tier
       rather than the only tier.
   A mine gets at most one Environmental flag -- district-level match wins
   over state-level if both would apply. LIMITATION: still not true
   mine-to-station geocoding (no lat/long join is done); real coordinate-
   based matching would be a further improvement.

EXPLANATIONS
------------
ai_risk_flags.explanation is commented in schema.sql as "LLM-generated
summary". If GROQ_API_KEY is set, this script asks Groq to turn each mine's
raw stats into a short, readable explanation (model_used='groq'); if not,
it falls back to a deterministic templated sentence built from the same
numbers (model_used='rule-based') so the job still runs end-to-end without
any API key -- useful for local testing or if you haven't set up Groq yet.

RISK SCORE
----------
Each flag type has its own simple, explainable normalization into [0, 1] --
see the `score_*` functions below. These are intentionally simple ratios/
z-scores, not a trained model -- swap in something fancier once you have
enough real (non-synthetic) history to justify it.
"""

import os
import math
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
groq_client = None
if GROQ_API_KEY:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY)

# CPCB National Ambient Air Quality Standards, annual average limits (ug/m3)
NAAQS_ANNUAL_LIMITS = {"pm10_annual_avg": 60, "pm25_annual_avg": 40, "so2_annual_avg": 50, "no2_annual_avg": 40}


def clamp01(x):
    return max(0.0, min(1.0, x))


# ------------------------------------------------------------
# Flag 1: Anomalous Accident Rate
# ------------------------------------------------------------
def compute_accident_rate_flags():
    rows = supabase.table("accidents").select("mine_id, severity, accident_count") \
        .eq("severity", "Fatal").not_.is_("mine_id", "null").execute().data
    if not rows:
        return []
    df = pd.DataFrame(rows)
    per_mine = df.groupby("mine_id")["accident_count"].sum()
    mean, std = per_mine.mean(), per_mine.std(ddof=0)
    if std == 0 or math.isnan(std):
        return []

    flags = []
    for mine_id, count in per_mine.items():
        z = (count - mean) / std
        if z > 1.0:
            flags.append({
                "mine_id": mine_id,
                "flag_type": "Anomalous Accident Rate",
                "risk_score": float(round(clamp01(z / 3), 2)),
                "stats": {"fatal_accident_count": int(count), "mine_mean": float(round(mean, 2)), "z_score": float(round(z, 2))},
            })
    return flags


# ------------------------------------------------------------
# Flag 2: Recurring Violation
# ------------------------------------------------------------
def compute_recurring_violation_flags():
    rows = supabase.table("geo_inspections").select(
        "mine_id, severity, corrective_action_status"
    ).in_("severity", ["High", "Critical"]).in_("corrective_action_status", ["Open", "Overdue"]).execute().data
    if not rows:
        return []
    df = pd.DataFrame(rows)
    per_mine = df.groupby("mine_id").size()

    flags = []
    for mine_id, count in per_mine.items():
        if count >= 2:
            flags.append({
                "mine_id": mine_id,
                "flag_type": "Recurring Violation",
                "risk_score": float(round(clamp01(count / 5), 2)),
                "stats": {"unresolved_high_critical_findings": int(count)},
            })
    return flags


# ------------------------------------------------------------
# Flag 3: Compliance Gap
# ------------------------------------------------------------
def compute_compliance_gap_flags():
    rows = supabase.table("compliance_tracking").select("mine_id, status").execute().data
    if not rows:
        return []
    df = pd.DataFrame(rows)
    grouped = df.groupby("mine_id")["status"].apply(list)

    flags = []
    for mine_id, statuses in grouped.items():
        total = len(statuses)
        overdue = sum(1 for s in statuses if s == "Overdue")
        overdue_ratio = overdue / total if total else 0
        if overdue_ratio > 0.15 or overdue >= 3:
            flags.append({
                "mine_id": mine_id,
                "flag_type": "Compliance Gap",
                "risk_score": float(round(clamp01(overdue_ratio), 2)),
                "stats": {"overdue_items": int(overdue), "total_applicable_items": int(total),
                          "overdue_ratio": round(overdue_ratio, 2)},
            })
    return flags


# ------------------------------------------------------------
# Flag 4: Environmental Threshold Breach (district-level match, state-level fallback)
# ------------------------------------------------------------
def compute_environmental_breach_flags():
    mines = supabase.table("mines").select("mine_id, state, district").execute().data
    aq_rows = supabase.table("air_quality_records").select(
        "state, city_town, so2_annual_avg, no2_annual_avg, pm10_annual_avg, pm25_annual_avg"
    ).execute().data
    if not mines or not aq_rows:
        return []
    aq_df = pd.DataFrame(aq_rows)

    # breaches keyed by state, and separately by (state, city) for district matching
    breaches_by_state = {}
    breaches_by_state_city = {}
    for _, r in aq_df.iterrows():
        for col, limit in NAAQS_ANNUAL_LIMITS.items():
            val = r.get(col)
            if pd.notna(val) and val > limit:
                pollutant = col.replace("_annual_avg", "").upper()
                breaches_by_state.setdefault(r["state"], []).append((r["city_town"], pollutant, val, limit))
                breaches_by_state_city.setdefault((r["state"], str(r["city_town"]).strip().lower()), []).append(
                    (r["city_town"], pollutant, val, limit)
                )

    flags = []
    for mine in mines:
        state, district = mine["state"], mine["district"]
        district_key = (state, str(district).strip().lower()) if district else None
        district_breaches = breaches_by_state_city.get(district_key) if district_key else None

        if district_breaches:
            pollutants = sorted({b[1] for b in district_breaches})
            flags.append({
                "mine_id": mine["mine_id"],
                "flag_type": "Environmental Threshold Breach",
                "risk_score": float(round(clamp01(len(pollutants) / 4 + 0.15), 2)),  # boosted for higher confidence
                "stats": {
                    "match_level": "district",
                    "state": state,
                    "district": district,
                    "pollutants_breached": pollutants,
                    "note": f"air-quality station name matches this mine's district ({district}) directly",
                },
            })
            continue  # district-level match wins; don't also add a state-level flag

        state_breaches = breaches_by_state.get(state)
        if state_breaches:
            pollutants = sorted({b[1] for b in state_breaches})
            flags.append({
                "mine_id": mine["mine_id"],
                "flag_type": "Environmental Threshold Breach",
                "risk_score": float(round(clamp01(len(pollutants) / 4 * 0.7), 2)),  # dampened for lower confidence
                "stats": {
                    "match_level": "state",
                    "state": state,
                    "breaching_cities_sample": [b[0] for b in state_breaches[:3]],
                    "pollutants_breached": pollutants,
                    "note": "state-level proxy -- no monitored city matched this mine's district directly",
                },
            })
    return flags


# ------------------------------------------------------------
# Explanations
# ------------------------------------------------------------
def rule_based_explanation(flag):
    t, s = flag["flag_type"], flag["stats"]
    if t == "Anomalous Accident Rate":
        return (f"This mine recorded {s['fatal_accident_count']} fatal accident(s), "
                f"vs a {s['mine_mean']} average across mines with any recorded fatal accident "
                f"(z-score {s['z_score']}).")
    if t == "Recurring Violation":
        return (f"{s['unresolved_high_critical_findings']} High/Critical-severity field-inspection "
                f"findings remain Open or Overdue at this mine.")
    if t == "Compliance Gap":
        return (f"{s['overdue_items']} of {s['total_applicable_items']} applicable statutory "
                f"compliance items are Overdue ({int(s['overdue_ratio'] * 100)}%).")
    if t == "Environmental Threshold Breach":
        if s.get("match_level") == "district":
            return (f"This mine's district ({s['district']}, {s['state']}) has an air-quality monitoring "
                     f"station exceeding CPCB annual limits for {', '.join(s['pollutants_breached'])}.")
        return (f"{s['state']} has monitored cities (e.g. {', '.join(s['breaching_cities_sample'])}) "
                f"exceeding CPCB annual limits for {', '.join(s['pollutants_breached'])}. "
                f"State-level proxy, not a mine-specific reading.")
    return "Risk flag generated."


def groq_explanation(flag):
    """Best-effort: falls back to the rule-based sentence on any API error,
    so a Groq outage never blocks the job from finishing."""
    if not groq_client:
        return rule_based_explanation(flag), "rule-based"
    try:
        prompt = (
            f"Write ONE concise, plain-English sentence (max 30 words) explaining this coal-mine "
            f"safety/compliance risk flag to a non-technical manager. Flag type: {flag['flag_type']}. "
            f"Raw stats: {flag['stats']}. Do not invent numbers not given above."
        )
        resp = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=80,
        )
        return resp.choices[0].message.content.strip(), "groq"
    except Exception as e:
        print(f"  Groq call failed ({e}), falling back to rule-based explanation")
        return rule_based_explanation(flag), "rule-based"


def main():
    print("Computing risk flags...")
    all_flags = (
        compute_accident_rate_flags()
        + compute_recurring_violation_flags()
        + compute_compliance_gap_flags()
        + compute_environmental_breach_flags()
    )
    print(f"  {len(all_flags)} raw flags computed across all 4 flag types")

    rows = []
    for flag in all_flags:
        explanation, model_used = groq_explanation(flag)
        rows.append({
            "mine_id": flag["mine_id"],
            "flag_type": flag["flag_type"],
            "risk_score": flag["risk_score"],
            "explanation": explanation,
            "model_used": model_used,
            "reviewed": False,
        })

    # Idempotent re-run: clear previous flags before inserting the fresh batch,
    # so scheduling this doesn't pile up stale duplicates over time.
    supabase.table("ai_risk_flags").delete().neq("mine_id", "00000000-0000-0000-0000-000000000000").execute()

    for i in range(0, len(rows), 500):
        supabase.table("ai_risk_flags").insert(rows[i:i + 500]).execute()

    print(f"Inserted {len(rows)} rows into ai_risk_flags "
          f"({'groq' if groq_client else 'rule-based'} explanations)")

    if rows:
        df = pd.DataFrame(rows)
        print(df["flag_type"].value_counts())


if __name__ == "__main__":
    main()

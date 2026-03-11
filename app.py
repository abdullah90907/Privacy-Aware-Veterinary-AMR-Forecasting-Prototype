from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from prophet import Prophet


st.set_page_config(
    page_title="Privacy Aware Veterinary AMR Prototype",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = BASE_DIR / "outputs"
FIGURES_DIR = OUTPUTS_DIR / "figures"
REPORTS_DIR = OUTPUTS_DIR / "reports"
DOCS_DIR = BASE_DIR / "docs"

for folder in [DATA_DIR, RAW_DIR, PROCESSED_DIR, OUTPUTS_DIR, FIGURES_DIR, REPORTS_DIR, DOCS_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


def clean_column_name(col: str) -> str:
    col = str(col).strip().lower()
    col = col.replace("\n", " ")
    col = col.replace("/", "_")
    col = col.replace("(", "")
    col = col.replace(")", "")
    col = col.replace("*", "")
    col = col.replace("%", "percent")
    col = col.replace(".", "")
    col = "_".join(col.split())
    return col


def find_local_dataset() -> Path | None:
    candidates: list[Path] = []
    for search_dir in [BASE_DIR, DATA_DIR, RAW_DIR]:
        if not search_dir.exists():
            continue
        for pattern in ("*.xlsx", "*.xlsm", "*.xls"):
            candidates.extend(search_dir.glob(pattern))

    if not candidates:
        return None

    candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)

    for file_path in candidates:
        suffix = file_path.suffix.lower()
        if suffix in [".xlsx", ".xlsm"] and zipfile.is_zipfile(file_path):
            return file_path
        if suffix == ".xls":
            return file_path

    return None


def save_uploaded_file(uploaded_file) -> Path:
    target_path = RAW_DIR / uploaded_file.name
    with open(target_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return target_path


def get_engine(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in [".xlsx", ".xlsm"]:
        return "openpyxl"
    if suffix == ".xls":
        return "xlrd"
    raise ValueError(f"Unsupported file type: {suffix}")


@st.cache_data(show_spinner=False)
def load_excel(file_path_str: str) -> tuple[pd.DataFrame, str]:
    file_path = Path(file_path_str)
    engine = get_engine(file_path)
    excel_file = pd.ExcelFile(file_path, engine=engine)
    sheet_name = excel_file.sheet_names[0]
    raw_df = pd.read_excel(file_path, sheet_name=sheet_name, engine=engine)
    return raw_df, sheet_name


def ensure_optional_columns(df: pd.DataFrame) -> pd.DataFrame:
    optional_cols = [
        "collection_date",
        "state",
        "lab",
        "collection_source",
        "sign",
        "serotype",
        "zd",
        "drug_code",
        "plate",
        "id",
    ]
    for col in optional_cols:
        if col not in df.columns:
            df[col] = np.nan
    return df


@st.cache_data(show_spinner=False)
def prepare_data(file_path_str: str):
    raw_df, sheet_name = load_excel(file_path_str)

    df = raw_df.copy()
    df.columns = [clean_column_name(c) for c in df.columns]
    df = ensure_optional_columns(df)

    df["collection_date"] = pd.to_datetime(df["collection_date"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["mic"] = pd.to_numeric(df["mic"], errors="coerce")
    df["zd"] = pd.to_numeric(df["zd"], errors="coerce")

    text_columns = [
        "drug_class",
        "drug_code",
        "drug_name",
        "genus",
        "host_species",
        "state",
        "lab",
        "plate",
        "sign",
        "sample_id",
        "collection_source",
        "serotype",
    ]

    for col in text_columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": np.nan, "None": np.nan, "": np.nan})

    required_cols = ["sample_id", "host_species", "genus", "drug_name", "drug_class", "year", "mic"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}")

    df = df[df["mic"].notna()].copy()
    df = df[df["mic"] > 0].copy()
    df = df[df["year"].notna()].copy()

    df["censored_flag"] = df["sign"].isin(["<", "<=", ">", ">="]).astype(int)
    df["mic_log2"] = np.log2(df["mic"])

    isolate_df = (
        df.groupby("sample_id")
        .agg(
            collection_date=("collection_date", "first"),
            year=("year", "first"),
            genus=("genus", "first"),
            host_species=("host_species", "first"),
            state=("state", "first"),
            lab=("lab", "first"),
            collection_source=("collection_source", "first"),
            drug_tests_count=("drug_name", "nunique"),
            median_mic=("mic", "median"),
            mean_mic=("mic", "mean"),
            max_mic=("mic", "max"),
            median_mic_log2=("mic_log2", "median"),
        )
        .reset_index()
    )

    yearly_trend_df = (
        df.groupby(["year", "host_species", "genus", "drug_name", "drug_class"])
        .agg(
            n_records=("mic", "size"),
            n_samples=("sample_id", "nunique"),
            median_mic=("mic", "median"),
            mean_mic=("mic", "mean"),
            median_mic_log2=("mic_log2", "median"),
            mean_mic_log2=("mic_log2", "mean"),
            censored_rate=("censored_flag", "mean"),
        )
        .reset_index()
        .sort_values(["host_species", "genus", "drug_name", "year"])
    )

    ranked_targets = (
        yearly_trend_df.groupby(["host_species", "genus", "drug_name", "drug_class"])
        .agg(
            total_records=("n_records", "sum"),
            years_covered=("year", "nunique"),
            avg_samples_per_year=("n_samples", "mean"),
            min_samples_year=("n_samples", "min"),
            mean_mic_variability=("mean_mic_log2", "std"),
            median_mic_variability=("median_mic_log2", "std"),
        )
        .reset_index()
    )

    ranked_targets["mean_mic_variability"] = ranked_targets["mean_mic_variability"].fillna(0)
    ranked_targets["median_mic_variability"] = ranked_targets["median_mic_variability"].fillna(0)

    meta = {
        "sheet_name": sheet_name,
        "raw_shape": raw_df.shape,
        "cleaned_shape": df.shape,
        "isolate_shape": isolate_df.shape,
        "trend_shape": yearly_trend_df.shape,
        "unique_hosts": int(df["host_species"].nunique()),
        "unique_genera": int(df["genus"].nunique()),
        "unique_drugs": int(df["drug_name"].nunique()),
        "year_min": int(df["year"].min()),
        "year_max": int(df["year"].max()),
    }

    return raw_df, df, isolate_df, yearly_trend_df, ranked_targets, meta


def filter_targets(
    ranked_targets: pd.DataFrame,
    min_years: int,
    min_avg_samples: int,
    min_min_samples: int,
) -> pd.DataFrame:
    filtered_targets = ranked_targets[
        (ranked_targets["years_covered"] >= min_years)
        & (ranked_targets["avg_samples_per_year"] >= min_avg_samples)
        & (ranked_targets["min_samples_year"] >= min_min_samples)
        & (ranked_targets["mean_mic_variability"] > 0)
    ].copy()

    filtered_targets = filtered_targets.sort_values(
        ["years_covered", "avg_samples_per_year", "min_samples_year", "mean_mic_variability", "total_records"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)

    return filtered_targets


def build_target_series(
    yearly_trend_df: pd.DataFrame,
    host_species: str,
    genus: str,
    drug_name: str,
    drug_class: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_df = yearly_trend_df[
        (yearly_trend_df["host_species"] == host_species)
        & (yearly_trend_df["genus"] == genus)
        & (yearly_trend_df["drug_name"] == drug_name)
        & (yearly_trend_df["drug_class"] == drug_class)
    ].copy().sort_values("year")

    prophet_df = target_df[["year", "mean_mic_log2", "n_samples"]].copy()
    prophet_df["ds"] = pd.to_datetime(prophet_df["year"].astype(int).astype(str) + "/01/01")
    prophet_df["y"] = prophet_df["mean_mic_log2"]
    prophet_df = prophet_df[["ds", "y", "n_samples"]].dropna().sort_values("ds")
    return target_df, prophet_df


@st.cache_data(show_spinner=False)
def run_prophet_from_records(records: list[dict]) -> tuple[pd.DataFrame, dict]:
    prophet_df = pd.DataFrame(records).copy()
    prophet_df["ds"] = pd.to_datetime(prophet_df["ds"])

    model = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.8,
    )
    model.fit(prophet_df[["ds", "y"]])

    future = model.make_future_dataframe(periods=2, freq="YS")
    forecast = model.predict(future)

    years_used = int(prophet_df.shape[0])
    avg_samples = float(prophet_df["n_samples"].mean())
    variability = float(prophet_df["y"].std()) if years_used > 1 else 0.0

    if years_used >= 8 and avg_samples >= 20 and variability > 0:
        confidence_label = "Higher confidence for a small research prototype"
    elif years_used >= 6 and avg_samples >= 10:
        confidence_label = "Moderate confidence, interpret with care"
    else:
        confidence_label = "Limited confidence due to sparse historical data"

    summary = {
        "years_used": years_used,
        "average_samples_per_year": avg_samples,
        "observed_variability": variability,
        "confidence_label": confidence_label,
    }

    return forecast, summary


def build_project_brief(
    host_species: str,
    genus: str,
    drug_name: str,
    drug_class: str,
    forecast_summary: dict,
) -> str:
    return f"""# Privacy Aware Veterinary AMR Forecasting Prototype

## Project motivation
This prototype was developed as a compact research aligned system inspired by privacy aware AMR decision support for rural and regional veterinary practice.

## What it demonstrates
1. Cleaning and structuring real public veterinary AMR records
2. Building surveillance style analytics for host species, bacterial genera, and yearly isolate activity
3. Constructing yearly host, pathogen, and drug trend tables
4. Forecasting a meaningful AMR related MIC trend with uncertainty intervals
5. Creating a traceable recipient specific export package for privacy aware sharing

## Current selected target
Host species: {host_species}

Genus: {genus}

Drug name: {drug_name}

Drug class: {drug_class}

## Why this aligns with Professor Ji's paper
This prototype reflects three important directions:
1. practical AMR decision support using real surveillance data
2. careful use of prediction with explicit uncertainty
3. privacy aware sharing through traceable reporting

## Why this shows strong fit
It shows the ability to move from raw domain data to usable analytics, forecasting, and privacy minded reporting in one workflow.

## Forecast confidence
{forecast_summary["confidence_label"]}

## Limitations
1. It uses public data rather than the private Texas dataset from the paper
2. It is a research style prototype, not a clinical tool
3. The privacy layer is lightweight and demonstrative, not a full secure deployment system
"""


def build_traceable_report(
    host_species: str,
    genus: str,
    drug_name: str,
    drug_class: str,
    forecast_summary: dict,
) -> tuple[dict, str]:
    recipient_name = "Professor Tianxi Ji"
    recipient_tag = recipient_name.lower().replace(" ", "_")
    report_id = uuid.uuid4().hex[:12]
    generated_at = datetime.now(timezone.utc).strftime("%Y_%m_%d__%H_%M_%S")

    report_json = {
        "project_title": "Privacy Aware Veterinary AMR Forecasting Prototype",
        "recipient": recipient_name,
        "recipient_tag": recipient_tag,
        "report_id": report_id,
        "generated_at_utc": generated_at,
        "selected_target": {
            "host_species": host_species,
            "genus": genus,
            "drug_name": drug_name,
            "drug_class": drug_class,
        },
        "forecast_summary": forecast_summary,
        "alignment_note": "Prototype inspired by privacy aware AMR dashboard research for rural and regional veterinary decision support.",
        "privacy_note": "This export contains a recipient specific tag and report ID for traceable sharing in a prototype setting.",
    }

    report_txt = f"""Privacy Aware Veterinary AMR Forecasting Prototype

Recipient: {recipient_name}
Recipient tag: {recipient_tag}
Report ID: {report_id}
Generated at UTC: {generated_at}

Selected target
Host species: {host_species}
Genus: {genus}
Drug name: {drug_name}
Drug class: {drug_class}

Confidence label
{forecast_summary["confidence_label"]}

What this shows
This prototype performs public veterinary AMR data cleaning, surveillance analysis, informative trend forecasting, uncertainty display, and traceable export generation.

Why it fits the paper
The project reflects practical AMR decision support, caution around prediction, and privacy aware sharing.
"""
    return report_json, report_txt


def save_outputs(
    df: pd.DataFrame,
    isolate_df: pd.DataFrame,
    yearly_trend_df: pd.DataFrame,
    ranked_targets: pd.DataFrame,
    target_df: pd.DataFrame,
    prophet_df: pd.DataFrame,
    forecast: pd.DataFrame,
    project_brief: str,
    report_json: dict,
    report_txt: str,
    meta: dict,
    selected_target: dict,
    forecast_summary: dict,
) -> None:
    df.to_csv(PROCESSED_DIR / "master_cleaned_amr_data.csv", index=False)
    isolate_df.to_csv(PROCESSED_DIR / "isolate_level_summary.csv", index=False)
    yearly_trend_df.to_csv(PROCESSED_DIR / "yearly_drug_trends.csv", index=False)
    ranked_targets.to_csv(PROCESSED_DIR / "ranked_targets.csv", index=False)
    target_df.to_csv(PROCESSED_DIR / "selected_target_series_full.csv", index=False)
    prophet_df.to_csv(PROCESSED_DIR / "selected_target_series.csv", index=False)
    forecast[["ds", "yhat", "yhat_lower", "yhat_upper", "trend"]].to_csv(
        PROCESSED_DIR / "final_demo_forecast.csv", index=False
    )

    with open(DOCS_DIR / "project_brief_for_professor.md", "w", encoding="utf_8") as f:
        f.write(project_brief)

    with open(REPORTS_DIR / "traceable_report_professor_tianxi_ji.json", "w", encoding="utf_8") as f:
        json.dump(report_json, f, indent=4)

    with open(REPORTS_DIR / "traceable_report_professor_tianxi_ji.txt", "w", encoding="utf_8") as f:
        f.write(report_txt)

    summary = {
        "meta": meta,
        "selected_target": selected_target,
        "forecast_summary": forecast_summary,
    }
    with open(DOCS_DIR / "dataset_summary.json", "w", encoding="utf_8") as f:
        json.dump(summary, f, indent=4)


def narrative_summary(meta: dict, selected_target: dict, forecast_summary: dict) -> str:
    return (
        f"This prototype processed {meta['cleaned_shape'][0]:,} valid AMR test records spanning "
        f"{meta['year_min']} to {meta['year_max']}. It identified {meta['unique_hosts']} host groups, "
        f"{meta['unique_genera']} bacterial genera, and {meta['unique_drugs']} drugs. "
        f"The selected demonstration target is {selected_target['host_species']} with "
        f"{selected_target['genus']} for {selected_target['drug_name']} in the "
        f"{selected_target['drug_class']} class. This target covers "
        f"{selected_target['years_covered']} years, averages "
        f"{selected_target['avg_samples_per_year']:.1f} samples per year, and has an observed mean log2 MIC variability of "
        f"{selected_target['mean_mic_variability']:.3f}. The forecast confidence is "
        f"'{forecast_summary['confidence_label']}'."
    )


def make_host_chart(isolate_df: pd.DataFrame):
    host_counts = isolate_df["host_species"].value_counts().head(15).reset_index()
    host_counts.columns = ["host_species", "count"]
    return px.bar(
        host_counts,
        x="host_species",
        y="count",
        title="Top host species by isolate count",
        text="count",
    )


def make_genus_chart(isolate_df: pd.DataFrame):
    genus_counts = isolate_df["genus"].value_counts().head(15).reset_index()
    genus_counts.columns = ["genus", "count"]
    return px.bar(
        genus_counts,
        x="genus",
        y="count",
        title="Top bacterial genera by isolate count",
        text="count",
    )


def make_year_chart(isolate_df: pd.DataFrame):
    year_counts = isolate_df.groupby("year").size().reset_index(name="count").sort_values("year")
    return px.line(
        year_counts,
        x="year",
        y="count",
        markers=True,
        title="Yearly isolate activity",
    )


def make_heatmap(df: pd.DataFrame, isolate_df: pd.DataFrame):
    top_genera = isolate_df["genus"].value_counts().head(10).index.tolist()
    heatmap_df = (
        df[df["genus"].isin(top_genera)]
        .groupby(["genus", "drug_class"])
        .agg(median_mic_log2=("mic_log2", "median"))
        .reset_index()
    )
    return px.density_heatmap(
        heatmap_df,
        x="drug_class",
        y="genus",
        z="median_mic_log2",
        histfunc="avg",
        color_continuous_scale="Viridis",
        title="Median log2 MIC by genus and drug class",
    )


def make_forecast_chart(prophet_df: pd.DataFrame, forecast: pd.DataFrame, title: str):
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=prophet_df["ds"],
            y=prophet_df["y"],
            mode="lines+markers",
            name="Observed mean log2 MIC",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["ds"],
            y=forecast["yhat"],
            mode="lines",
            name="Forecasted mean log2 MIC",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=list(forecast["ds"]) + list(forecast["ds"])[::-1],
            y=list(forecast["yhat_upper"]) + list(forecast["yhat_lower"])[::-1],
            fill="toself",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip",
            name="Uncertainty interval",
        )
    )
    fig.update_layout(title=title, xaxis_title="Year", yaxis_title="Mean log2 MIC")
    return fig


st.title("Privacy Aware Veterinary AMR Forecasting Prototype")
st.caption(
    "Automatic end to end analysis of veterinary AMR data with surveillance views, target selection, "
    "uncertainty aware forecasting, and traceable export."
)

with st.sidebar:
    st.header("Dataset")
    uploaded_file = st.file_uploader("Upload workbook", type=["xlsx", "xlsm", "xls"])

    if uploaded_file is not None:
        dataset_path = save_uploaded_file(uploaded_file)
    else:
        dataset_path = find_local_dataset()

    if dataset_path is None:
        st.error("Upload the workbook or place it in the project folder.")
        st.stop()

    st.success(f"Using dataset: {dataset_path.name}")

    st.header("Target filters")
    min_years = st.slider("Minimum years covered", min_value=3, max_value=8, value=6)
    min_avg_samples = st.slider("Minimum average samples per year", min_value=1, max_value=50, value=10)
    min_min_samples = st.slider("Minimum smallest yearly sample count", min_value=1, max_value=20, value=3)

try:
    raw_df, df, isolate_df, yearly_trend_df, ranked_targets, meta = prepare_data(str(dataset_path))
except Exception as e:
    st.error(f"Failed to read dataset: {e}")
    st.stop()

filtered_targets = filter_targets(ranked_targets, min_years, min_avg_samples, min_min_samples)

if filtered_targets.empty:
    st.warning("No targets match the current filters. Lower the thresholds in the sidebar.")
    st.stop()

filtered_targets["label"] = (
    filtered_targets["host_species"].astype(str)
    + " | "
    + filtered_targets["genus"].astype(str)
    + " | "
    + filtered_targets["drug_name"].astype(str)
    + " | years="
    + filtered_targets["years_covered"].astype(str)
    + " | avg_samples="
    + filtered_targets["avg_samples_per_year"].round(1).astype(str)
)

selected_label = st.selectbox("Selected forecasting target", filtered_targets["label"].tolist(), index=0)
selected_row = filtered_targets[filtered_targets["label"] == selected_label].iloc[0]

selected_target = {
    "host_species": str(selected_row["host_species"]),
    "genus": str(selected_row["genus"]),
    "drug_name": str(selected_row["drug_name"]),
    "drug_class": str(selected_row["drug_class"]),
    "years_covered": int(selected_row["years_covered"]),
    "avg_samples_per_year": float(selected_row["avg_samples_per_year"]),
    "min_samples_year": float(selected_row["min_samples_year"]),
    "mean_mic_variability": float(selected_row["mean_mic_variability"]),
    "total_records": int(selected_row["total_records"]),
}

target_df, prophet_df = build_target_series(
    yearly_trend_df=yearly_trend_df,
    host_species=selected_target["host_species"],
    genus=selected_target["genus"],
    drug_name=selected_target["drug_name"],
    drug_class=selected_target["drug_class"],
)

forecast, forecast_summary = run_prophet_from_records(prophet_df.to_dict("records"))

project_brief = build_project_brief(
    host_species=selected_target["host_species"],
    genus=selected_target["genus"],
    drug_name=selected_target["drug_name"],
    drug_class=selected_target["drug_class"],
    forecast_summary=forecast_summary,
)

report_json, report_txt = build_traceable_report(
    host_species=selected_target["host_species"],
    genus=selected_target["genus"],
    drug_name=selected_target["drug_name"],
    drug_class=selected_target["drug_class"],
    forecast_summary=forecast_summary,
)

save_outputs(
    df=df,
    isolate_df=isolate_df,
    yearly_trend_df=yearly_trend_df,
    ranked_targets=filtered_targets,
    target_df=target_df,
    prophet_df=prophet_df,
    forecast=forecast,
    project_brief=project_brief,
    report_json=report_json,
    report_txt=report_txt,
    meta=meta,
    selected_target=selected_target,
    forecast_summary=forecast_summary,
)

summary_text = narrative_summary(meta, selected_target, forecast_summary)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Valid AMR records", f"{meta['cleaned_shape'][0]:,}")
m2.metric("Unique hosts", meta["unique_hosts"])
m3.metric("Unique genera", meta["unique_genera"])
m4.metric("Unique drugs", meta["unique_drugs"])

m5, m6, m7, m8 = st.columns(4)
m5.metric("Years covered", f"{meta['year_min']} to {meta['year_max']}")
m6.metric("Selected target years", selected_target["years_covered"])
m7.metric("Avg samples per year", f"{selected_target['avg_samples_per_year']:.1f}")
m8.metric("Forecast confidence", forecast_summary["confidence_label"])

st.markdown("### Prototype summary")
st.info(summary_text)

overview_tab, surveillance_tab, forecast_tab, analysis_tab, export_tab = st.tabs(
    ["Overview", "Surveillance", "Forecasting", "Interpretation", "Export"]
)

with overview_tab:
    st.markdown("### Dataset profile")
    st.json(
        {
            "dataset_file": dataset_path.name,
            "sheet_used": meta["sheet_name"],
            "raw_shape": meta["raw_shape"],
            "cleaned_shape": meta["cleaned_shape"],
            "isolate_shape": meta["isolate_shape"],
            "trend_shape": meta["trend_shape"],
        }
    )

    st.markdown("### Selected target")
    st.json(selected_target)

    st.markdown("### Top ranked targets")
    st.dataframe(
        filtered_targets[
            [
                "host_species",
                "genus",
                "drug_name",
                "drug_class",
                "years_covered",
                "avg_samples_per_year",
                "min_samples_year",
                "mean_mic_variability",
                "total_records",
            ]
        ].head(20),
        use_container_width=True,
    )

    st.markdown("### Raw preview")
    st.dataframe(raw_df.head(10), use_container_width=True)

with surveillance_tab:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(make_host_chart(isolate_df), use_container_width=True)
    with c2:
        st.plotly_chart(make_genus_chart(isolate_df), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(make_year_chart(isolate_df), use_container_width=True)
    with c4:
        st.plotly_chart(make_heatmap(df, isolate_df), use_container_width=True)

    with st.expander("What these surveillance outputs show", expanded=True):
        st.write(
            "The host and genus charts show where the dataset is concentrated. "
            "The yearly isolate activity plot shows how much data is available over time. "
            "The heatmap highlights genus and drug class combinations with higher or lower median log2 MIC values, "
            "which helps identify meaningful patterns before forecasting."
        )

with forecast_tab:
    st.markdown("### Target series used for forecasting")
    st.dataframe(prophet_df, use_container_width=True)

    st.markdown("### Forecast output")
    st.plotly_chart(
        make_forecast_chart(
            prophet_df,
            forecast,
            f"AMR Forecast | {selected_target['host_species']} | {selected_target['genus']} | {selected_target['drug_name']}",
        ),
        use_container_width=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Observed variability", f"{forecast_summary['observed_variability']:.3f}")
    c2.metric("Years used", forecast_summary["years_used"])
    c3.metric("Avg samples", f"{forecast_summary['average_samples_per_year']:.1f}")

    st.markdown("### Forecast values")
    st.dataframe(
        forecast[["ds", "yhat", "yhat_lower", "yhat_upper", "trend"]].tail(8),
        use_container_width=True,
    )

with analysis_tab:
    st.markdown("### Interpretation")
    st.write(
        f"The selected target combines {selected_target['host_species']}, "
        f"{selected_target['genus']}, and {selected_target['drug_name']}. "
        f"It covers {selected_target['years_covered']} years and has "
        f"{selected_target['total_records']} total records. "
        f"The average yearly sample support is {selected_target['avg_samples_per_year']:.1f}, "
        f"and the smallest yearly support is {selected_target['min_samples_year']:.0f}. "
        f"The observed mean log2 MIC variability is {selected_target['mean_mic_variability']:.3f}, "
        f"which is why it is more informative than a flat series."
    )

    st.write(
        f"The forecast confidence is currently '{forecast_summary['confidence_label']}'. "
        "This means the prototype is useful for demonstrating trend aware and uncertainty aware AMR analytics, "
        "but it should still be described as a research style prototype rather than a clinical system."
    )

    st.markdown("### Professor aligned project brief")
    st.markdown(project_brief)

    st.markdown("### Email ready project paragraph")
    email_paragraph = (
        "Inspired by your work on privacy aware AMR decision support for rural and regional veterinary practice, "
        "I developed a Streamlit based prototype using public veterinary AMR data. "
        "The current version performs data cleaning, surveillance style visualization, yearly host, pathogen, and drug trend construction, "
        "uncertainty aware forecasting of MIC trends, and a traceable export layer for privacy minded sharing. "
        "Through this prototype, I wanted to better understand how useful AMR analytics can be designed while keeping responsible data handling inside the workflow."
    )
    st.code(email_paragraph)

with export_tab:
    st.markdown("### Download project brief")
    st.download_button(
        label="Download project brief markdown",
        data=project_brief,
        file_name="project_brief_for_professor.md",
        mime="text/markdown",
        use_container_width=True,
    )

    st.markdown("### Download traceable report")
    st.download_button(
        label="Download report JSON",
        data=json.dumps(report_json, indent=4),
        file_name="traceable_report_professor_tianxi_ji.json",
        mime="application/json",
        use_container_width=True,
    )

    st.download_button(
        label="Download report TXT",
        data=report_txt,
        file_name="traceable_report_professor_tianxi_ji.txt",
        mime="text/plain",
        use_container_width=True,
    )

    st.markdown("### Download CSV outputs")
    csv_bundle = {
        "master_cleaned_amr_data.csv": df.to_csv(index=False),
        "isolate_level_summary.csv": isolate_df.to_csv(index=False),
        "yearly_drug_trends.csv": yearly_trend_df.to_csv(index=False),
        "ranked_targets.csv": filtered_targets.to_csv(index=False),
        "selected_target_series.csv": prophet_df.to_csv(index=False),
        "forecast_output.csv": forecast[["ds", "yhat", "yhat_lower", "yhat_upper", "trend"]].to_csv(index=False),
    }
    csv_name = st.selectbox("Choose CSV output", list(csv_bundle.keys()))
    st.download_button(
        label="Download selected CSV",
        data=csv_bundle[csv_name],
        file_name=csv_name,
        mime="text/csv",
        use_container_width=True,
    )
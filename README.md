# Privacy Aware Veterinary AMR Forecasting Prototype

## Overview
This project is a compact research aligned prototype inspired by work on privacy aware antimicrobial resistance decision support for rural and regional veterinary practice. It uses public veterinary AMR data to combine surveillance analytics, trend forecasting, uncertainty display, and traceable export in one clean workflow.

## Why this project is strong for professor outreach
This prototype is designed to demonstrate four things clearly:

1. You can work with real domain data rather than toy examples.
2. You understand that decision support systems need both predictive value and visible caution around uncertainty.
3. You can keep privacy inside the workflow instead of treating it as a final add on.
4. You can package a research aligned idea into a reproducible project that is easy for a professor to inspect.

## What the script does
The Python script:

1. Loads the Vet LIRN AMR Excel workbook.
2. Cleans and standardizes the data.
3. Builds isolate level and yearly trend tables.
4. Creates surveillance figures for host species, bacterial genera, yearly activity, and genus by drug class MIC patterns.
5. Selects an informative host, pathogen, drug target for forecasting.
6. Forecasts the selected AMR trend with Prophet.
7. Saves a forecast figure with uncertainty intervals.
8. Generates a professor facing project brief.
9. Generates a traceable report package with a recipient specific tag and report ID.

## Project structure
```text
amr_privacy_prototype/
├── app.py
├── requirements.txt
└── README.md
```

When you run the script, it creates a structured output folder like this:

```text
results/
├── data/
│   ├── raw/
│   └── processed/
├── docs/
└── outputs/
    ├── figures/
    └── reports/
```

## Input data
This project expects the FDA Vet LIRN AMR workbook as input. It uses public veterinary AMR data rather than the private Texas dataset used in the original paper. The goal is not to reproduce the paper exactly. The goal is to build a compact prototype that reflects its core ideas.

## Installation
Create a virtual environment in VS Code, then install the requirements:

```bash
pip install -r requirements.txt
```

## How to run
Basic usage:

```bash
python app.py --excel path/to/updated_vetlirn-amr-database-2017-2024.xlsx --output-dir results
```

Recommended professor aligned run:

```bash
python app.py \
  --excel path/to/updated_vetlirn-amr-database-2017-2024.xlsx \
  --output-dir results \
  --recipient "Professor Tianxi Ji" \
  --forecast-years 2 \
  --min-years 5 \
  --min-avg-samples 10 \
  --min-coverage-ratio 0.60
```

## Main outputs
After a successful run, the project saves:

1. `master_cleaned_amr_data.csv`
2. `isolate_level_summary.csv`
3. `yearly_drug_trends.csv`
4. `ranked_demo_targets.csv`
5. `final_demo_forecast.csv`
6. surveillance figures in `outputs/figures/`
7. a professor facing brief in `docs/project_brief_for_professor.md`
8. a traceable report package in `outputs/reports/`

## What to present to a professor
Present this as a compact, thoughtful prototype, not as a full reproduction of the paper.

A good summary is:

> I built a compact privacy aware veterinary AMR forecasting prototype inspired by your paper. Using public veterinary AMR data, the system performs data cleaning, surveillance visualization, yearly host, pathogen, and drug trend construction, uncertainty aware forecasting, and traceable export for privacy minded sharing.

## Why the alignment is credible
This prototype aligns with three important ideas:

1. practical AMR decision support built on real surveillance data
2. careful use of prediction with explicit uncertainty
3. privacy aware reporting and sharing

## Limitations
1. This is a research style prototype, not a clinical tool.
2. It uses public data instead of the private Texas dataset from the original work.
3. The privacy layer is lightweight and demonstrative, not a full secure deployment system.
4. Forecast quality depends on the historical coverage and yearly sample counts of the selected target.

## Suggested next improvements
1. stronger target selection using stricter minimum yearly sample thresholds
2. richer uncertainty estimation and backtesting
3. more advanced privacy preserving export methods
4. optional interactive interface after the core pipeline is stable

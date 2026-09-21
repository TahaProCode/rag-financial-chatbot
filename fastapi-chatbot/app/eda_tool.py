"""
eda_tool.py
------------
A LangChain @tool that performs automated Exploratory Data Analysis (EDA)
on an uploaded Excel/CSV file using pandas, with a local Ollama model
(qwen2.5:7b) writing targeted follow-up analysis code and a short
narrative summary.

Drop this file next to your existing `tools.py`, then:

    from .eda_tool import eda_analysis_tool
    TOOLS = [..., eda_analysis_tool]

and mention it in your AGENT_SYSTEM_PROMPT (see bottom of this file for
the exact text to add).
"""

import os
import io
import re
import json
import contextlib
import traceback

import numpy as np
import pandas as pd
from langchain_core.tools import tool
from langchain_ollama import ChatOllama


# Config

OLLAMA_MODEL = "qwen2.5:7b"
MAX_ROWS_FOR_PREVIEW = 5
MAX_CATEGORICAL_VALUES = 5
MAX_GENERATED_CODE_CHARS = 3000

_eda_llm = ChatOllama(model=OLLAMA_MODEL, temperature=0)

# Tokens we never allow in LLM-generated exploration code, since it runs
# through exec(). This is a blunt filter on top of a restricted builtins
# dict — belt and suspenders, not a full sandbox.
_BANNED_TOKENS = [
    "import os", "import sys", "import subprocess", "import shutil",
    "open(", "eval(", "exec(", "__import__", "compile(",
    "globals(", "locals(", "input(", "os.", "sys.", "subprocess.",
    "shutil.", "socket", "requests", "urllib", "pathlib", "pickle",
    "__class__", "__bases__", "__subclasses__", "__globals__",
]

_ALLOWED_BUILTINS = {
    "len": len, "range": range, "enumerate": enumerate, "list": list,
    "dict": dict, "set": set, "tuple": tuple, "sorted": sorted,
    "sum": sum, "min": min, "max": max, "abs": abs, "round": round,
    "zip": zip, "map": map, "filter": filter, "str": str, "int": int,
    "float": float, "bool": bool, "print": print, "isinstance": isinstance,
    "True": True, "False": False, "None": None,
}


# ---------------------------------------------------------------------------
# Step 1: Load file
# ---------------------------------------------------------------------------

def _load_dataframe(file_path: str) -> pd.DataFrame:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found on disk: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        df = pd.read_excel(file_path)
    elif ext == ".csv":
        df = pd.read_csv(file_path)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. Only .xlsx, .xls, .xlsm and .csv are supported."
        )

    if df.empty:
        raise ValueError("The uploaded file loaded successfully but contains no rows.")
    return df


# Step 2: Deterministic profiling (no LLM, always correct)

def _safe_describe(df: pd.DataFrame) -> dict:
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.empty:
        return {}
    desc = numeric_df.describe().round(2)
    return desc.to_dict()


def _detect_outliers_iqr(df: pd.DataFrame) -> dict:
    outliers = {}
    numeric_df = df.select_dtypes(include=[np.number])
    for col in numeric_df.columns:
        series = numeric_df[col].dropna()
        if series.empty:
            continue
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        count = int(((series < lower) | (series > upper)).sum())
        if count > 0:
            outliers[col] = count
    return outliers


def _top_correlations(df: pd.DataFrame, top_n: int = 5) -> list:
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.shape[1] < 2:
        return []
    corr = numeric_df.corr(numeric_only=True).abs()
    pairs = []
    cols = corr.columns
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            val = corr.iloc[i, j]
            if pd.notna(val):
                pairs.append((cols[i], cols[j], round(float(val), 3)))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs[:top_n]


def _build_profile(df: pd.DataFrame) -> dict:
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category", "bool"]).columns.tolist()
    datetime_cols = df.select_dtypes(include=["datetime64[ns]"]).columns.tolist()

    categorical_summary = {}
    for col in categorical_cols[:10]:  # cap to avoid huge prompts/reports
        vc = df[col].value_counts(dropna=True).head(MAX_CATEGORICAL_VALUES)
        categorical_summary[col] = vc.to_dict()

    profile = {
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "columns": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
        "datetime_cols": datetime_cols,
        "missing_counts": {c: int(v) for c, v in df.isnull().sum().items() if v > 0},
        "missing_pct": {
            c: round(float(v), 2)
            for c, v in (df.isnull().mean() * 100).items()
            if v > 0
        },
        "duplicate_rows": int(df.duplicated().sum()),
        "numeric_summary": _safe_describe(df),
        "categorical_summary": categorical_summary,
        "outliers_iqr": _detect_outliers_iqr(df),
        "top_correlations": _top_correlations(df),
        "sample_rows": df.head(MAX_ROWS_FOR_PREVIEW).astype(str).to_dict(orient="records"),
    }
    return profile


# ---------------------------------------------------------------------------
# Step 3: LLM writes targeted follow-up pandas code
# ---------------------------------------------------------------------------

_CODE_GEN_SYSTEM = """You are a senior data analyst writing pandas code.

You are given a JSON profile describing a dataframe already loaded as `df`.
Write a SHORT pandas snippet (max 15 lines) that computes 2-4 additional,
NON-OBVIOUS insights not already covered by basic describe()/value_counts()
— for example: a meaningful groupby aggregation, a trend by a date column,
a ratio between two numeric columns, or the row(s) representing extremes.

STRICT RULES:
- Only use `df`, `pd`, and `np` — nothing else is available.
- Do NOT import anything, do NOT read/write files, do NOT use os/sys/eval/exec/open.
- Store every result you want reported into a dict called `output`,
  e.g. output["avg_by_category"] = df.groupby("category")["value"].mean().round(2).to_dict()
- Keep values in `output` JSON-serializable (dict, list, str, int, float).
- Return ONLY the raw Python code. No markdown fences, no explanation, no comments.
- If the dataframe genuinely has nothing more interesting to compute, return exactly: pass
"""


def _generate_eda_code(profile: dict) -> str:
    trimmed_profile = {
        "columns": profile["columns"],
        "dtypes": profile["dtypes"],
        "numeric_cols": profile["numeric_cols"],
        "categorical_cols": profile["categorical_cols"],
        "datetime_cols": profile["datetime_cols"],
        "n_rows": profile["n_rows"],
        "sample_rows": profile["sample_rows"][:3],
    }
    messages = [
        ("system", _CODE_GEN_SYSTEM),
        ("user", f"Dataframe profile:\n{json.dumps(trimmed_profile, default=str)}"),
    ]
    response = _eda_llm.invoke(messages)
    code = response.content.strip()

    # Strip markdown fences if the model added them anyway
    code = re.sub(r"^```(?:python)?\s*", "", code)
    code = re.sub(r"\s*```$", "", code)
    return code[:MAX_GENERATED_CODE_CHARS].strip()


def _code_is_safe(code: str) -> bool:
    lowered = code.lower()
    return not any(token in lowered for token in _BANNED_TOKENS)


def _run_generated_code(code: str, df: pd.DataFrame) -> dict:
    if not code or code.strip() == "pass":
        return {"success": True, "output": {}, "stdout": ""}

    if not _code_is_safe(code):
        return {"success": False, "error": "Generated code failed the safety filter and was not run."}

    local_vars = {"df": df, "pd": pd, "np": np, "output": {}}
    stdout_buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buffer):
            exec(compile(code, "<eda_generated_code>", "exec"), {"__builtins__": _ALLOWED_BUILTINS}, local_vars)
        # make sure whatever landed in `output` is actually JSON-safe
        json.dumps(local_vars.get("output", {}), default=str)
        return {
            "success": True,
            "output": local_vars.get("output", {}),
            "stdout": stdout_buffer.getvalue().strip(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(limit=2),
        }


# ---------------------------------------------------------------------------
# Step 4: LLM narrative summary — grounded strictly in computed numbers
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = """You are a data analyst summarizing an EDA report for a
business user. You will be given ONLY computed statistics (never raw data).
Write a crisp 4-6 sentence narrative: what the dataset looks like, the most
notable pattern or risk (missing data, outliers, correlation, skew), and one
suggested next step. Do NOT invent any number that isn't in the provided
JSON. Plain prose, no headers, no bullet points."""


def _generate_narrative(profile: dict, extra_insights: dict) -> str:
    payload = {
        "n_rows": profile["n_rows"],
        "n_cols": profile["n_cols"],
        "missing_pct": profile["missing_pct"],
        "duplicate_rows": profile["duplicate_rows"],
        "outliers_iqr": profile["outliers_iqr"],
        "top_correlations": profile["top_correlations"],
        "extra_insights": extra_insights,
    }
    try:
        messages = [
            ("system", _SUMMARY_SYSTEM),
            ("user", json.dumps(payload, default=str)),
        ]
        response = _eda_llm.invoke(messages)
        return response.content.strip()
    except Exception:
        return "Narrative summary unavailable (model call failed); see the statistics above."


# ---------------------------------------------------------------------------
# Step 5: Assemble a polished markdown report
# ---------------------------------------------------------------------------

def _fmt_table(d: dict, key_label: str, val_label: str) -> str:
    if not d:
        return "_None_"
    lines = [f"| {key_label} | {val_label} |", "|---|---|"]
    for k, v in d.items():
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _format_report(file_path: str, profile: dict, extra: dict, narrative: str) -> str:
    lines = []
    lines.append(f"## 📊 EDA Report — `{os.path.basename(file_path)}`\n")
    lines.append(f"**Rows:** {profile['n_rows']:,}  |  **Columns:** {profile['n_cols']}  |  **Duplicate rows:** {profile['duplicate_rows']}\n")

    lines.append("### 🧾 Columns & Types")
    lines.append(_fmt_table(profile["dtypes"], "Column", "Type"))
    lines.append("")

    lines.append("### ❓ Missing Values")
    if profile["missing_pct"]:
        lines.append(_fmt_table(
            {k: f"{v}%" for k, v in profile["missing_pct"].items()},
            "Column", "Missing %"
        ))
    else:
        lines.append("No missing values detected. ✅")
    lines.append("")

    if profile["numeric_summary"]:
        lines.append("### 🔢 Numeric Summary")
        num_df = pd.DataFrame(profile["numeric_summary"])
        lines.append(num_df.to_markdown())
        lines.append("")

    if profile["categorical_summary"]:
        lines.append("### 🏷️ Top Categorical Values")
        for col, vc in profile["categorical_summary"].items():
            lines.append(f"**{col}**")
            lines.append(_fmt_table(vc, "Value", "Count"))
            lines.append("")

    if profile["outliers_iqr"]:
        lines.append("### 🚨 Potential Outliers (IQR method)")
        lines.append(_fmt_table(profile["outliers_iqr"], "Column", "Outlier count"))
        lines.append("")

    if profile["top_correlations"]:
        lines.append("### 🔗 Strongest Correlations")
        lines.append("| Column A | Column B | Correlation |")
        lines.append("|---|---|---|")
        for a, b, v in profile["top_correlations"]:
            lines.append(f"| {a} | {b} | {v} |")
        lines.append("")

    if extra.get("success") and extra.get("output"):
        lines.append("### 🔍 Additional Insights")
        for k, v in extra["output"].items():
            pretty = k.replace("_", " ").title()
            if isinstance(v, dict):
                lines.append(f"**{pretty}**")
                lines.append(_fmt_table(v, "Key", "Value"))
                lines.append("")
            else:
                lines.append(f"- **{pretty}:** {v}")
        lines.append("")
    elif extra.get("success") is False:
        lines.append("### 🔍 Additional Insights")
        lines.append(f"_Skipped: {extra.get('error', 'unknown error')}_\n")

    lines.append("### 🧠 Summary")
    lines.append(narrative)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The tool itself
# ---------------------------------------------------------------------------

@tool
def eda_analysis_tool(file_path: str) -> str:
    """
    Run a full automated Exploratory Data Analysis on an uploaded Excel/CSV
    file and return a structured, human-readable markdown report.

    Use this tool whenever the user asks to analyze, explore, profile, or
    get insights/statistics/summary about an uploaded spreadsheet — as
    opposed to `pandas_eda_tool`, which is for running a SPECIFIC,
    user-directed pandas query the user already described.

    Args:
        file_path: Absolute path to the uploaded .xlsx/.xls/.csv file on disk.

    Returns:
        A markdown-formatted EDA report string.
    """
    try:
        df = _load_dataframe(file_path)
    except Exception as e:
        return f"❌ Could not load the file for EDA: {e}"

    profile = _build_profile(df)

    try:
        generated_code = _generate_eda_code(profile)
        extra = _run_generated_code(generated_code, df)
    except Exception as e:
        extra = {"success": False, "error": f"Code generation step failed: {e}"}

    narrative = _generate_narrative(profile, extra.get("output", {}) if extra.get("success") else {})

    return _format_report(file_path, profile, extra, narrative)


# ---------------------------------------------------------------------------
# Integration notes (not executed — read this before wiring it up)
# ---------------------------------------------------------------------------
#
# 1) tools.py:
#       from .eda_tool import eda_analysis_tool
#       TOOLS = [sec_filing_lookup, calculator, web_search, pandas_eda_tool, eda_analysis_tool]
#
# 2) graph.py — AGENT_SYSTEM_PROMPT, add a line distinguishing the two pandas tools:
#       - pandas_eda_tool: for running a SPECIFIC pandas query/code the user described.
#       - eda_analysis_tool: for a FULL automatic exploratory analysis of an
#         uploaded file when the user asks to "analyze"/"explore"/"summarize" it.
#
# 3) Nothing else changes in your graph — ToolNode(TOOLS) + tools_condition
#    will route to it automatically once the LLM decides to call it, exactly
#    like your other tools.
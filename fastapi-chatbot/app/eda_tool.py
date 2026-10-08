"""
eda_tool.py
------------
A LangChain @tool that performs automated Exploratory Data Analysis (EDA)
on an uploaded Excel/CSV file using pandas, with a local Ollama model
(qwen2.5:7b) writing targeted follow-up analysis code and a short
narrative summary.

Two modes:
  * question empty  -> full markdown EDA report (graph.py shows it as-is)
  * question given  -> answers only that question from the data (the agent
                       LLM then phrases the short answer)

Requires: pip install tabulate   (optional - a fallback table is used without it)
"""

import os
import io
import re
import json
import contextlib
import traceback
from typing import Optional

import numpy as np
import pandas as pd
from langchain_core.tools import tool
from langchain_ollama import ChatOllama


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OLLAMA_MODEL = "qwen2.5:7b"
MAX_ROWS_FOR_PREVIEW = 5
MAX_CATEGORICAL_VALUES = 5
MAX_GENERATED_CODE_CHARS = 3000
MAX_QA_OUTPUT_CHARS = 3000

_eda_llm = ChatOllama(model=OLLAMA_MODEL, temperature=0)

# Tokens we never allow in LLM-generated code, since it runs through exec().
# Blunt filter on top of a restricted builtins dict - not a full sandbox.
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

def _parse_date_like_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert object columns that look like real dates (e.g. 2015-07-01)
    into datetime. Columns like 'July' (no digits) are left alone."""
    for col in df.select_dtypes(include=["object"]).columns:
        if "date" not in col.lower():
            continue
        sample = df[col].dropna().astype(str).head(50)
        if sample.empty or not sample.str.contains(r"\d").all():
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        if parsed.notna().mean() > 0.9:
            df[col] = parsed
    return df


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
    return _parse_date_like_columns(df)


# ---------------------------------------------------------------------------
# Step 2: Deterministic profiling (no LLM, always correct)
# ---------------------------------------------------------------------------

def _safe_describe(df: pd.DataFrame) -> dict:
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.empty:
        return {}
    return numeric_df.describe().round(2).to_dict()


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
    datetime_cols = df.select_dtypes(include=["datetime"]).columns.tolist()

    categorical_summary = {}
    for col in categorical_cols[:10]:  # cap to avoid huge reports
        vc = df[col].value_counts(dropna=True).head(MAX_CATEGORICAL_VALUES)
        categorical_summary[col] = vc.to_dict()

    return {
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


# ---------------------------------------------------------------------------
# Step 3: LLM writes pandas code (extra insights OR answer to a question)
# ---------------------------------------------------------------------------

_CODE_RULES = """STRICT RULES:
- Only use `df`, `pd`, and `np` - nothing else is available.
- Do NOT import anything, do NOT read/write files, do NOT use os/sys/eval/exec/open.
- Store every result you want reported into a dict called `output`,
  e.g. output["avg_by_category"] = df.groupby("category")["value"].mean().round(2).to_dict()
- Keep values in `output` JSON-serializable (dict, list, str, int, float). Use int()/float() on numpy scalars.
- Use ONLY column names that exist in the profile.
- Return ONLY the raw Python code. No markdown fences, no explanation, no comments.
"""

_CODE_GEN_SYSTEM = """You are a senior data analyst writing pandas code.

You are given a JSON profile describing a dataframe already loaded as `df`.
Write a SHORT pandas snippet (max 15 lines) that computes 2-4 additional,
NON-OBVIOUS insights not already covered by basic describe()/value_counts()
- for example: a meaningful groupby aggregation, a trend by a date column,
a ratio between two numeric columns, or the row(s) representing extremes.

""" + _CODE_RULES + """- If the dataframe genuinely has nothing more interesting to compute, return exactly: pass
"""

_QA_CODE_SYSTEM = """You are a senior data analyst writing pandas code.

You are given a JSON profile of a dataframe already loaded as `df`, and a
USER QUESTION. Write a SHORT pandas snippet (max 12 lines) that computes
exactly what is needed to answer that question.

""" + _CODE_RULES


def _trim_profile(profile: dict) -> dict:
    return {
        "columns": profile["columns"],
        "dtypes": profile["dtypes"],
        "numeric_cols": profile["numeric_cols"],
        "categorical_cols": profile["categorical_cols"],
        "datetime_cols": profile["datetime_cols"],
        "n_rows": profile["n_rows"],
        "sample_rows": profile["sample_rows"][:3],
    }


def _clean_code(raw: str) -> str:
    code = raw.strip()
    code = re.sub(r"^```(?:python)?\s*", "", code)
    code = re.sub(r"\s*```$", "", code)
    return code[:MAX_GENERATED_CODE_CHARS].strip()


def _generate_eda_code(profile: dict) -> str:
    messages = [
        ("system", _CODE_GEN_SYSTEM),
        ("user", f"Dataframe profile:\n{json.dumps(_trim_profile(profile), default=str)}"),
    ]
    return _clean_code(_eda_llm.invoke(messages).content)


def _generate_qa_code(profile: dict, question: str) -> str:
    messages = [
        ("system", _QA_CODE_SYSTEM),
        (
            "user",
            f"Dataframe profile:\n{json.dumps(_trim_profile(profile), default=str)}\n\n"
            f"USER QUESTION: {question}",
        ),
    ]
    return _clean_code(_eda_llm.invoke(messages).content)


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
            exec(
                compile(code, "<eda_generated_code>", "exec"),
                {"__builtins__": _ALLOWED_BUILTINS},
                local_vars,
            )
        json.dumps(local_vars.get("output", {}), default=str)  # JSON-safety check
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
# Step 4: LLM narrative summary - grounded strictly in computed numbers
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = """You are a data analyst. You are given ONLY computed statistics.
Write exactly 3 short bullet points, each starting with "- ":
1. The most notable data-quality issue (missing values / duplicates).
2. The most notable pattern or risk (outliers, correlation, extra insights).
3. One recommended next step.
Use ONLY numbers present in the JSON. No headers, no intro, no closing line."""


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
        messages = [("system", _SUMMARY_SYSTEM), ("user", json.dumps(payload, default=str))]
        return _eda_llm.invoke(messages).content.strip()
    except Exception:
        return "_Narrative summary unavailable (model call failed); see the statistics above._"


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


def _df_to_md(df: pd.DataFrame) -> str:
    """DataFrame -> markdown table. Falls back to a manual build if
    `tabulate` isn't installed."""
    try:
        return df.to_markdown()
    except ImportError:
        header = "| " + " | ".join([""] + [str(c) for c in df.columns]) + " |"
        sep = "|" + "---|" * (len(df.columns) + 1)
        rows = [
            "| " + " | ".join([str(idx)] + [str(v) for v in row]) + " |"
            for idx, row in zip(df.index, df.values.tolist())
        ]
        return "\n".join([header, sep] + rows)


def _format_report(file_path: str, profile: dict, extra: dict, narrative: str) -> str:
    # NOTE: graph.py detects the report via the text "EDA Report —" in the
    # first line. Keep that header text if you change the title.
    lines = []
    lines.append(f"## 📊 EDA Report — `{os.path.basename(file_path)}`\n")
    lines.append(
        f"**Rows:** {profile['n_rows']:,}  |  **Columns:** {profile['n_cols']}  |  "
        f"**Duplicate rows:** {profile['duplicate_rows']:,}\n"
    )

    lines.append("### 🧾 Columns & Types")
    lines.append(_fmt_table(profile["dtypes"], "Column", "Type"))
    lines.append("")

    lines.append("### ❓ Missing Values")
    if profile["missing_pct"]:
        lines.append(_fmt_table(
            {k: f"{v}%" for k, v in profile["missing_pct"].items()},
            "Column", "Missing %",
        ))
    else:
        lines.append("No missing values detected. ✅")
    lines.append("")

    if profile["numeric_summary"]:
        lines.append("### 🔢 Numeric Summary")
        # transpose: one row per column (much easier to read than 16+ wide columns)
        num_df = pd.DataFrame(profile["numeric_summary"]).T
        lines.append(_df_to_md(num_df))
        lines.append("")

    if profile["categorical_summary"]:
        lines.append("### 🏷️ Top Categorical Values")
        for col, vc in profile["categorical_summary"].items():
            lines.append(f"**{col}**\n")
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
                lines.append(f"**{pretty}**\n")
                lines.append(_fmt_table(v, "Key", "Value"))
                lines.append("")
            else:
                lines.append(f"- **{pretty}:** {v}")
        lines.append("")
    elif extra.get("success") is False:
        lines.append("### 🔍 Additional Insights")
        lines.append(f"_Skipped: {extra.get('error', 'unknown error')}_\n")

    lines.append("### 🧠 Key Takeaways")
    lines.append(narrative)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Question mode
# ---------------------------------------------------------------------------

def _answer_question(df: pd.DataFrame, profile: dict, question: str) -> str:
    try:
        code = _generate_qa_code(profile, question)
        result = _run_generated_code(code, df)
    except Exception as e:
        return f"Could not answer the question: code generation failed ({e})."

    if not result.get("success"):
        return (
            f"Could not compute an answer: {result.get('error')}. "
            f"Available columns: {profile['columns']}"
        )

    payload = {"question": question, "computed_result": result.get("output", {})}
    if result.get("stdout"):
        payload["printed"] = result["stdout"]
    return json.dumps(payload, default=str)[:MAX_QA_OUTPUT_CHARS]


# ---------------------------------------------------------------------------
# The tool itself
# ---------------------------------------------------------------------------

@tool
def eda_analysis_tool(file_path: str, question: Optional[str] = None) -> str:
    """
    Analyze an uploaded Excel/CSV file.

    Two modes:
    - Leave `question` empty to get a FULL automated EDA report (use when the
      user asks to analyze / explore / profile / summarize the whole file).
    - Set `question` to the user's specific question (e.g. "how many bookings
      were canceled?") to get only the computed answer data for that question.

    Args:
        file_path: Absolute path to the uploaded .xlsx/.xls/.csv file on disk.
        question: Optional specific question about the data. Empty = full report.

    Returns:
        A markdown EDA report (full mode) or a JSON string with the computed
        result (question mode).
    """
    try:
        df = _load_dataframe(file_path)
    except Exception as e:
        return f"Could not load the file for EDA: {e}"

    profile = _build_profile(df)

    if question and question.strip():
        return _answer_question(df, profile, question.strip())

    try:
        generated_code = _generate_eda_code(profile)
        extra = _run_generated_code(generated_code, df)
    except Exception as e:
        extra = {"success": False, "error": f"Code generation step failed: {e}"}

    narrative = _generate_narrative(
        profile, extra.get("output", {}) if extra.get("success") else {}
    )

    return _format_report(file_path, profile, extra, narrative)
import os
import io
import sys
import ast
import pandas as pd
from typing import Dict, Any
from langchain_core.tools import tool
from .logging_config import logger

def load_dataframe(file_path: str) -> pd.DataFrame:
    """Utility to load Excel or CSV into Pandas DataFrame."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found at path: {file_path}")
    
    ext = os.path.splitext(file_path)[-1].lower()
    if ext == ".csv":
        return pd.read_csv(file_path)
    elif ext in [".xlsx", ".xls"]:
        return pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext}")


@tool
def pandas_eda_tool(code: str, file_path: str) -> str:
    """
    Executes python pandas code on a CSV/Excel dataset file.
    
    Args:
        code: Python code snippet to execute on DataFrame `df`.
        file_path: Absolute or relative path to the data file.
    """
    logger.info(f"Executing pandas_eda_tool on file: {file_path}")
    
    try:
        df = load_dataframe(file_path)
    except Exception as e:
        return f"Error loading data file: {str(e)}"

    
    cleaned_code = code.strip().strip("`").replace("python\n", "").strip()

    
    safe_globals: Dict[str, Any] = {
        "df": df,
        "pd": pd,
        "__builtins__": {
            "print": print,
            "range": range,
            "len": len,
            "int": int,
            "float": float,
            "str": str,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "abs": abs,
            "sum": sum,
            "min": min,
            "max": max,
            "round": round,
            "bool": bool,
            "type": type,
        }
    }
    
    old_stdout = sys.stdout
    redirected_output = sys.stdout = io.StringIO()

    try:
        parsed_ast = ast.parse(cleaned_code)
        if parsed_ast.body and isinstance(parsed_ast.body[-1], ast.Expr):
            last_expr = parsed_ast.body.pop()
            exec(compile(parsed_ast, filename="<ast>", mode="exec"), safe_globals)
            last_val = eval(compile(ast.Expression(last_expr.value), filename="<ast>", mode="eval"), safe_globals)
            if last_val is not None:
                print(last_val)
        else:
            exec(cleaned_code, safe_globals)
            
        output = redirected_output.getvalue().strip()
        
        if not output:
            return "Code executed successfully, but produced no visual output."
            
      
        if len(output) > 3000:
            return output[:3000] + "\n... [Output truncated due to character limit]"
            
        return output

    except Exception as e:
        logger.error(f"Pandas execution error: {e}")
        return f"Execution Error: {type(e).__name__} - {str(e)}"
        
    finally:
        sys.stdout = old_stdout
import os
import ast
import operator as op
import requests
from langchain_core.tools import tool
from . import rag_service as rag_service_module
from .rag_service import is_ambiguous_query, NOT_ENOUGH_INFO_REPLY
from .eda_tool import pandas_eda_tool

@tool
def sec_filing_lookup(query: str) -> str:
    """Search SEC filing reports (10-K, 10-Q, etc.) for company financial data.
    Pass the user's full financial question."""
    if is_ambiguous_query(query):
        return NOT_ENOUGH_INFO_REPLY
    
    docs = rag_service_module.rag_service.retriever.retrieve(query, top_k=5)
    return rag_service_module.generate_answer(query, docs)


_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.Pow: op.pow, ast.USub: op.neg,
}

def _eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Unsupported expression")


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression, e.g. '394.3 * 0.15'."""
    try:
        tree = ast.parse(expression, mode="eval").body
        return str(_eval(tree))
    except Exception as e:
        return f"Error evaluating expression: {e}"


@tool
def web_search(query: str) -> str:
    """Search the live internet for recent news, real-time events, current updates, or anything not in SEC filings."""
    api_key = os.getenv("TAVILY_API_KEY")
    
    if not api_key:
        print("ERROR: TAVILY_API_KEY environment variable is missing!")
        return "ERROR: Web search API key is not configured in the backend environment."

    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 3, "search_depth": "basic"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        
        if not results:
            return "No web search results found for this query."
        
        # Explicit structured context for LLM
        formatted_results = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No Title")
            content = r.get("content", "No Content")
            formatted_results.append(f"[{i}] {title}\n{content}")
            
        return "\n\n".join(formatted_results)
        
    except Exception as e:
        print(f"Tavily Search Exception: {e}")
        return f"Error performing web search: {str(e)}"


TOOLS = [sec_filing_lookup, calculator, web_search ,pandas_eda_tool]
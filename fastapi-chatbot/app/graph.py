from typing import TypedDict, Annotated, Optional
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
import re
import pandas as pd
from .rag_service import is_small_talk, OLLAMA_MODEL, generate_small_talk_reply
from .tools import TOOLS


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    file_path: Optional[str]
    top_k: Optional[int]


# Initialize Ollama Model
llm = ChatOllama(model=OLLAMA_MODEL, temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)

AGENT_SYSTEM_PROMPT = """You are an intelligent AI Assistant with access to tools:
- sec_filing_lookup: for SEC filing / company financial questions.
- calculator: for arithmetic on numbers you already have.
- web_search: for current events, news, or anything not in SEC filings.
- pandas_eda_tool: for running Python pandas analysis on CSV/Excel files.

IMPORTANT: 
1. You do not have built-in knowledge of current events. For ANY question about 
   recent news or current events, call web_search first.
2. If an attached file path is provided in context or state, use pandas_eda_tool 
   to inspect and analyze the file. Always assume the dataset is loaded as DataFrame df. 
   First check columns (df.columns) or inspect sample rows (df.head()) before answering 
   data-specific questions.

CRITICAL RULES:
1. Never write raw Python code directly in your response text. Always call
   pandas_eda_tool to run code — never narrate or simulate running it yourself.
2. Never write phrases like "Execution Error:", "Execution Result:", or
   "let's execute this code" unless that exact text came back from the actual
   tool call. Never fabricate tool output.
3. Never invent file paths, column names, or results — only use what the tool
   actually returns.
4. Never narrate your plan before acting ("Let's calculate...", "I will use the 
   following steps..."). The moment you know a tool is needed, call it immediately 
   in the same turn — don't describe it first.
"""

def route_after_check(state: ChatState) -> str:
    last_user_msg = state["messages"][-1].content
    if is_small_talk(last_user_msg):
        return "generate"
    return "agent"


def generate_node(state: ChatState, config: RunnableConfig = None) -> dict:
    last_user_msg = state["messages"][-1].content
    reply = generate_small_talk_reply(last_user_msg)
    return {"messages": [AIMessage(content=reply)]}

def _get_file_columns(file_path: str) -> str:
    try:
        if file_path.endswith(".csv"):
            df_preview = pd.read_csv(file_path, nrows=3)
        else:
            df_preview = pd.read_excel(file_path, nrows=3)
        return f"Columns: {list(df_preview.columns)}"
    except Exception as e:
        return f"Could not preview file: {e}"
    
def _contains_raw_code(text: str) -> bool:
    """Detect karta hai ke response me raw executable code hai jo tool call
    ke bajaye seedha text me likha gaya hai."""
    return "```python" in text or "```" in text and "import pandas" in text

_STALL_PHRASES = [
    "let's proceed", "let's calculate", "i will use the following",
    "i will proceed", "let's compute", "we will now", "i'll calculate",
    "let's proceed with the calculation", "let me calculate",
]

def _is_stalling(text: str) -> bool:
    """Detect karta hai jab model sirf 'plan' bata raha ho, actual result nahi de raha."""
    if not text:
        return False
    lowered = text.lower()
    has_stall_phrase = any(p in lowered for p in _STALL_PHRASES)
    has_number = bool(re.search(r"\d", text))  # agar koi number mila to matlab result mil chuka
    return has_stall_phrase and not has_number
MAX_RETRIES = 2

async def agent_node(state: ChatState, config: RunnableConfig = None) -> dict:
    system_prompt = AGENT_SYSTEM_PROMPT
    file_path = state.get("file_path")
    if file_path:
        preview = _get_file_columns(file_path)
        system_prompt += (
            f"\n\nCURRENT ATTACHED FILE PATH: {file_path}\n"
            f"When calling pandas_eda_tool, pass file_path='{file_path}' in tool arguments.\n"
            f"DATASET PREVIEW (use these EXACT column names, do not guess):\n{preview}"
        )

    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = await llm_with_tools.ainvoke(messages)

    retries = 0
    while (
        not response.tool_calls
        and response.content
        and (_contains_raw_code(response.content) or _is_stalling(response.content))
        and retries < MAX_RETRIES
    ):
        correction_prompt = (
            "You just described a plan instead of executing it. Do NOT write "
            "sentences like 'Let's calculate' or 'I will use the following steps'. "
            "Call the appropriate tool RIGHT NOW with real arguments. "
            "Respond with ONLY the tool call — no narration, no plan, no explanation."
        )
        retry_messages = messages + [response, SystemMessage(content=correction_prompt)]
        response = await llm_with_tools.ainvoke(retry_messages)
        retries += 1

    return {"messages": [response]}

# Build graph
builder = StateGraph(ChatState)

builder.add_node("generate", generate_node)
builder.add_node("agent", agent_node)
builder.add_node("tools", ToolNode(TOOLS))

builder.set_conditional_entry_point(
    route_after_check,
    {"generate": "generate", "agent": "agent"},
)

builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
builder.add_edge("generate", END)

chat_graph_builder = builder
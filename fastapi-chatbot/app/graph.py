from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama

from .rag_service import is_small_talk, generate_small_talk_reply, OLLAMA_MODEL
from .tools import TOOLS


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]


# Initialize Ollama Model
llm = ChatOllama(model=OLLAMA_MODEL, temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)

AGENT_SYSTEM_PROMPT = """You are an intelligent AI Assistant with access to tools:
- sec_filing_lookup: for SEC filing / company financial questions.
- calculator: for arithmetic on numbers you already have.
- web_search: for current events, news, or anything not in SEC filings.

IMPORTANT: You do not have built-in knowledge of current events. For ANY question
about recent news, current events, or up-to-date information, you MUST call
web_search first — never answer from memory alone."""


def route_after_check(state: ChatState) -> str:
    last_user_msg = state["messages"][-1].content
    if is_small_talk(last_user_msg):
        return "generate"
    return "agent"


def generate_node(state: ChatState, config: RunnableConfig = None) -> dict:
    last_user_msg = state["messages"][-1].content
    reply = generate_small_talk_reply(last_user_msg)
    return {"messages": [AIMessage(content=reply)]}


async def agent_node(state: ChatState, config: RunnableConfig = None) -> dict:
    messages = [SystemMessage(content=AGENT_SYSTEM_PROMPT)] + state["messages"]
    # Model async invoke via ainvoke
    response = await llm_with_tools.ainvoke(messages)
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
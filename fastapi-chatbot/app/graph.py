# from typing import TypedDict, Annotated, Optional
# from langgraph.graph import StateGraph, END
# from langgraph.graph.message import add_messages
# from langchain_core.messages import AIMessage

# from . import rag_service as rag_service_module
# from .rag_service import is_small_talk, generate_small_talk_reply, generate_answer


# class ChatState(TypedDict):
#     messages: Annotated[list, add_messages]   # LangGraph khud purane + naye messages merge karta hai
#     top_k: int
#     retrieved_docs: Optional[list]


# def retrieve_node(state: ChatState) -> dict:
#     last_user_msg = state["messages"][-1].content
#     if is_small_talk(last_user_msg):
#         return {"retrieved_docs": []}
#     docs = rag_service_module.rag_service.retriever.retrieve(last_user_msg, top_k=state.get("top_k", 5))
#     return {"retrieved_docs": docs}


# def generate_node(state: ChatState) -> dict:
#     last_user_msg = state["messages"][-1].content
#     if is_small_talk(last_user_msg):
#         reply = generate_small_talk_reply(last_user_msg)
#     else:
#         reply = generate_answer(last_user_msg, state.get("retrieved_docs", []))
#     return {"messages": [AIMessage(content=reply)]}


# builder = StateGraph(ChatState)
# builder.add_node("retrieve", retrieve_node)
# builder.add_node("generate", generate_node)
# builder.set_entry_point("retrieve")
# builder.add_edge("retrieve", "generate")
# builder.add_edge("generate", END)

# # checkpointer abhi None hai - main.py mein lifespan pe attach hoga
# chat_graph_builder = builder


from typing import TypedDict, Annotated, Optional
import json
import ollama
import re
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from . import rag_service as rag_service_module
from .rag_service import is_small_talk, generate_small_talk_reply, generate_answer, OLLAMA_MODEL


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    top_k: int
    retrieved_docs: Optional[list]


# Helper to detect personal queries or memory clear requests
def is_personal_question(text: str) -> bool:
    keywords = [
        "my name", "who am i", "my role", "my job", 
        "what do you know about me", "my profile", "my interest", 
        "remember about me", "my facts"
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def is_memory_clear_request(text: str) -> bool:
    keywords = ["forget me", "clear memory", "delete my memory", "reset memory", "forget my details"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


# --- 1. MEMORY EXTRACTOR NODE ---
def extract_memory_node(state: ChatState, config: RunnableConfig = None, store: BaseStore = None) -> dict:
    if not store:
        return {}

    last_user_msg = state["messages"][-1].content
    if is_small_talk(last_user_msg) or is_personal_question(last_user_msg) or is_memory_clear_request(last_user_msg):
        return {}

    system_prompt = """You are a memory extractor. Analyze the user's message.
If they share ANY facts or details about themselves (e.g., name, role, interests, tech stack, preferences, location, goals), extract them into a JSON object with descriptive key-value pairs.
If no personal facts are shared, return ONLY an empty JSON object {}.

CRITICAL: Return ONLY valid raw JSON. Do not include markdown formatting or extra text."""

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Message: {last_user_msg}"},
            ],
            format="json",
            options={"temperature": 0.0},
        )

        content = response["message"]["content"].strip()

        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()

        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            clean_json_str = json_match.group(0)
            extracted_facts = json.loads(clean_json_str)

            if extracted_facts:
                existing_item = store.get(("user_profile",), "profile_data")
                existing_facts = existing_item.value if existing_item and existing_item.value else {}

                # Merge any new facts into dynamic dictionary
                existing_facts.update(extracted_facts)
                store.put(("user_profile",), "profile_data", existing_facts)
                print(f"Permanent Memory Updated: {existing_facts}")

    except Exception as e:
        print(f"Error extracting memory: {e}")

    return {}


# --- 2. RETRIEVE NODE ---
def retrieve_node(state: ChatState, config: RunnableConfig = None) -> dict:
    last_user_msg = state["messages"][-1].content
    
    if is_small_talk(last_user_msg) or is_personal_question(last_user_msg) or is_memory_clear_request(last_user_msg):
        return {"retrieved_docs": []}
    
    tk = state.get("top_k") or 5
    docs = rag_service_module.rag_service.retriever.retrieve(last_user_msg, top_k=tk)
    return {"retrieved_docs": docs}


# --- 3. GENERATE NODE ---
def generate_node(state: ChatState, config: RunnableConfig = None, store: BaseStore = None) -> dict:
    user_profile_data = {}
    
    if store:
        try:
            mem_item = store.get(("user_profile",), "profile_data")
            if mem_item and mem_item.value:
                user_profile_data = mem_item.value
        except Exception as e:
            print(f"Error fetching from store: {e}")

    last_user_msg = state["messages"][-1].content

    # A. MEMORY DELETE REQUEST (Jab chat delete/reset karni ho)
    if is_memory_clear_request(last_user_msg):
        if store:
            try:
                store.delete(("user_profile",), "profile_data")
                reply = "I have cleared all stored facts about you from my memory."
            except Exception as e:
                reply = f"Error clearing memory: {e}"
        else:
            reply = "No active memory store found to clear."
        return {"messages": [AIMessage(content=reply)]}

    # B. DYNAMIC PERSONAL QUESTION RESPONSE (Works for ANY extracted field)
    if is_personal_question(last_user_msg):
        if user_profile_data:
            formatted_details = []
            for k, v in user_profile_data.items():
                key_clean = k.replace("_", " ").title()
                formatted_details.append(f"• **{key_clean}**: {v}")
            
            details_str = "\n".join(formatted_details)
            reply = f"Here is what I remember about you:\n{details_str}\n\nHow can I help you today?"
        else:
            reply = "You haven't shared any details with me yet! What would you like me to remember?"
            
        return {"messages": [AIMessage(content=reply)]}

    # C. NORMAL RAG & SMALL TALK FLOW
    if user_profile_data:
        profile_str = f"[User Profile Context: {json.dumps(user_profile_data)}]\n"
    else:
        profile_str = ""

    full_prompt = profile_str + last_user_msg

    if is_small_talk(last_user_msg):
        reply = generate_small_talk_reply(full_prompt)
    else:
        reply = generate_answer(full_prompt, state.get("retrieved_docs", []))
        
    return {"messages": [AIMessage(content=reply)]}


# --- 4. GRAPH ARCHITECTURE ---
builder = StateGraph(ChatState)

builder.add_node("retrieve", retrieve_node)
builder.add_node("generate", generate_node)
builder.add_node("extract_memory", extract_memory_node)

builder.set_entry_point("retrieve")
builder.add_edge("retrieve", "generate")
builder.add_edge("retrieve", "extract_memory") 
builder.add_edge("generate", END)
builder.add_edge("extract_memory", END)

chat_graph_builder = builder
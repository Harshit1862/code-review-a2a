"""The orchestrator agent: a LangGraph tool-calling loop with per-thread memory.

    START -> agent --(tool calls?)--> tools -> agent ... -> END
"""

from langchain_core.messages import SystemMessage, trim_messages
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from common.config import settings
from common.llm import get_llm
from common.timeutils import now_local
from orchestrator.tools import TOOLS

SYSTEM_PROMPT = """You are the Code Review Orchestrator. You track git pushes stored in a database
and can score any push with three specialist agents (Code quality, Best practices, Security).

Current local date and time: {now} ({tz}).

How to work:
- Always use tools for facts about projects, pushes and reviews. Never invent push IDs, counts or scores.
- "Any updates?" / "recent" / "today" questions that do NOT name a project: first call list_projects.
  If more than one project is tracked, ask the user which project they mean instead of guessing or
  showing all of them. If there is only one project (or the user already named one, or asked for
  pushes/updates "across everything"/"all projects" explicitly), call search_pushes directly.
- "How many" questions -> count_pushes (same project-ambiguity rule applies).
- "What changed in X" -> get_push_details.
- "Score / review / rate it" -> review_push. If the user says "it", "that one" or "the latest",
  use the push ID from the conversation; if there is none, call search_pushes first with limit=1.
- Previously scored pushes: get_review. Only re-run (force=true) if the user asks to re-run.

How to answer:
- Be short and clear. Always mention push IDs as #<id>.
- For reviews, show the three scores separately as "X/10", each with a 1-2 sentence report and its
  most important findings. Mention how the score was calculated if the user asks.
- If nothing matches, say so plainly and suggest a wider filter."""


def build_graph(checkpointer):
    llm = get_llm().bind_tools(TOOLS)

    async def agent(state: MessagesState) -> dict:
        system = SystemMessage(content=SYSTEM_PROMPT.format(
            now=now_local().strftime("%A %Y-%m-%d %H:%M"), tz=settings.timezone))
        # Keep the last ~30 messages so long chats stay within the model's context
        history = trim_messages(state["messages"], max_tokens=30, token_counter=len,
                                strategy="last", start_on="human", include_system=False)
        response = await llm.ainvoke([system, *history])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)  # -> "tools" or END
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)

"""LangGraph topology for payout assessment and approval-gated submission."""

from typing import Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.workflows.payout.state import SmartPayoutState


class SmartPayoutNodeHandlers(Protocol):
    """Service methods used as smart payout graph nodes."""

    async def load_payout(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState: ...

    async def assess_payout(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState: ...

    async def generate_summary(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState: ...

    async def persist_decision(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState: ...

    async def await_human_approval(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState: ...

    async def load_approved_payout(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState: ...

    async def submit_payout(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState: ...


def _route_start(state: SmartPayoutState) -> str:
    return "submit" if state.get("resume_decision_id") is not None else "assess"


def build_smart_payout_graph(
    nodes: SmartPayoutNodeHandlers,
) -> CompiledStateGraph[
    SmartPayoutState,
    None,
    SmartPayoutState,
    SmartPayoutState,
]:
    """Compile the recommendation workflow and persisted approval resume path."""
    graph = StateGraph(SmartPayoutState)
    graph.add_node("load_payout", nodes.load_payout)
    graph.add_node("assess_payout", nodes.assess_payout)
    graph.add_node("generate_summary", nodes.generate_summary)
    graph.add_node("persist_decision", nodes.persist_decision)
    graph.add_node("await_human_approval", nodes.await_human_approval)
    graph.add_node("load_approved_payout", nodes.load_approved_payout)
    graph.add_node("submit_payout", nodes.submit_payout)
    graph.add_conditional_edges(
        START,
        _route_start,
        {"assess": "load_payout", "submit": "load_approved_payout"},
    )
    graph.add_edge("load_payout", "assess_payout")
    graph.add_edge("assess_payout", "generate_summary")
    graph.add_edge("generate_summary", "persist_decision")
    graph.add_edge("persist_decision", "await_human_approval")
    graph.add_edge("await_human_approval", END)
    graph.add_edge("load_approved_payout", "submit_payout")
    graph.add_edge("submit_payout", END)
    return graph.compile()

"""LangGraph topology for dispute evidence preparation and approval-gated submit."""

from typing import Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.workflows.dispute.state import DisputeDefenseState


class DisputeDefenseNodeHandlers(Protocol):
    """Application service methods used by the dispute graph."""

    async def receive_dispute_event(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def retrieve_local_context(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def retrieve_paypal_order(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def retrieve_shipping_evidence(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def retrieve_communication_history(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def build_evidence_package(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def generate_narrative(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def calculate_success_probability(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def recommend_action(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def create_decision_record(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def await_human_approval(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def load_approved_case(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...

    async def submit_evidence(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState: ...


def _route_after_event(state: DisputeDefenseState) -> str:
    return "resume" if state.get("resume_decision_id") is not None else "new_event"


def build_dispute_defense_graph(
    nodes: DisputeDefenseNodeHandlers,
) -> CompiledStateGraph[
    DisputeDefenseState,
    None,
    DisputeDefenseState,
    DisputeDefenseState,
]:
    """Compile the review workflow; approval is resumed from persisted records."""
    graph = StateGraph(DisputeDefenseState)
    graph.add_node("receive_dispute_event", nodes.receive_dispute_event)
    graph.add_node("retrieve_local_context", nodes.retrieve_local_context)
    graph.add_node("retrieve_paypal_order", nodes.retrieve_paypal_order)
    graph.add_node("retrieve_shipping_evidence", nodes.retrieve_shipping_evidence)
    graph.add_node(
        "retrieve_communication_history",
        nodes.retrieve_communication_history,
    )
    graph.add_node("build_evidence_package", nodes.build_evidence_package)
    graph.add_node("generate_narrative", nodes.generate_narrative)
    graph.add_node("calculate_success_probability", nodes.calculate_success_probability)
    graph.add_node("recommend_action", nodes.recommend_action)
    graph.add_node("create_decision_record", nodes.create_decision_record)
    graph.add_node("await_human_approval", nodes.await_human_approval)
    graph.add_node("load_approved_case", nodes.load_approved_case)
    graph.add_node("submit_evidence", nodes.submit_evidence)

    graph.add_edge(START, "receive_dispute_event")
    graph.add_conditional_edges(
        "receive_dispute_event",
        _route_after_event,
        {"new_event": "retrieve_local_context", "resume": "load_approved_case"},
    )
    graph.add_edge("retrieve_local_context", "retrieve_paypal_order")
    graph.add_edge("retrieve_paypal_order", "retrieve_shipping_evidence")
    graph.add_edge("retrieve_shipping_evidence", "retrieve_communication_history")
    graph.add_edge("retrieve_communication_history", "build_evidence_package")
    graph.add_edge("build_evidence_package", "generate_narrative")
    graph.add_edge("generate_narrative", "calculate_success_probability")
    graph.add_edge("calculate_success_probability", "recommend_action")
    graph.add_edge("recommend_action", "create_decision_record")
    graph.add_edge("create_decision_record", "await_human_approval")
    graph.add_edge("await_human_approval", END)
    graph.add_edge("load_approved_case", "submit_evidence")
    graph.add_edge("submit_evidence", END)
    return graph.compile()

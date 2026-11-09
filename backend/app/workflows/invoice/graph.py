"""LangGraph topology for invoice compliance review."""

from typing import Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.workflows.invoice.state import InvoiceComplianceState


class InvoiceComplianceNodeHandlers(Protocol):
    """Service methods used as invoice workflow nodes."""

    async def load_invoice(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState: ...

    async def find_duplicates(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState: ...

    async def assess_invoice(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState: ...

    async def generate_summary(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState: ...

    async def persist_decision(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState: ...

    async def await_human_review(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState: ...


def build_invoice_compliance_graph(
    nodes: InvoiceComplianceNodeHandlers,
) -> CompiledStateGraph[
    InvoiceComplianceState,
    None,
    InvoiceComplianceState,
    InvoiceComplianceState,
]:
    """Compile invoice data checks into an auditable pending recommendation."""
    graph = StateGraph(InvoiceComplianceState)
    graph.add_node("load_invoice", nodes.load_invoice)
    graph.add_node("find_duplicates", nodes.find_duplicates)
    graph.add_node("assess_invoice", nodes.assess_invoice)
    graph.add_node("generate_summary", nodes.generate_summary)
    graph.add_node("persist_decision", nodes.persist_decision)
    graph.add_node("await_human_review", nodes.await_human_review)
    graph.add_edge(START, "load_invoice")
    graph.add_edge("load_invoice", "find_duplicates")
    graph.add_edge("find_duplicates", "assess_invoice")
    graph.add_edge("assess_invoice", "generate_summary")
    graph.add_edge("generate_summary", "persist_decision")
    graph.add_edge("persist_decision", "await_human_review")
    graph.add_edge("await_human_review", END)
    return graph.compile()

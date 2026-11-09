"use client";

import { ArrowUpRight, Bot, ShieldCheck, Sparkles } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { PageHeading } from "@/components/page-heading";
import { ErrorState, LoadingState } from "@/components/request-state";
import { StatusBadge } from "@/components/status-badge";
import { askBackend, readBackend } from "@/lib/api";
import {
  copilotAnswerSchema,
  copilotOverviewSchema,
  copilotQuestionSchema,
} from "@/lib/contracts";

const suggestions = [
  "What risks need attention this week?",
  "How are dispute volumes trending?",
  "Where is revenue waiting to be collected?",
  "What should an operations lead review first?",
];

export default function CopilotPage() {
  const [question, setQuestion] = useState("");
  const overview = useQuery({
    queryKey: ["copilot-insights"],
    queryFn: () => readBackend("copilot/insights", copilotOverviewSchema),
  });
  const answer = useMutation({
    mutationFn: (input: unknown) =>
      askBackend(
        "copilot/ask",
        copilotQuestionSchema.parse(input),
        copilotAnswerSchema,
      ),
  });

  function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = copilotQuestionSchema.safeParse({ question });
    if (parsed.success) {
      answer.mutate(parsed.data);
    }
  }

  return (
    <>
      <PageHeading
        eyebrow="EXECUTIVE INTELLIGENCE · 06"
        title="Commerce copilot"
        description="Explore tenant-level trends and operational priorities with answers grounded in reporting data."
        actions={
          <span className="human-review-mark">
            <ShieldCheck aria-hidden="true" size={15} />
            HUMAN-APPROVAL ONLY
          </span>
        }
      />
      <div className="copilot-layout">
        <section className="panel copilot-chat">
          <div className="copilot-title">
            <span className="copilot-avatar">
              <Bot aria-hidden="true" size={18} />
            </span>
            <div>
              <h2>Ask about your operation</h2>
              <span className="copilot-status">
                <span className="live-dot" />
                GROUNDED IN YOUR AGGREGATES
              </span>
            </div>
          </div>
          <p className="copilot-intro">
            Ask about revenue patterns, dispute risk, receivables, or the next
            operational review. The copilot uses only aggregated reporting
            facts; it cannot approve payouts or submit disputes.
          </p>
          <div className="suggestion-list" aria-label="Suggested questions">
            {suggestions.map((suggestion) => (
              <button
                className="suggestion-chip"
                key={suggestion}
                onClick={() => setQuestion(suggestion)}
                type="button"
              >
                {suggestion}
              </button>
            ))}
          </div>
          <form className="copilot-form" onSubmit={submitQuestion}>
            <label className="visually-hidden" htmlFor="copilot-question">
              Ask the commerce copilot
            </label>
            <input
              className="field"
              id="copilot-question"
              maxLength={1000}
              minLength={3}
              onChange={(event) => setQuestion(event.currentTarget.value)}
              placeholder="Ask a question about your commerce operation..."
              required
              value={question}
            />
            <button
              className="button button-primary"
              disabled={answer.isPending || question.trim().length < 3}
              type="submit"
            >
              {answer.isPending ? "Analyzing..." : "Ask"}
              <ArrowUpRight aria-hidden="true" size={15} />
            </button>
          </form>
          {answer.isError ? (
            <div className="inline-error" role="alert">
              {answer.error.message}
            </div>
          ) : null}
          {answer.data ? (
            <article className="answer-card" aria-live="polite">
              <h3>Executive summary</h3>
              <p>{answer.data.answer}</p>
              <div className="source-list">
                Sources: {answer.data.sources.join(" · ")}
              </div>
            </article>
          ) : null}
          <div className="copilot-disclaimer">
            Recommendations are informational and may be incomplete. Verify
            decisions against the underlying work queues. No financial action
            can be initiated from this assistant.
          </div>
        </section>

        <aside>
          <div className="insights-heading">
            <div className="panel-heading">
              <div>
                <h2>Operational signals</h2>
                <p>Rule-based findings from the latest snapshot</p>
              </div>
              <Sparkles aria-hidden="true" color="#68d5ac" size={17} />
            </div>
          </div>
          {overview.isLoading ? (
            <LoadingState label="Loading operational signals" />
          ) : overview.isError ? (
            <ErrorState
              message={overview.error.message}
              onRetry={() => void overview.refetch()}
            />
          ) : (
            <div className="insights-list">
              {overview.data?.insights.map((insight) => (
                <article className="insight-card" key={insight.title}>
                  <div className="insight-card-heading">
                    <span className="insight-label">
                      {insight.category.replaceAll("_", " ")}
                    </span>
                    <StatusBadge value={insight.severity} />
                  </div>
                  <h3>{insight.title}</h3>
                  <p>{insight.summary}</p>
                  <p className="recommendation">{insight.recommendation}</p>
                </article>
              ))}
            </div>
          )}
        </aside>
      </div>
    </>
  );
}

"use client";

import React, { useState, useRef, useEffect } from "react";
import { MessageSquareText, Send, Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * frontend/components/soc/ChatInterface.tsx
 *
 * Feature 16: ask a free-text question about an incident, get an answer
 * grounded in the recorded decision-provenance graph
 * (backend/agents/chat_agent.py -> backend/routers/chat.py).
 *
 * Styled to match IncidentFeed.tsx's actual conventions: font-mono,
 * neon accent palette, backdrop-blur panel, terminal-style header
 * tagged with the backend file it talks to.
 *
 * NOTE: unlike IncidentFeed.tsx (which currently simulates random data
 * client-side with setInterval), this component makes a REAL fetch call
 * to the backend. It's the first "live" panel in the frontend right now
 * — worth flagging to the team when merging.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Confidence = "grounded" | "partial" | "insufficient_data";

interface ChatMessage {
  role: "judge" | "chimera";
  text: string;
  citedEdgeIds?: number[];
  confidence?: Confidence;
}

interface ChatInterfaceProps {
  incidentId: number;
}

const CONFIDENCE_STYLES: Record<Confidence, string> = {
  grounded: "bg-[#00ff66]/10 text-[#00ff66] border-[#00ff66]/30",
  partial: "bg-[#ffb703]/10 text-[#ffb703] border-[#ffb703]/30",
  insufficient_data: "bg-[#ff003c]/10 text-[#ff003c] border-[#ff003c]/30",
};

export default function ChatInterface({ incidentId }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  async function askQuestion() {
    const question = input.trim();
    if (!question || loading) return;

    setMessages((prev) => [...prev, { role: "judge", text: question }]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/incidents/${incidentId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (!res.ok) throw new Error(`Request failed: ${res.status}`);

      const data: {
        answer: string;
        cited_edge_ids: number[];
        confidence: Confidence;
      } = await res.json();

      setMessages((prev) => [
        ...prev,
        {
          role: "chimera",
          text: data.answer,
          citedEdgeIds: data.cited_edge_ids,
          confidence: data.confidence,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "chimera",
          text: "Couldn't reach the incident explainer — check the backend is running.",
          confidence: "insufficient_data",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full h-full min-h-[300px] flex flex-col bg-white/[0.02] backdrop-blur-md border border-white/5 rounded-xl overflow-hidden hover:border-[#00f0ff]/30 transition-all">
      {/* Panel Header — matches IncidentFeed.tsx's terminal-tag convention */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-black/40">
        <div className="flex items-center gap-2">
          <MessageSquareText className="w-3.5 h-3.5 text-[#00f0ff]" />
          <h3 className="text-xs font-mono text-gray-300 tracking-widest uppercase">
            INCIDENT_EXPLAINER [chat_agent.py]
          </h3>
        </div>
        <div className="flex items-center gap-2 text-[10px] font-mono text-white/50">
          <span className="w-1.5 h-1.5 rounded-full bg-[#00f0ff] animate-ping" />
          <span className="text-[#00f0ff]">GROUNDED</span>
        </div>
      </div>

      {/* Message feed */}
      <div ref={feedRef} className="flex-1 p-3 space-y-2 overflow-y-auto font-mono text-xs">
        {messages.length === 0 && (
          <p className="text-white/30 text-[11px] px-1 py-2">
            &gt; try: &ldquo;why did you block this IP?&rdquo;
          </p>
        )}

        {messages.map((msg, i) => {
          const isJudge = msg.role === "judge";
          return (
            <div
              key={i}
              className={cn(
                "flex items-start gap-2 px-3 py-2 rounded border text-[11px]",
                isJudge
                  ? "bg-white/[0.03] border-white/10 text-white/90"
                  : "bg-[#00f0ff]/5 border-[#00f0ff]/20 text-[#00f0ff]/90"
              )}
            >
              {isJudge ? (
                <User className="w-3 h-3 mt-0.5 shrink-0 text-white/40" />
              ) : (
                <Bot className="w-3 h-3 mt-0.5 shrink-0 text-[#00f0ff]/60" />
              )}
              <div className="flex-1">
                <p>{msg.text}</p>
                {msg.confidence && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "px-1.5 py-0.5 text-[9px] font-bold rounded uppercase border",
                        CONFIDENCE_STYLES[msg.confidence]
                      )}
                    >
                      {msg.confidence.replace("_", " ")}
                    </span>
                    {!!msg.citedEdgeIds?.length && (
                      <span className="text-[10px] text-white/30">
                        edges: {msg.citedEdgeIds.join(", ")}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {loading && (
          <p className="text-[11px] text-white/30 px-1 animate-pulse">
            &gt; querying provenance graph...
          </p>
        )}
      </div>

      {/* Input row */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-white/5 bg-black/40">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && askQuestion()}
          placeholder="ask about this incident..."
          className="flex-1 bg-transparent font-mono text-[11px] text-white placeholder:text-white/30 focus:outline-none"
        />
        <button
          onClick={askQuestion}
          disabled={loading}
          className="p-1.5 rounded bg-[#00f0ff]/10 border border-[#00f0ff]/30 text-[#00f0ff] hover:bg-[#00f0ff]/20 transition-all disabled:opacity-40"
        >
          <Send className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

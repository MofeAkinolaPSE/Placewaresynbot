import { useState } from "react";
import { Send, Plus, Trash2, AlertCircle, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiUrl } from "@/lib/api-base";
import { authClient } from "@/lib/auth-client";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

const AskSynbot = () => {
  const [conversations, setConversations] = useState([
    {
      id: 1,
      title: "New Conversation",
      timestamp: new Date().toLocaleString(),
      active: true,
    },
  ]);

  const [activeConvId, setActiveConvId] = useState(1);
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<any[]>([]);
  const [isSending, setIsSending] = useState(false);

  const handleSendMessage = async () => {
    const trimmed = message.trim();
    if (!trimmed || isSending) return;

    const userMsg = {
      id: messages.length + 1,
      type: "user" as const,
      content: trimmed,
      timestamp: new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
    };
    setMessages((prev) => [...prev, userMsg]);
    setMessage("");
    setIsSending(true);

    try {
      let token = authClient.getAccessToken();
      if (!token) {
        const refreshed = await authClient.refresh();
        if (refreshed) {
          token = authClient.getAccessToken();
        }
      }

      let res = await fetch(apiUrl("/chat"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { "Authorization": `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ question: trimmed, mode: "executive" }),
      });

      if (res.status === 401) {
        const refreshed = await authClient.refresh();
        if (refreshed) {
          token = authClient.getAccessToken();
          res = await fetch(apiUrl("/chat"), {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { "Authorization": `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ question: trimmed, mode: "executive" }),
          });
        }
      }

      if (!res.ok) {
        let detail = `Chat request failed (${res.status})`;
        try {
          const err = await res.json();
          detail = err?.detail || err?.error || detail;
        } catch {
          const txt = await res.text();
          if (txt) detail = txt;
        }
        throw new Error(detail);
      }

      const data = await res.json();
      if (!data || typeof data.answer !== "string" || !data.answer.trim()) {
        throw new Error("Chat response did not include a valid answer.");
      }
      const sources = (data.sources || []).map((s: any) => ({
        label: s.question || "Q&A snippet",
        url: "#",
      }));

      const botMsg = {
        id: userMsg.id + 1,
        type: "bot" as const,
        content: data.answer,
        timestamp: new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
        sources,
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (e: any) {
      const errorMsg = {
        id: messages.length + 2,
        type: "bot" as const,
        content: `Error: ${e?.message || "Chat request failed"}`,
        timestamp: new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      };
      setMessages((prev) => [...prev, errorMsg]);
      console.error(e);
    } finally {
      setIsSending(false);
    }
  };

  const deleteConversation = (id: number) => {
    setConversations(conversations.filter((c) => c.id !== id));
    if (activeConvId === id && conversations.length > 0) {
      setActiveConvId(conversations[0].id);
    }
  };

  const activeConversation = conversations.find((c) => c.id === activeConvId);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface flex min-h-[calc(100vh-8rem)]"
    >
      {/* Sidebar - Conversations */}
      <div className="z-10 flex w-64 flex-col border-r border-border/70 bg-card/80 backdrop-blur-md">
        <div className="p-4 border-b border-border">
          <Button
            className="w-full"
            size="sm"
            onClick={() => {
              const nextId = conversations.length + 1;
              const newConv = {
                id: nextId,
                title: "New Conversation",
                timestamp: new Date().toLocaleString(),
                active: true,
              };
              setConversations((prev) =>
                prev.map((c) => ({ ...c, active: false })).concat(newConv)
              );
              setActiveConvId(nextId);
              setMessages([]);
            }}
          >
            <Plus className="w-4 h-4 mr-2" />
            New Conversation
          </Button>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-2 space-y-2">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => setActiveConvId(conv.id)}
                className={`p-3 rounded-lg cursor-pointer transition-colors group ${
                  activeConvId === conv.id
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                <p className="text-sm font-medium truncate">{conv.title}</p>
                <p
                  className={`text-xs mt-1 ${
                    activeConvId === conv.id
                      ? "text-primary-foreground/70"
                      : "text-muted-foreground"
                  }`}
                >
                  {conv.timestamp}
                </p>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteConversation(conv.id);
                  }}
                  className={`opacity-0 group-hover:opacity-100 transition-opacity mt-2 p-1 rounded hover:bg-black/10 ${
                    activeConvId === conv.id ? "" : ""
                  }`}
                  title="Delete conversation"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        </ScrollArea>

        <div className="border-t border-border/70 p-4 text-xs text-muted-foreground">
          <p>Warebot v1.0</p>
          <p>Powered by Placeware AI</p>
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="z-10 flex flex-1 flex-col">
        {/* Header */}
        <div className="border-b border-border/70 bg-card/80 p-6 backdrop-blur-md">
          <h1 className="text-2xl font-bold text-foreground">
            {activeConversation?.title}
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            {activeConversation?.timestamp}
          </p>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 p-6">
          <div className="space-y-6 max-w-4xl">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex gap-4 ${
                  msg.type === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {msg.type === "bot" && (
                  <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-primary-foreground font-semibold text-sm flex-shrink-0">
                    P
                  </div>
                )}

                <div
                  className={`max-w-2xl ${
                    msg.type === "user" ? "text-right" : "text-left"
                  }`}
                >
                  <div
                    className={`inline-block rounded-lg p-4 ${
                      msg.type === "user"
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted"
                    }`}
                  >
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">
                      {msg.content}
                    </p>
                  </div>

                  {msg.type === "bot" && msg.sources && (
                    <div className="mt-3 space-y-1">
                      <p className="text-xs font-semibold text-muted-foreground uppercase">
                        Sources
                      </p>
                      {msg.sources.map((source, idx) => (
                        <a
                          key={idx}
                          href={source.url}
                          className="flex items-center gap-1 text-xs text-primary hover:underline"
                        >
                          <ExternalLink className="w-3 h-3" />
                          {source.label}
                        </a>
                      ))}
                    </div>
                  )}

                  <p className="text-xs text-muted-foreground mt-2">
                    {msg.timestamp}
                  </p>
                </div>

                {msg.type === "user" && (
                  <div className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-secondary-foreground font-semibold text-sm flex-shrink-0">
                    A
                  </div>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>

        {/* Disclaimer */}
        <div className="mx-6 mb-4 rounded-xl border border-warning/30 bg-warning/15 p-4">
          <div className="flex gap-3">
            <AlertCircle className="w-4 h-4 text-warning flex-shrink-0 mt-0.5" />
            <p className="text-xs text-warning">
              <strong>Pharma Compliance Notice:</strong> Warebot analysis is for business intelligence only. 
              For regulated decisions (formulary inclusions, pricing), consult subject matter experts and 
              regulatory compliance team.
            </p>
          </div>
        </div>

        {/* Input */}
        <div className="p-6 border-t border-border">
          <div className="flex gap-2 max-w-4xl">
            <Input
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyPress={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              placeholder="Ask Warebot a question about your business..."
              className="flex-1"
            />
            <Button onClick={handleSendMessage} size="icon" disabled={isSending}>
              <Send className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

export default AskSynbot;

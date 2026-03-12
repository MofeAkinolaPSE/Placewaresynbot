import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

export default function StaffCollaboration() {
  const queryClient = useQueryClient();
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
  const [newChannelTitle, setNewChannelTitle] = useState("");
  const [newChannelKey, setNewChannelKey] = useState("");
  const [contextType, setContextType] = useState("");
  const [contextId, setContextId] = useState("");
  const [message, setMessage] = useState("");

  useRealtimeChannel("chat_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["chat-channels"] });
    void queryClient.invalidateQueries({ queryKey: ["chat-unread"] });
    if (selectedThreadId) {
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", selectedThreadId] });
      void queryClient.invalidateQueries({ queryKey: ["chat-presence", selectedThreadId] });
    }
  });

  const channelsQuery = useQuery({
    queryKey: ["chat-channels"],
    queryFn: () => api.threads.listChannels(),
  });

  const unreadQuery = useQuery({
    queryKey: ["chat-unread"],
    queryFn: () => api.threads.unreadSummary(),
  });

  const messagesQuery = useQuery({
    queryKey: ["chat-messages", selectedThreadId],
    queryFn: () => api.threads.listMessages(selectedThreadId as string),
    enabled: !!selectedThreadId,
  });

  const presenceQuery = useQuery({
    queryKey: ["chat-presence", selectedThreadId],
    queryFn: () => api.threads.getPresence(selectedThreadId as string),
    enabled: !!selectedThreadId,
    refetchInterval: 20_000,
  });

  const unreadMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of unreadQuery.data?.items || []) {
      map.set(String(item.thread_id), Number(item.unread_count || 0));
    }
    return map;
  }, [unreadQuery.data]);

  const createChannelMutation = useMutation({
    mutationFn: () =>
      api.threads.createChannel({
        title: newChannelTitle,
        channel_key: newChannelKey,
        context_type: contextType || undefined,
        context_id: contextId || undefined,
      }),
    onSuccess: () => {
      setNewChannelTitle("");
      setNewChannelKey("");
      setContextType("");
      setContextId("");
      void queryClient.invalidateQueries({ queryKey: ["chat-channels"] });
    },
  });

  const sendMessageMutation = useMutation({
    mutationFn: () =>
      api.threads.postMessage(selectedThreadId as string, {
        content: message,
        metadata: {
          context_link: contextType && contextId ? { type: contextType, id: contextId } : undefined,
        },
      }),
    onSuccess: async () => {
      setMessage("");
      if (selectedThreadId) {
        await api.threads.markRead(selectedThreadId);
        void queryClient.invalidateQueries({ queryKey: ["chat-messages", selectedThreadId] });
        void queryClient.invalidateQueries({ queryKey: ["chat-unread"] });
      }
    },
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-6 p-8"
    >
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Staff Collaboration</h1>
        <p className="text-muted-foreground">Group channels with context-linked threads, presence, and unread tracking.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="pw-surface-interactive">
          <CardHeader>
            <CardTitle>Create Channel</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <Label>Channel Name</Label>
              <Input value={newChannelTitle} onChange={(e) => setNewChannelTitle(e.target.value)} placeholder="Ops Daily" />
            </div>
            <div>
              <Label>Channel Key</Label>
              <Input value={newChannelKey} onChange={(e) => setNewChannelKey(e.target.value)} placeholder="ops-daily" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label>Context Type</Label>
                <Input value={contextType} onChange={(e) => setContextType(e.target.value)} placeholder="project" />
              </div>
              <div>
                <Label>Context ID</Label>
                <Input value={contextId} onChange={(e) => setContextId(e.target.value)} placeholder="PRJ-001" />
              </div>
            </div>
            <Button
              className="w-full"
              onClick={() => createChannelMutation.mutate()}
              disabled={!newChannelTitle || !newChannelKey || createChannelMutation.isPending}
            >
              {createChannelMutation.isPending ? "Creating..." : "Create Channel"}
            </Button>
          </CardContent>
        </Card>

        <Card className="pw-surface-interactive lg:col-span-2">
          <CardHeader>
            <CardTitle>Channels</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {(channelsQuery.data || []).length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {channelsQuery.isLoading ? "Loading channels..." : "No channels yet."}
              </p>
            ) : (
              (channelsQuery.data || []).map((channel: any) => {
                const unread = unreadMap.get(String(channel.id)) || 0;
                return (
                  <button
                    key={channel.id}
                    onClick={async () => {
                      setSelectedThreadId(String(channel.id));
                      await api.threads.setPresence(String(channel.id), "online");
                      await api.threads.markRead(String(channel.id));
                      void queryClient.invalidateQueries({ queryKey: ["chat-unread"] });
                    }}
                    className={`w-full rounded-xl border border-border/70 bg-card/40 p-3 text-left transition-colors hover:border-primary/40 ${selectedThreadId === String(channel.id) ? "border-primary bg-primary/5" : ""}`}
                  >
                    <div className="flex items-center justify-between">
                      <p className="font-medium">{channel.title}</p>
                      {unread > 0 && <Badge>{unread}</Badge>}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      #{channel.channel_key || "channel"}
                      {channel.context_type && channel.context_id
                        ? ` · linked to ${channel.context_type}:${channel.context_id}`
                        : ""}
                    </p>
                  </button>
                );
              })
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="pw-surface-interactive lg:col-span-2">
          <CardHeader>
            <CardTitle>Thread Messages</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {!selectedThreadId ? (
              <p className="text-sm text-muted-foreground">Select a channel to view messages.</p>
            ) : (
              <>
                <div className="pw-surface-base max-h-[420px] space-y-2 overflow-y-auto rounded-xl p-3">
                  {(messagesQuery.data || []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      {messagesQuery.isLoading ? "Loading messages..." : "No messages yet."}
                    </p>
                  ) : (
                    (messagesQuery.data || []).map((msg: any) => (
                      <div key={msg.id} className="rounded-xl border border-border/60 bg-background/60 p-2">
                        <p className="text-sm">{msg.content}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {msg.sender || "unknown"} · {msg.created_at || "-"}
                        </p>
                      </div>
                    ))
                  )}
                </div>
                <div className="flex gap-2">
                  <Input
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    placeholder="Type a message"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey && message.trim()) {
                        e.preventDefault();
                        sendMessageMutation.mutate();
                      }
                    }}
                  />
                  <Button
                    onClick={() => sendMessageMutation.mutate()}
                    disabled={!message.trim() || sendMessageMutation.isPending}
                  >
                    Send
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="pw-surface-interactive">
          <CardHeader>
            <CardTitle>Presence</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {!selectedThreadId ? (
              <p className="text-sm text-muted-foreground">Presence appears for selected channel.</p>
            ) : (presenceQuery.data || []).length === 0 ? (
              <p className="text-sm text-muted-foreground">No active members.</p>
            ) : (
              (presenceQuery.data || []).map((p: any) => (
                <div key={`${p.thread_id}-${p.user_id}`} className="rounded-xl border border-border/60 bg-background/60 p-2">
                  <p className="text-sm font-medium">{p.user_id}</p>
                  <p className="text-xs text-muted-foreground">{p.status} · {p.last_seen_at || "-"}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </motion.div>
  );
}

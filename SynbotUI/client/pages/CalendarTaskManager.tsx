import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Calendar as CalendarIcon,
  Clock,
  Plus,
  Check,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  ListTodo,
  Flag,
  MoreHorizontal,
  Search,
  Trash2,
  User,
  UserCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Calendar } from "@/components/ui/calendar";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

interface CalendarEvent {
  id: string;
  title: string;
  description?: string;
  event_type: "meeting" | "deadline" | "reminder" | "holiday" | "other";
  start_time: string;
  end_time?: string;
  all_day: boolean;
  location?: string;
}

interface Task {
  id: string;
  title: string;
  description?: string;
  status: "pending" | "in_progress" | "completed" | "cancelled" | "blocked";
  priority: "low" | "medium" | "high" | "critical";
  due_date?: string;
  assigned_to?: string;
  source: string;
  created_at: string;
}

interface DirectoryUser {
  id: string;
  email: string;
  display_name?: string;
  roles: string[];
}

const CalendarTaskManager = () => {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [selectedDate, setSelectedDate] = useState<Date | undefined>(new Date());
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [showEventDialog, setShowEventDialog] = useState(false);
  const [showTaskDialog, setShowTaskDialog] = useState(false);
  const [newEvent, setNewEvent] = useState({ title: "", description: "", event_type: "meeting", start_time: "", end_time: "", location: "", all_day: false });
  const [newTask, setNewTask] = useState({ title: "", description: "", priority: "medium", due_date: "", assigned_to: "" });
  const [assigneeSearch, setAssigneeSearch] = useState("");

  useRealtimeChannel("calendar_tasks", (message) => {
    const evt = message?.event;
    if (!evt) return;
    if (evt.startsWith("calendar_event_")) {
      queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
    }
    if (evt.startsWith("task_")) {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  // Fetch calendar events
  const { data: eventsData, isLoading: eventsLoading } = useQuery({
    queryKey: ["calendar-events", currentMonth.toISOString().slice(0, 7)],
    queryFn: () => api.calendar.list(currentMonth.toISOString().slice(0, 7)),
  });

  // Fetch tasks
  const { data: tasksData, isLoading: tasksLoading } = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api.tasks.list(),
  });

  // Fetch user directory for assignment dropdown (admins/managers)
  const { data: directoryData } = useQuery({
    queryKey: ["user-directory"],
    queryFn: () => api.users.directory(),
    staleTime: 300_000,
  });
  const directoryUsers: DirectoryUser[] = (directoryData as any) ?? [];
  const filteredUsers = assigneeSearch.trim()
    ? directoryUsers.filter((u) =>
        (u.display_name || u.email).toLowerCase().includes(assigneeSearch.toLowerCase())
      )
    : directoryUsers;

  const events = (eventsData as { events?: CalendarEvent[] })?.events ?? [];
  const tasks = (tasksData as { tasks?: Task[] })?.tasks ?? [];

  // Events for selected date
  const selectedDateEvents = useMemo(() => {
    if (!selectedDate) return [];
    const dateStr = selectedDate.toISOString().slice(0, 10);
    return events.filter((e) => e.start_time.startsWith(dateStr));
  }, [events, selectedDate]);

  // Tasks grouped by status
  const tasksByStatus = useMemo(() => {
    const pending = tasks.filter((t) => t.status === "pending" || t.status === "in_progress");
    const completed = tasks.filter((t) => t.status === "completed");
    return { pending, completed };
  }, [tasks]);

  // Create event mutation
  const createEventMutation = useMutation({
    mutationFn: (data: typeof newEvent) => api.calendar.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
      toast({ title: "Event created", description: "Your event has been added to the calendar." });
      setShowEventDialog(false);
      setNewEvent({ title: "", description: "", event_type: "meeting", start_time: "", end_time: "", location: "", all_day: false });
    },
    onError: (e: any) => {
      toast({ title: "Error", description: e?.message || "Failed to create event", variant: "destructive" });
    },
  });

  // Create task mutation
  const createTaskMutation = useMutation({
    mutationFn: (data: typeof newTask) => api.tasks.create(data),
    onSuccess: (_res, vars) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      const assignedTo = vars.assigned_to;
      const assigneeName = assignedTo
        ? directoryUsers.find((u) => u.id === assignedTo)?.display_name ||
          directoryUsers.find((u) => u.id === assignedTo)?.email ||
          "team member"
        : null;
      toast({
        title: "Task created",
        description: assigneeName
          ? `Task assigned to ${assigneeName}`
          : "Task added to your list.",
      });
      setShowTaskDialog(false);
      setNewTask({ title: "", description: "", priority: "medium", due_date: "", assigned_to: "" });
      setAssigneeSearch("");
    },
    onError: (e: any) => {
      toast({ title: "Error", description: e?.message || "Failed to create task", variant: "destructive" });
    },
  });

  // Update task status mutation
  const updateTaskMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.tasks.update(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  // Delete task mutation
  const deleteTaskMutation = useMutation({
    mutationFn: (id: string) => api.tasks.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      toast({ title: "Task deleted" });
    },
  });

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case "critical": return "bg-destructive/10 text-destructive border-destructive/20";
      case "high": return "bg-warning/15 text-warning border-warning/30";
      case "medium": return "bg-info/15 text-info border-info/30";
      case "low": return "bg-muted text-muted-foreground border-border/40";
      default: return "bg-muted text-muted-foreground";
    }
  };

  const getEventTypeColor = (type: string) => {
    switch (type) {
      case "meeting": return "bg-info";
      case "deadline": return "bg-destructive";
      case "reminder": return "bg-warning";
      case "holiday": return "bg-success";
      default: return "bg-muted-foreground";
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <CalendarIcon className="h-6 w-6 text-primary" />
            Calendar & Tasks
          </h1>
          <p className="text-muted-foreground mt-1">Schedule events and manage your tasks</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setShowEventDialog(true)} variant="outline">
            <Plus className="h-4 w-4 mr-2" />
            New Event
          </Button>
          <Button onClick={() => setShowTaskDialog(true)}>
            <ListTodo className="h-4 w-4 mr-2" />
            New Task
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Calendar Section */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-4">
            <div className="flex items-center justify-between">
              <CardTitle>Company Calendar</CardTitle>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-sm font-medium min-w-[120px] text-center">
                  {currentMonth.toLocaleDateString("en-US", { month: "long", year: "numeric" })}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1))}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <Calendar
              mode="single"
              selected={selectedDate}
              onSelect={setSelectedDate}
              month={currentMonth}
              onMonthChange={setCurrentMonth}
              className="rounded-md border w-full"
              modifiers={{
                hasEvent: events.map((e) => new Date(e.start_time)),
              }}
              modifiersStyles={{
                hasEvent: { fontWeight: "bold", textDecoration: "underline", color: "hsl(var(--primary))" },
              }}
            />

            {/* Selected Date Events */}
            {selectedDate && (
              <div className="mt-6 pt-4 border-t">
                <h3 className="font-semibold mb-3 flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  Events for {selectedDate.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" })}
                </h3>
                {selectedDateEvents.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No events scheduled for this day.</p>
                ) : (
                  <div className="space-y-2">
                    {selectedDateEvents.map((event) => (
                      <div key={event.id} className="pw-surface-base flex items-center gap-3 rounded-xl p-3">
                        <div className={`w-2 h-2 rounded-full ${getEventTypeColor(event.event_type)}`} />
                        <div className="flex-1">
                          <p className="font-medium text-sm">{event.title}</p>
                          {event.location && <p className="text-xs text-muted-foreground">{event.location}</p>}
                        </div>
                        <Badge variant="outline" className="text-xs">
                          {event.all_day ? "All day" : new Date(event.start_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Tasks Section */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ListTodo className="h-5 w-5" />
              Tasks
            </CardTitle>
            <CardDescription>{tasksByStatus.pending.length} pending tasks</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="pending" className="w-full">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="pending">Pending</TabsTrigger>
                <TabsTrigger value="completed">Completed</TabsTrigger>
              </TabsList>

              <TabsContent value="pending" className="mt-4 space-y-3">
                {tasksLoading ? (
                  <p className="text-sm text-muted-foreground">Loading...</p>
                ) : tasksByStatus.pending.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">No pending tasks!</p>
                ) : (
                  tasksByStatus.pending.map((task) => (
                    <div key={task.id} className="p-3 rounded-xl border border-border/50 bg-background/70 hover:bg-muted/50 transition-colors group">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-start gap-3 flex-1">
                          <button
                            className="mt-0.5 h-5 w-5 rounded-full border-2 border-primary flex items-center justify-center hover:bg-primary hover:text-primary-foreground transition-colors"
                            onClick={() => updateTaskMutation.mutate({ id: task.id, status: "completed" })}
                          >
                            <Check className="h-3 w-3 opacity-0 group-hover:opacity-100" />
                          </button>
                          <div className="flex-1">
                            <p className="text-sm font-medium">{task.title}</p>
                            {task.description && <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{task.description}</p>}
                            <div className="flex flex-wrap items-center gap-2 mt-2">
                              <Badge variant="outline" className={`text-xs ${getPriorityColor(task.priority)}`}>
                                <Flag className="h-3 w-3 mr-1" />
                                {task.priority}
                              </Badge>
                              {task.due_date && (
                                <span className="text-xs text-muted-foreground flex items-center gap-1">
                                  <Clock className="h-3 w-3" />
                                  {new Date(task.due_date).toLocaleDateString()}
                                </span>
                              )}
                              {task.assigned_to && (
                                <span className="text-xs text-muted-foreground flex items-center gap-1">
                                  <UserCheck className="h-3 w-3 text-primary" />
                                  {directoryUsers.find((u) => u.id === task.assigned_to)?.display_name ||
                                    directoryUsers.find((u) => u.id === task.assigned_to)?.email ||
                                    task.assigned_to}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-7 w-7 opacity-0 group-hover:opacity-100">
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => updateTaskMutation.mutate({ id: task.id, status: "in_progress" })}>
                              Mark In Progress
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => updateTaskMutation.mutate({ id: task.id, status: "completed" })}>
                              Mark Complete
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="text-destructive"
                              onClick={() => deleteTaskMutation.mutate(task.id)}
                            >
                              <Trash2 className="h-4 w-4 mr-2" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </div>
                  ))
                )}
              </TabsContent>

              <TabsContent value="completed" className="mt-4 space-y-3">
                {tasksByStatus.completed.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">No completed tasks yet.</p>
                ) : (
                  tasksByStatus.completed.slice(0, 10).map((task) => (
                    <div key={task.id} className="p-3 rounded-xl border border-border/40 bg-muted/30 opacity-60">
                      <div className="flex items-center gap-3">
                        <Check className="h-4 w-4 text-success" />
                        <p className="text-sm line-through">{task.title}</p>
                      </div>
                    </div>
                  ))
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>

      {/* New Event Dialog */}
      <Dialog open={showEventDialog} onOpenChange={setShowEventDialog}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>Create New Event</DialogTitle>
            <DialogDescription>Add an event to the company calendar.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <label className="text-sm font-medium">Title</label>
              <Input
                placeholder="Event title"
                value={newEvent.title}
                onChange={(e) => setNewEvent({ ...newEvent, title: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">Description</label>
              <Textarea
                placeholder="Event description (optional)"
                value={newEvent.description}
                onChange={(e) => setNewEvent({ ...newEvent, description: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <label className="text-sm font-medium">Type</label>
                <Select value={newEvent.event_type} onValueChange={(v) => setNewEvent({ ...newEvent, event_type: v })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="meeting">Meeting</SelectItem>
                    <SelectItem value="deadline">Deadline</SelectItem>
                    <SelectItem value="reminder">Reminder</SelectItem>
                    <SelectItem value="holiday">Holiday</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium">Location</label>
                <Input
                  placeholder="Office / Zoom link"
                  value={newEvent.location}
                  onChange={(e) => setNewEvent({ ...newEvent, location: e.target.value })}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <label className="text-sm font-medium">Start</label>
                <Input
                  type="datetime-local"
                  value={newEvent.start_time}
                  onChange={(e) => setNewEvent({ ...newEvent, start_time: e.target.value })}
                />
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium">End (optional)</label>
                <Input
                  type="datetime-local"
                  value={newEvent.end_time}
                  onChange={(e) => setNewEvent({ ...newEvent, end_time: e.target.value })}
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEventDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createEventMutation.mutate(newEvent)}
              disabled={!newEvent.title || !newEvent.start_time || createEventMutation.isPending}
            >
              {createEventMutation.isPending ? "Creating..." : "Create Event"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Task Dialog */}
      <Dialog open={showTaskDialog} onOpenChange={(o) => { setShowTaskDialog(o); if (!o) { setAssigneeSearch(""); } }}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>Create New Task</DialogTitle>
            <DialogDescription>Add a task and optionally assign it to a team member.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <label className="text-sm font-medium">Title *</label>
              <Input
                placeholder="Task title"
                value={newTask.title}
                onChange={(e) => setNewTask({ ...newTask, title: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">Description</label>
              <Textarea
                placeholder="Task details (optional)"
                value={newTask.description}
                onChange={(e) => setNewTask({ ...newTask, description: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <label className="text-sm font-medium">Priority</label>
                <Select value={newTask.priority} onValueChange={(v) => setNewTask({ ...newTask, priority: v })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="critical">Critical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium">Due Date</label>
                <Input
                  type="datetime-local"
                  value={newTask.due_date}
                  onChange={(e) => setNewTask({ ...newTask, due_date: e.target.value })}
                />
              </div>
            </div>

            {/* ── Assign To ── */}
            <div className="grid gap-2">
              <label className="text-sm font-medium flex items-center gap-1">
                <User className="w-3.5 h-3.5" />
                Assign To
                <span className="text-muted-foreground font-normal">(optional)</span>
              </label>

              {/* Selected assignee pill */}
              {newTask.assigned_to && (
                <div className="flex items-center justify-between rounded-md border border-primary/40 bg-primary/5 px-3 py-1.5 text-sm">
                  <span className="flex items-center gap-1.5">
                    <UserCheck className="w-3.5 h-3.5 text-primary" />
                    {directoryUsers.find((u) => u.id === newTask.assigned_to)?.display_name ||
                      directoryUsers.find((u) => u.id === newTask.assigned_to)?.email ||
                      newTask.assigned_to}
                  </span>
                  <button
                    onClick={() => { setNewTask({ ...newTask, assigned_to: "" }); setAssigneeSearch(""); }}
                    className="text-muted-foreground hover:text-destructive text-xs"
                  >
                    ✕ clear
                  </button>
                </div>
              )}

              {/* Search + dropdown list */}
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground pointer-events-none" />
                <Input
                  className="pl-8"
                  placeholder="Search team members…"
                  value={assigneeSearch}
                  onChange={(e) => setAssigneeSearch(e.target.value)}
                />
              </div>
              {assigneeSearch.trim() && filteredUsers.length > 0 && (
                <div className="max-h-44 overflow-y-auto rounded-md border bg-popover shadow-md">
                  {filteredUsers.map((u) => (
                    <button
                      key={u.id}
                      type="button"
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted text-left transition-colors"
                      onClick={() => {
                        setNewTask({ ...newTask, assigned_to: u.id });
                        setAssigneeSearch("");
                      }}
                    >
                      <User className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                      <span className="truncate">{u.display_name || u.email}</span>
                      <span className="ml-auto text-xs text-muted-foreground shrink-0">
                        {u.roles.join(", ")}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {assigneeSearch.trim() && filteredUsers.length === 0 && (
                <p className="text-xs text-muted-foreground pl-1">No matching team members found.</p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setShowTaskDialog(false); setAssigneeSearch(""); }}>
              Cancel
            </Button>
            <Button
              onClick={() => createTaskMutation.mutate(newTask)}
              disabled={!newTask.title || createTaskMutation.isPending}
            >
              {createTaskMutation.isPending ? "Creating..." : newTask.assigned_to ? "Assign Task" : "Create Task"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
};

export default CalendarTaskManager;

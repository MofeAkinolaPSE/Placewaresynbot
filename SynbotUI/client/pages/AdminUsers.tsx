import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { motion } from "framer-motion";
import { askConfirm, askText } from "@/lib/ask";
import { motionTransitions } from "@/lib/motion";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { AccessPreview, defaultDepartment, RoleDef, RolePicker } from "@/components/admin/RolePicker";
import { BranchPicker } from "@/components/admin/BranchPicker";
import { TourPreview } from "@/components/tour/TourPreview";

type UserRecord = {
  id: string;
  email: string;
  roles: string[];
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
  home_entity_id?: string | null;
  extra_entity_ids?: string[] | null;
};

const DEFAULT_ATTESTATION = "I attest this access management action is authorized and policy-compliant.";

// HR departments come from the server (GET /users/roles, staff_workspace.DEPARTMENTS) so
// they always match the database; this is only the fallback while it loads.
const FALLBACK_DEPARTMENTS = ["Finance", "Sales", "Frontdesk", "Operations", "Procurement", "Logistics", "Quality", "HR", "Management", "Admin"];

const parseRoles = (value: string): string[] =>
  value
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean);

const SPECIAL_CHARS = "!@#$%^&*()-_=+[]{};:,.?/";

function passwordStrengthError(pwd: string): string | null {
  if (pwd.length < 10) return "At least 10 characters";
  if (!/[a-z]/.test(pwd)) return "At least one lowercase letter";
  if (!/[A-Z]/.test(pwd)) return "At least one uppercase letter";
  if (!/[0-9]/.test(pwd)) return "At least one number";
  if (![...SPECIAL_CHARS].some((c) => pwd.includes(c)))
    return `At least one special character (${SPECIAL_CHARS})`;
  return null;
}

/**
 * Addresses are a single unbreakable token, so a narrow card breaks them
 * mid-word ("placeware.co / m"). A <wbr> at the @ gives the browser a sane
 * break point to prefer instead.
 */
function EmailText({ email, className }: { email: string; className?: string }) {
  const at = email.indexOf("@");
  if (at < 0) return <span className={className}>{email}</span>;
  return (
    <span className={className} title={email}>
      {email.slice(0, at)}
      <wbr />
      {email.slice(at)}
    </span>
  );
}

const AdminUsers = () => {
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();

  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRoles, setNewRoles] = useState("viewer");
  const [createReason, setCreateReason] = useState("");
  const [createAttestation, setCreateAttestation] = useState(DEFAULT_ATTESTATION);
  // Optional Staff Directory link -- when both are filled, POST /users also
  // creates a matching placeware_staff record so the account actually shows
  // up on the HR page. Previously nothing did this at all.
  const [newFullName, setNewFullName] = useState("");
  const [newDepartment, setNewDepartment] = useState("");
  const [newJobTitle, setNewJobTitle] = useState("");

  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [passwordUserId, setPasswordUserId] = useState<string>("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [statusReason, setStatusReason] = useState("");
  const [statusAttestation, setStatusAttestation] = useState(DEFAULT_ATTESTATION);
  const [passwordReason, setPasswordReason] = useState("");
  const [passwordAttestation, setPasswordAttestation] = useState(DEFAULT_ATTESTATION);

  const usersQuery = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.users.list(200),
  });
  const rolesQuery = useQuery({ queryKey: ["admin-roles"], queryFn: () => api.users.roles(), staleTime: 600_000 });
  const catalog: RoleDef[] = rolesQuery.data?.roles ?? [];
  const departments = rolesQuery.data?.departments ?? FALLBACK_DEPARTMENTS;
  const roleLabel = (k: string) => catalog.find((r) => r.key === k)?.label ?? k;
  // Branches (Lagos / Abuja): where each login works
  const branchesQuery = useQuery({ queryKey: ["branches", "all"], queryFn: () => api.branches.all(), staleTime: 600_000 });
  const branches = branchesQuery.data ?? [];
  const primaryBranch = branches.find((b) => b.is_primary)?.id ?? branches[0]?.id ?? "";
  const branchName = (id?: string | null) => branches.find((b) => b.id === id)?.branch_name ?? "";
  const [newHome, setNewHome] = useState("");
  const [newExtra, setNewExtra] = useState<string[]>([]);

  // Edit access (roles + branch) of an existing account
  const [accessUserId, setAccessUserId] = useState("");
  const [accessRoles, setAccessRoles] = useState<string[]>([]);
  const [accessReason, setAccessReason] = useState("");
  const [accessHome, setAccessHome] = useState("");
  const [accessExtra, setAccessExtra] = useState<string[]>([]);
  const openAccess = (u: UserRecord) => {
    setAccessUserId(u.id); setAccessRoles(u.roles); setAccessReason("");
    setAccessHome(u.home_entity_id || primaryBranch); setAccessExtra(u.extra_entity_ids || []);
  };
  const accessMutation = useMutation({
    mutationFn: async () => {
      const u = users.find((x) => x.id === accessUserId);
      const rolesChanged = !u || [...u.roles].sort().join(",") !== [...accessRoles].sort().join(",");
      const branchChanged = !!accessHome && (!u || (u.home_entity_id || primaryBranch) !== accessHome
        || [...(u.extra_entity_ids || [])].sort().join(",") !== [...accessExtra].sort().join(","));
      if (rolesChanged) await api.users.setRoles(accessUserId, accessRoles, accessReason.trim());
      if (branchChanged) await api.branches.setForUser(accessUserId, accessHome, accessExtra, accessReason.trim());
    },
    onSuccess: () => {
      toast.success("Access updated - it applies when their session next refreshes (or at their next sign-in)");
      setAccessUserId("");
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: any) => toast.error(error?.message || "Failed to update access"),
  });

  const users = useMemo<UserRecord[]>(() => {
    if (!Array.isArray(usersQuery.data)) return [];
    return usersQuery.data.filter((row: any) =>
      typeof row?.id === "string" &&
      typeof row?.email === "string" &&
      Array.isArray(row?.roles) &&
      typeof row?.is_active === "boolean",
    );
  }, [usersQuery.data]);

  const malformedCount = useMemo(() => {
    if (!Array.isArray(usersQuery.data)) return 0;
    return usersQuery.data.length - users.length;
  }, [usersQuery.data, users.length]);

  const createUserMutation = useMutation({
    mutationFn: () => {
      const roles = parseRoles(newRoles);
      return api.users.create({
        email: newEmail.trim().toLowerCase(),
        password: newPassword,
        roles,
        approval_reason: createReason.trim(),
        attestation_text: createAttestation.trim(),
        full_name: newFullName.trim() || undefined,
        department: newDepartment || undefined,
        job_title: newJobTitle.trim() || undefined,
        home_entity_id: (newHome || primaryBranch) || undefined,
        extra_entity_ids: newExtra,
      });
    },
    onSuccess: (data: any) => {
      if (data?.staff_link_warning) {
        toast.warning(data.staff_link_warning);
      } else if (data?.staff) {
        toast.success("User created and added to the Staff Directory");
      } else {
        toast.success("User created");
      }
      setNewEmail("");
      setNewPassword("");
      setNewRoles("viewer");
      setCreateReason("");
      setCreateAttestation(DEFAULT_ATTESTATION);
      setNewFullName("");
      setNewDepartment("");
      setNewJobTitle("");
      setNewHome("");
      setNewExtra([]);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: any) => {
      toast.error(error?.message || "Failed to create user");
    },
  });

  // Closing the box forgets the reason, so it never carries over to the next person
  const closeStatusChange = () => {
    setSelectedUserId("");
    setStatusReason("");
    setStatusAttestation(DEFAULT_ATTESTATION);
  };

  const statusMutation = useMutation({
    mutationFn: (params: { userId: string; nextActive: boolean }) =>
      api.users.setStatus(params.userId, {
        is_active: params.nextActive,
        approval_reason: statusReason.trim(),
        attestation_text: statusAttestation.trim(),
      }),
    onSuccess: (_, vars) => {
      toast.success(vars.nextActive ? "User activated" : "User deactivated");
      closeStatusChange();
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: any) => {
      toast.error(error?.message || "Failed to update user status");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (p: { userId: string; reason: string }) => api.users.remove(p.userId, { approval_reason: p.reason }),
    onSuccess: (r: any) => {
      toast.success(`Access deleted${r?.email ? ` - ${r.email}` : ""}`);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: any) => toast.error(error?.message || "Failed to delete user"),
  });
  const deleteUser = async (user: { id: string; email: string }) => {
    const ok = await askConfirm(`Delete the access for ${user.email}?\n\nThey can no longer sign in, and the login is removed from this list. ` +
      `Their HR profile, timesheets and tasks stay; posted records keep who did them.\n\nIf this person has left, use Deactivate instead - it keeps everything and can be undone.`);
    if (!ok) return;
    const reason = await askText(`Why is the access for ${user.email} being deleted? (kept in the audit trail)`);
    if (reason && reason.trim()) deleteMutation.mutate({ userId: user.id, reason: reason.trim() });
  };

  // Closing the box forgets what was typed, so one person's password or reason never carries over to the next
  const closePasswordReset = () => {
    setPasswordUserId("");
    setNewUserPassword("");
    setPasswordReason("");
    setPasswordAttestation(DEFAULT_ATTESTATION);
  };

  const passwordMutation = useMutation({
    mutationFn: (userId: string) =>
      api.users.resetPassword(userId, {
        password: newUserPassword,
        approval_reason: passwordReason.trim(),
        attestation_text: passwordAttestation.trim(),
      }),
    onSuccess: () => {
      toast.success("Password updated");
      closePasswordReset();
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: any) => {
      toast.error(error?.message || "Failed to update password");
    },
  });

  const pwdError = passwordStrengthError(newPassword);
  // Name / department / job title are optional: every login gets an HR profile automatically
  // (named from the email, department from the role) which HR can complete later.
  const canCreate =
    newEmail.trim().length > 0 &&
    pwdError === null &&
    parseRoles(newRoles).length > 0 &&
    createReason.trim().length > 0 &&
    createAttestation.trim().length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-8 p-8"
    >
      <div>
        <h1 className="text-3xl font-bold text-foreground">User Access Management</h1>
        <p className="text-muted-foreground mt-2">
          Manage user accounts, role assignments, credential resets, and activation status.
        </p>
      </div>

      <div className="pw-surface-interactive rounded-xl p-6 space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Create User</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Input
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="user@placeware.ng"
            aria-label="Email"
          />
          <div className="flex flex-col gap-1">
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Initial password"
              aria-label="Password"
              aria-describedby="pw-hint"
            />
            <p id="pw-hint" className={`text-xs ${newPassword.length > 0 && pwdError ? "text-destructive" : "text-muted-foreground"}`}>
              {newPassword.length > 0 && pwdError
                ? `⚠️ ${pwdError}`
                : "Min 10 chars · uppercase · lowercase · number · special char"}
            </p>
          </div>
          <div className="space-y-2 md:col-span-2">
            <p className="text-sm font-medium text-foreground">Access - tick every role this person needs</p>
            {rolesQuery.isLoading ? <p className="text-xs text-muted-foreground">Loading roles…</p> : (
              <RolePicker catalog={catalog} value={parseRoles(newRoles)}
                onChange={(r) => {
                  setNewRoles(r.join(","));
                  const d = defaultDepartment(catalog, r);
                  if (d && (!newDepartment || newDepartment === defaultDepartment(catalog, parseRoles(newRoles)))) setNewDepartment(d);
                }} />
            )}
            <AccessPreview roles={parseRoles(newRoles)} />
            <BranchPicker branches={branches} home={newHome || primaryBranch} extra={newExtra} roles={parseRoles(newRoles)}
                          onChange={(h, x) => { setNewHome(h); setNewExtra(x); }} />
          </div>
          <Input
            value={createReason}
            onChange={(e) => setCreateReason(e.target.value)}
            placeholder="Approval reason"
            aria-label="Approval reason"
          />
        </div>

        <div className="pt-2 border-t">
          <p className="text-sm font-medium text-foreground">HR profile</p>
          <p className="text-xs text-muted-foreground mb-3">
            Every new account appears in HR → Staff directory and on the Team automatically. Fill these in now or let HR complete them later
            (the name is taken from the email and the department from the role until then).
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Input
              value={newFullName}
              onChange={(e) => setNewFullName(e.target.value)}
              placeholder="Full name"
              aria-label="Full name"
            />
            <Select value={newDepartment} onValueChange={setNewDepartment}>
              <SelectTrigger aria-label="Department">
                <SelectValue placeholder="Department" />
              </SelectTrigger>
              <SelectContent>
                {departments.map((d) => (
                  <SelectItem key={d} value={d}>{d}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={newJobTitle}
              onChange={(e) => setNewJobTitle(e.target.value)}
              placeholder="Job title (optional, e.g. Warehouse Lead)"
              aria-label="Job title"
            />
          </div>
        </div>

        <Textarea
          value={createAttestation}
          onChange={(e) => setCreateAttestation(e.target.value)}
          className="min-h-20"
          aria-label="Attestation text"
        />
        <Button
          onClick={() => createUserMutation.mutate()}
          disabled={!canCreate || createUserMutation.isPending}
        >
          {createUserMutation.isPending ? "Creating..." : "Create User"}
        </Button>
      </div>

      <TourPreview />

      <div className="pw-surface-interactive rounded-xl p-6 space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Current Users</h2>

        {usersQuery.isError && (
          <p className="text-sm text-destructive">Data error: {(usersQuery.error as Error)?.message || "Failed to load users."}</p>
        )}

        {!usersQuery.isError && malformedCount > 0 && (
          <p className="text-sm text-destructive">
            Data error: {malformedCount} user record(s) are malformed and were excluded.
          </p>
        )}

        {!usersQuery.isLoading && !usersQuery.isError && users.length === 0 && (
          <p className="text-sm text-muted-foreground">No users found.</p>
        )}

        {isMobile ? (
          <div className="space-y-3">
            {users.map((user) => (
              <div key={user.id} className="rounded-xl border border-border/60 bg-card p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <EmailText
                    email={user.email}
                    className="min-w-0 flex-1 text-sm font-medium leading-snug [overflow-wrap:break-word]"
                  />
                  {/* shrink-0 + nowrap: without them the pill compresses to
                      its narrowest word and stacks "Act / ive". */}
                  <span
                    className={cn(
                      "shrink-0 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
                      user.is_active
                        ? "border-secondary/40 bg-secondary/15 text-success"
                        : "border-border bg-muted text-muted-foreground",
                    )}
                  >
                    {user.is_active ? "active" : "inactive"}
                  </span>
                </div>
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Access: <span className="text-foreground/80">{user.roles.map(roleLabel).join(", ") || "—"}</span>
                </p>
                {/* Buttons share the row when both fit and wrap to their own
                    line when they don't -- "Reset Password" cannot shrink. */}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="min-w-[7.5rem] flex-1"
                    onClick={() => setSelectedUserId(user.id)}
                  >
                    {user.is_active ? "Deactivate" : "Activate"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="min-w-[7.5rem] flex-1"
                    onClick={() => setPasswordUserId(user.id)}
                  >
                    Reset Password
                  </Button>
                  <Button size="sm" variant="outline" className="min-w-[7.5rem] flex-1" onClick={() => openAccess(user)}>
                    Edit access
                  </Button>
                  <Button size="sm" variant="destructive" className="min-w-[7.5rem] flex-1" disabled={deleteMutation.isPending}
                          onClick={() => deleteUser(user)}>
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-10 min-w-[260px] bg-muted/90">Email</TableHead>
                  <TableHead className="min-w-[220px]">Roles</TableHead>
                  {branches.length > 1 && <TableHead className="min-w-[120px]">Branch</TableHead>}
                  <TableHead className="min-w-[100px]">Status</TableHead>
                  <TableHead className="min-w-[240px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="sticky left-0 z-10 bg-background font-medium">
                      <EmailText email={user.email} />
                    </TableCell>
                    <TableCell>{user.roles.map(roleLabel).join(", ")}</TableCell>
                    {branches.length > 1 && (
                      <TableCell>
                        {user.roles.some((r) => r === "admin" || r === "management")
                          ? "All branches"
                          : [branchName(user.home_entity_id || primaryBranch), ...(user.extra_entity_ids || []).map(branchName)].filter(Boolean).join(" + ")}
                      </TableCell>
                    )}
                    <TableCell>{user.is_active ? "active" : "inactive"}</TableCell>
                    <TableCell className="space-x-2">
                      <Button
                        variant="outline"
                        onClick={() => setSelectedUserId(user.id)}
                      >
                        {user.is_active ? "Deactivate" : "Activate"}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => setPasswordUserId(user.id)}
                      >
                        Reset Password
                      </Button>
                      <Button variant="outline" onClick={() => openAccess(user)}>Edit access</Button>
                      <Button variant="destructive" disabled={deleteMutation.isPending} onClick={() => deleteUser(user)}>Delete</Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <Dialog open={!!accessUserId} onOpenChange={(open) => { if (!open) setAccessUserId(""); }}>
        {/* the role list is long: the box scrolls inside the screen */}
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit access</DialogTitle>
            <DialogDescription>
              {users.find((u) => u.id === accessUserId)?.email} - tick every role this person needs; the preview shows the menus they will see. Choose the branch they work in.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <RolePicker catalog={catalog} value={accessRoles} onChange={setAccessRoles} />
            <AccessPreview roles={accessRoles} />
            <BranchPicker branches={branches} home={accessHome} extra={accessExtra} roles={accessRoles}
                          onChange={(h, x) => { setAccessHome(h); setAccessExtra(x); }} />
            <Input
              value={accessReason}
              onChange={(e) => setAccessReason(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && accessRoles.length && accessReason.trim() && !accessMutation.isPending) accessMutation.mutate();
              }}
              placeholder="Reason for the change (recorded in the audit log)"
              aria-label="Access change reason"
            />
          </div>
          {/* stays in view while the roles scroll */}
          <DialogFooter className="sticky -bottom-6 -mb-6 gap-2 border-t bg-background py-4">
            <Button type="button" variant="ghost" onClick={() => setAccessUserId("")}>Cancel</Button>
            <Button type="button" onClick={() => accessMutation.mutate()} disabled={accessMutation.isPending || !accessRoles.length || !accessReason.trim()}>
              {accessMutation.isPending ? "Saving..." : "Save access"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {(() => {
        const target = users.find((u) => u.id === selectedUserId);
        const verb = target?.is_active ? "Deactivate" : "Activate";
        return (
          <Dialog open={!!selectedUserId} onOpenChange={(open) => { if (!open) closeStatusChange(); }}>
            <DialogContent className="max-w-lg">
              <form
                className="space-y-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!target) {
                    toast.error("Selected user not found");
                    return;
                  }
                  if (!statusReason.trim() || !statusAttestation.trim()) {
                    toast.error("Approval reason and attestation are required");
                    return;
                  }
                  statusMutation.mutate({ userId: target.id, nextActive: !target.is_active });
                }}
              >
                <DialogHeader>
                  <DialogTitle>{verb} user</DialogTitle>
                  <DialogDescription>
                    {target?.email} - {target?.is_active
                      ? "they can no longer sign in and are signed out on their next click. Their records stay, and Activate undoes this."
                      : "they can sign in again with their existing password."}
                  </DialogDescription>
                </DialogHeader>
                <Input
                  autoFocus
                  value={statusReason}
                  onChange={(e) => setStatusReason(e.target.value)}
                  placeholder="Approval reason"
                  aria-label="Status approval reason"
                />
                <Textarea
                  value={statusAttestation}
                  onChange={(e) => setStatusAttestation(e.target.value)}
                  className="min-h-20"
                  aria-label="Status attestation"
                />
                <DialogFooter className="gap-2">
                  <Button type="button" variant="ghost" onClick={closeStatusChange}>Cancel</Button>
                  <Button type="submit" disabled={statusMutation.isPending}>
                    {statusMutation.isPending ? "Saving..." : `${verb} user`}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        );
      })()}

      <Dialog open={!!passwordUserId} onOpenChange={(open) => { if (!open) closePasswordReset(); }}>
        <DialogContent className="max-w-lg">
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!newUserPassword.trim()) {
                toast.error("New password is required");
                return;
              }
              if (!passwordReason.trim() || !passwordAttestation.trim()) {
                toast.error("Approval reason and attestation are required");
                return;
              }
              passwordMutation.mutate(passwordUserId);
            }}
          >
            <DialogHeader>
              <DialogTitle>Reset User Password</DialogTitle>
              <DialogDescription>
                {users.find((u) => u.id === passwordUserId)?.email} - they are signed out everywhere and use the new password from their next sign-in.
              </DialogDescription>
            </DialogHeader>
            <Input
              type="password"
              autoFocus
              autoComplete="new-password"
              value={newUserPassword}
              onChange={(e) => setNewUserPassword(e.target.value)}
              placeholder="New password"
              aria-label="New password"
            />
            <Input
              value={passwordReason}
              onChange={(e) => setPasswordReason(e.target.value)}
              placeholder="Approval reason"
              aria-label="Password approval reason"
            />
            <Textarea
              value={passwordAttestation}
              onChange={(e) => setPasswordAttestation(e.target.value)}
              className="min-h-20"
              aria-label="Password reset attestation"
            />
            <DialogFooter className="gap-2">
              <Button type="button" variant="ghost" onClick={closePasswordReset}>Cancel</Button>
              <Button type="submit" disabled={passwordMutation.isPending}>
                {passwordMutation.isPending ? "Resetting…" : "Confirm Password Reset"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
};

export default AdminUsers;

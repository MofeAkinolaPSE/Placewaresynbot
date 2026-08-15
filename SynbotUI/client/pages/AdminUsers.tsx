import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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
import { motionTransitions } from "@/lib/motion";
import { useIsMobile } from "@/hooks/use-mobile";

type UserRecord = {
  id: string;
  email: string;
  roles: string[];
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
};

const DEFAULT_ATTESTATION = "I attest this access management action is authorized and policy-compliant.";

// Must match placeware_staff's CHECK constraint exactly (backend/migrations/
// 000_full_schema_with_rls.sql) -- these are Staff Directory departments,
// a different concept from the Access Role select below (which controls
// RBAC via `roles`, not the HR directory).
const STAFF_DEPARTMENTS = ["Finance", "Sales", "Operations", "HR", "Management"];

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
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: any) => {
      toast.error(error?.message || "Failed to create user");
    },
  });

  const statusMutation = useMutation({
    mutationFn: (params: { userId: string; nextActive: boolean }) =>
      api.users.setStatus(params.userId, {
        is_active: params.nextActive,
        approval_reason: statusReason.trim(),
        attestation_text: statusAttestation.trim(),
      }),
    onSuccess: (_, vars) => {
      toast.success(vars.nextActive ? "User activated" : "User deactivated");
      setSelectedUserId("");
      setStatusReason("");
      setStatusAttestation(DEFAULT_ATTESTATION);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: any) => {
      toast.error(error?.message || "Failed to update user status");
    },
  });

  const passwordMutation = useMutation({
    mutationFn: (userId: string) =>
      api.users.resetPassword(userId, {
        password: newUserPassword,
        approval_reason: passwordReason.trim(),
        attestation_text: passwordAttestation.trim(),
      }),
    onSuccess: () => {
      toast.success("Password updated");
      setPasswordUserId("");
      setNewUserPassword("");
      setPasswordReason("");
      setPasswordAttestation(DEFAULT_ATTESTATION);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: any) => {
      toast.error(error?.message || "Failed to update password");
    },
  });

  const pwdError = passwordStrengthError(newPassword);
  // Staff Directory link is optional as a pair -- either both full name and
  // department are filled, or neither. Matches POST /users' own 400 case.
  const staffLinkIncomplete = Boolean(newFullName.trim()) !== Boolean(newDepartment);
  const canCreate =
    newEmail.trim().length > 0 &&
    pwdError === null &&
    parseRoles(newRoles).length > 0 &&
    createReason.trim().length > 0 &&
    createAttestation.trim().length > 0 &&
    !staffLinkIncomplete;

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
          <Select value={newRoles} onValueChange={(v) => setNewRoles(v)}>
            <SelectTrigger aria-label="Roles">
              <SelectValue placeholder="Select role" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="viewer">Viewer</SelectItem>
              <SelectItem value="sales">Sales</SelectItem>
              <SelectItem value="hr">HR</SelectItem>
              <SelectItem value="ops">Operations</SelectItem>
              <SelectItem value="finance">Finance</SelectItem>
              <SelectItem value="quality_assurance">Quality Assurance</SelectItem>
              <SelectItem value="management">Management</SelectItem>
              <SelectItem value="admin">Admin</SelectItem>
            </SelectContent>
          </Select>
          <Input
            value={createReason}
            onChange={(e) => setCreateReason(e.target.value)}
            placeholder="Approval reason"
            aria-label="Approval reason"
          />
        </div>

        <div className="pt-2 border-t">
          <p className="text-sm font-medium text-foreground">Staff Directory link (optional)</p>
          <p className="text-xs text-muted-foreground mb-3">
            Fill in both name and department to also create a matching card on the HR Staff Directory page. Leave both blank to create a login-only account (e.g. a service/rider account).
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
                {STAFF_DEPARTMENTS.map((d) => (
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
          {staffLinkIncomplete && (
            <p className="text-xs text-destructive mt-1">
              Provide both full name and department to link a staff record, or clear both.
            </p>
          )}
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
              <div key={user.id} className="rounded-lg border bg-card p-3">
                <div className="flex items-start justify-between gap-3">
                  <p className="font-medium break-all leading-tight">{user.email}</p>
                  <span className="rounded-full border px-2 py-0.5 text-xs capitalize">{user.is_active ? "active" : "inactive"}</span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">Roles: {user.roles.join(", ")}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setSelectedUserId(user.id)}
                  >
                    {user.is_active ? "Deactivate" : "Activate"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setPasswordUserId(user.id)}
                  >
                    Reset Password
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
                  <TableHead className="min-w-[100px]">Status</TableHead>
                  <TableHead className="min-w-[240px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="sticky left-0 z-10 bg-background font-medium">{user.email}</TableCell>
                    <TableCell>{user.roles.join(", ")}</TableCell>
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
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {selectedUserId && (
        <div className="pw-surface-interactive rounded-xl p-6 space-y-4">
          <h2 className="text-lg font-semibold text-foreground">Confirm Status Change</h2>
          <Input
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
          <div className="flex gap-3">
            <Button
              onClick={() => {
                const target = users.find((u) => u.id === selectedUserId);
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
              disabled={statusMutation.isPending}
            >
              Confirm
            </Button>
            <Button variant="ghost" onClick={() => setSelectedUserId("")}>Cancel</Button>
          </div>
        </div>
      )}

      {passwordUserId && (
        <div className="pw-surface-interactive rounded-xl p-6 space-y-4">
          <h2 className="text-lg font-semibold text-foreground">Reset User Password</h2>
          <Input
            type="password"
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
          <div className="flex gap-3">
            <Button
              onClick={() => {
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
              disabled={passwordMutation.isPending}
            >
              Confirm Password Reset
            </Button>
            <Button variant="ghost" onClick={() => setPasswordUserId("")}>Cancel</Button>
          </div>
        </div>
      )}
    </motion.div>
  );
};

export default AdminUsers;

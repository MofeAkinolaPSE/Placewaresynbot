import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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

type UserRecord = {
  id: string;
  email: string;
  roles: string[];
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
};

const DEFAULT_ATTESTATION = "I attest this access management action is authorized and policy-compliant.";

const parseRoles = (value: string): string[] =>
  value
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean);

const AdminUsers = () => {
  const queryClient = useQueryClient();

  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRoles, setNewRoles] = useState("viewer");
  const [createReason, setCreateReason] = useState("");
  const [createAttestation, setCreateAttestation] = useState(DEFAULT_ATTESTATION);

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
      });
    },
    onSuccess: () => {
      toast.success("User created");
      setNewEmail("");
      setNewPassword("");
      setNewRoles("viewer");
      setCreateReason("");
      setCreateAttestation(DEFAULT_ATTESTATION);
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

  const canCreate =
    newEmail.trim().length > 0 &&
    newPassword.length > 0 &&
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
          <Input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="Initial password"
            aria-label="Password"
          />
          <Input
            value={newRoles}
            onChange={(e) => setNewRoles(e.target.value)}
            placeholder="viewer, finance"
            aria-label="Roles"
          />
          <Input
            value={createReason}
            onChange={(e) => setCreateReason(e.target.value)}
            placeholder="Approval reason"
            aria-label="Approval reason"
          />
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

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Roles</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((user) => (
              <TableRow key={user.id}>
                <TableCell className="font-medium">{user.email}</TableCell>
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

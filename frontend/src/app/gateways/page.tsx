"use client";

export const dynamic = "force-dynamic";

import { useMemo, useState } from "react";
import Link from "next/link";

import { useAuth } from "@/auth/clerk";
import { useQueryClient } from "@tanstack/react-query";

import { GatewaysTable } from "@/components/gateways/GatewaysTable";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { buttonVariants } from "@/components/ui/button";
import { ConfirmActionDialog } from "@/components/ui/confirm-action-dialog";

import { ApiError } from "@/api/mutator";
import {
  type listGatewaysApiV1GatewaysGetResponse,
  getListGatewaysApiV1GatewaysGetQueryKey,
  useDeleteGatewayApiV1GatewaysGatewayIdDelete,
  useListGatewaysApiV1GatewaysGet,
} from "@/api/generated/gateways/gateways";
import { createOptimisticListDeleteMutation } from "@/lib/list-delete";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import type { GatewayRead } from "@/api/generated/model";
import { useUrlSorting } from "@/lib/use-url-sorting";

const GATEWAY_SORTABLE_COLUMNS = ["name", "workspace_root", "updated_at"];

export default function GatewaysPage() {
  const { isSignedIn } = useAuth();
  const queryClient = useQueryClient();
  const { sorting, onSortingChange } = useUrlSorting({
    allowedColumnIds: GATEWAY_SORTABLE_COLUMNS,
    defaultSorting: [{ id: "name", desc: false }],
    paramPrefix: "gateways",
  });

  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const [deleteTarget, setDeleteTarget] = useState<GatewayRead | null>(null);

  const gatewaysKey = getListGatewaysApiV1GatewaysGetQueryKey();
  const gatewaysQuery = useListGatewaysApiV1GatewaysGet<
    listGatewaysApiV1GatewaysGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchInterval: 30_000,
      refetchOnMount: "always",
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
    },
  });

  const gateways = useMemo(
    () =>
      gatewaysQuery.data?.status === 200
        ? (gatewaysQuery.data.data.items ?? [])
        : [],
    [gatewaysQuery.data],
  );

  const deleteMutation = useDeleteGatewayApiV1GatewaysGatewayIdDelete<
    ApiError,
    { previous?: listGatewaysApiV1GatewaysGetResponse }
  >(
    {
      mutation: createOptimisticListDeleteMutation<
        GatewayRead,
        listGatewaysApiV1GatewaysGetResponse,
        { gatewayId: string }
      >({
        queryClient,
        queryKey: gatewaysKey,
        getItemId: (gateway) => gateway.id,
        getDeleteId: ({ gatewayId }) => gatewayId,
        onSuccess: () => {
          setDeleteTarget(null);
        },
        invalidateQueryKeys: [gatewaysKey],
      }),
    },
    queryClient,
  );

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate({ gatewayId: deleteTarget.id });
  };

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to view gateways.",
          forceRedirectUrl: "/gateways",
        }}
        title="Gateways"
        description="Manage OpenClaw gateway connections used by boards"
        headerActions={
          isAdmin && gateways.length > 0 ? (
            <Link
              href="/gateways/new"
              className={buttonVariants({
                size: "md",
                variant: "primary",
              })}
            >
              Create gateway
            </Link>
          ) : null
        }
        isAdmin={isAdmin}
        adminOnlyMessage="Only organization owners and admins can access gateways."
        stickyHeader
      >
        {/* What are Gateways — shown only when there are no gateways */}
        {!gatewaysQuery.isLoading && gateways.length === 0 && (
          <div className="mb-5 rounded-xl p-5 space-y-3" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
            <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>What are Gateways?</h2>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              A Gateway is a connection to a machine (local or remote) where your agents run code and Skills are installed.
              You only need a Gateway if you want to run Skills or active Agents — not for chat, memory, or workflows.
            </p>
            <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
              For local use, run the OpenClaw gateway process and point the URL to <span className="font-mono" style={{ color: "var(--text)" }}>http://localhost:8080</span>.
            </p>
          </div>
        )}

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <GatewaysTable
            gateways={gateways}
            isLoading={gatewaysQuery.isLoading}
            sorting={sorting}
            onSortingChange={onSortingChange}
            showActions
            stickyHeader
            onDelete={setDeleteTarget}
            emptyState={{
              title: "No gateways yet",
              description:
                "Create your first gateway to connect an execution environment. Gateways are where your Skills and Agents actually run.",
              actionHref: "/gateways/new",
              actionLabel: "Create your first gateway",
            }}
          />
        </div>

        {gatewaysQuery.error ? (
          <p className="mt-4 text-sm text-red-500">
            {gatewaysQuery.error.message}
          </p>
        ) : null}
      </DashboardPageLayout>

      <ConfirmActionDialog
        open={Boolean(deleteTarget)}
        onOpenChange={() => setDeleteTarget(null)}
        title="Delete gateway?"
        description={
          <>
            This removes the gateway connection from Mission Control. Boards
            using it will need a new gateway assigned.
          </>
        }
        errorMessage={deleteMutation.error?.message}
        errorStyle="text"
        cancelVariant="ghost"
        onConfirm={handleDelete}
        isConfirming={deleteMutation.isPending}
      />
    </>
  );
}

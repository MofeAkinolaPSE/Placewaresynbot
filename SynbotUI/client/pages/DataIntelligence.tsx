import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Database,
  Search,
  Link2,
  ListTree,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Shared badge helpers — reuses QualityControl.tsx's green/amber/red palette,
// not a new one.
// ---------------------------------------------------------------------------

function statusBadgeClass(status?: string): string {
  switch (status) {
    case "HEALTHY":
      return "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300";
    case "REVIEW_REQUIRED":
      return "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300";
    case "FAILED":
    case "ERROR":
      return "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300";
    default:
      return "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-white/70";
  }
}

function qualityBadgeClass(badge?: string): string {
  switch (badge) {
    case "green":
      return "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300";
    case "amber":
      return "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300";
    case "red":
      return "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300";
    default:
      return "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-white/70";
  }
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value}%`;
}

// ---------------------------------------------------------------------------
// Explorer tab
// ---------------------------------------------------------------------------

function ExplorerTab() {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [selected, setSelected] = useState<{ entityType: string; key: string } | null>(null);

  const { data: searchData, isFetching: searching } = useQuery({
    queryKey: ["data-intel-search", submittedQuery],
    queryFn: () => api.dataIntel.search(submittedQuery),
    enabled: submittedQuery.length > 0,
  });

  const { data: record, isFetching: loadingRecord } = useQuery({
    queryKey: ["data-intel-record", selected?.entityType, selected?.key],
    queryFn: () => api.dataIntel.record(selected!.entityType, selected!.key),
    enabled: !!selected,
  });

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Search</CardTitle>
          <CardDescription>Customers, vendors, items, GL accounts, invoices — by code, name, phone, or invoice #.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              placeholder="e.g. customer name, SKU, invoice number..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") setSubmittedQuery(query);
              }}
            />
            <Button onClick={() => setSubmittedQuery(query)} disabled={!query.trim()}>
              {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            </Button>
          </div>
          <div className="space-y-1 max-h-[420px] overflow-y-auto">
            {(searchData?.results || []).map((r: any, i: number) => (
              <button
                key={`${r.entity_type}-${r.key}-${i}`}
                onClick={() => setSelected({ entityType: r.entity_type, key: String(r.key) })}
                className="w-full text-left px-3 py-2 rounded-md border hover:bg-muted/60 transition-colors flex items-center justify-between gap-2"
              >
                <div>
                  <div className="text-sm font-medium">{r.label}</div>
                  <div className="text-xs text-muted-foreground">{r.subtitle}</div>
                </div>
                <Badge variant="outline" className="text-[10px] capitalize shrink-0">{r.entity_type}</Badge>
              </button>
            ))}
            {submittedQuery && !searching && (searchData?.results || []).length === 0 && (
              <p className="text-sm text-muted-foreground px-1 py-4">No matches for "{submittedQuery}".</p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Record Detail</CardTitle>
          <CardDescription>Canonical row, Bronze history, relationships, and developer trace.</CardDescription>
        </CardHeader>
        <CardContent>
          {!selected && <p className="text-sm text-muted-foreground">Select a search result to inspect it.</p>}
          {selected && loadingRecord && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
          {selected && record && (
            <div className="space-y-4 max-h-[480px] overflow-y-auto">
              <div className="flex items-center gap-2">
                <Badge className={qualityBadgeClass(record.quality_badge)}>{record.quality_badge?.toUpperCase()}</Badge>
                <span className="text-sm text-muted-foreground">
                  {record.entity_type} · {record.key}
                </span>
              </div>
              {record.quality_reasons?.length > 0 && (
                <ul className="text-xs text-amber-700 list-disc pl-4 space-y-0.5 dark:text-amber-300">
                  {record.quality_reasons.map((r: string, i: number) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}

              <div>
                <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">Canonical (Silver)</h4>
                <pre className="text-xs bg-muted/50 rounded-md p-2 overflow-x-auto">
                  {JSON.stringify(record.canonical, null, 2)}
                </pre>
              </div>

              <div>
                <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">
                  Related ({record.related?.length || 0})
                </h4>
                <div className="space-y-1">
                  {(record.related || []).map((rel: any) => (
                    <div key={rel.relationship} className="flex items-center justify-between text-xs border rounded px-2 py-1">
                      <span>{rel.description}</span>
                      <Badge variant="outline">{rel.count ?? "—"}</Badge>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">
                  Bronze history ({record.bronze_history?.length || 0} imports)
                </h4>
                <p className="text-xs text-muted-foreground">
                  Most recent {Math.min(record.bronze_history?.length || 0, 20)} raw snapshot rows for this key, newest first.
                </p>
              </div>

              <div>
                <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">Developer trace</h4>
                <div className="space-y-1">
                  {(record.developer_trace || []).map((t: any) => (
                    <div key={t.ace_column} className="text-xs border rounded px-2 py-1 flex items-center justify-between gap-2">
                      <span className="font-mono">{t.ace_column}</span>
                      <span className="text-muted-foreground truncate">{t.sage_column_candidates?.join(", ")}</span>
                      <Badge variant="outline">{pct(t.live_coverage_pct)}</Badge>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
          {selected && !loadingRecord && record && !record.found && (
            <p className="text-sm text-red-700 dark:text-red-300">Record not found in the Silver view.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field Coverage tab
// ---------------------------------------------------------------------------

function CoverageTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["data-intel-coverage"],
    queryFn: () => api.dataIntel.coverage(),
  });

  if (isLoading) return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;

  const renderEntities = (entities: any[], label: string) => (
    <div className="space-y-4">
      {entities?.map((e: any) => (
        <Card key={e.entity}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              {e.entity}
              <Badge variant="outline" className="font-mono text-[10px]">{e.target_table}</Badge>
              {e.silver_view && <Badge variant="outline" className="text-[10px]">view: {e.silver_view}</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ACE Column</TableHead>
                  <TableHead>Sage Column (candidates)</TableHead>
                  <TableHead className="text-right">Coverage</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {e.columns.map((c: any) => (
                  <TableRow key={c.ace_column}>
                    <TableCell className="font-mono text-xs">{c.ace_column}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {c.sage_column_candidates?.join(", ")}
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge
                        className={
                          c.coverage_pct === null
                            ? "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-white/70"
                            : c.coverage_pct >= 95
                            ? "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300"
                            : c.coverage_pct >= 50
                            ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                            : "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300"
                        }
                      >
                        {pct(c.coverage_pct)}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold mb-2">DAT-translated entities (historical migration)</h3>
        {renderEntities(data?.dat_translated_entities, "dat")}
      </div>
      <div>
        <h3 className="text-sm font-semibold mb-2">
          CSV-native entities (live import — near 1:1 passthrough, shown separately so it doesn't pad the numbers above)
        </h3>
        {renderEntities(data?.csv_native_entities, "csv")}
      </div>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-300" /> Known non-extractable fields
          </CardTitle>
          <CardDescription>Sage 50 source files that cannot (or could only partially) be extracted — tribal knowledge written down.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {data?.non_extractable_fields?.map((f: any) => (
            <div key={f.source} className="text-xs border rounded px-2 py-1.5 flex items-start justify-between gap-3">
              <div>
                <div className="font-mono">{f.source}</div>
                <div className="text-muted-foreground">{f.field_group}</div>
                <div className="text-muted-foreground">{f.reason}</div>
              </div>
              <Badge variant="outline" className="shrink-0">{f.status.replace(/_/g, " ")}</Badge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Relationship Audit tab
// ---------------------------------------------------------------------------

function RelationshipAuditTab() {
  const { data: score, isLoading: loadingScore } = useQuery({
    queryKey: ["data-intel-integrity-score"],
    queryFn: () => api.dataIntel.integrityScore(),
  });
  const { data: relationships, isLoading: loadingRel } = useQuery({
    queryKey: ["data-intel-relationships"],
    queryFn: () => api.dataIntel.relationships(),
  });
  const [orphanEdge, setOrphanEdge] = useState<string | null>(null);
  const { data: orphans } = useQuery({
    queryKey: ["data-intel-orphans", orphanEdge],
    queryFn: () => api.dataIntel.orphans(orphanEdge!, 20),
    enabled: !!orphanEdge,
  });

  if (loadingScore || loadingRel) return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Link2 className="h-4 w-4" /> Overall Integrity Score
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          <span className="text-3xl font-bold">{pct(score?.overall_score)}</span>
          <Badge className={statusBadgeClass(score?.status)}>{score?.status}</Badge>
          <span className="text-xs text-muted-foreground max-w-md">{score?.formula}</span>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Soft-relationship edges</CardTitle>
          <CardDescription>Untyped text-column linkage audited against Silver views, since this schema has few DB-enforced FKs.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Relationship</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Matched</TableHead>
                <TableHead className="text-right">Orphan</TableHead>
                <TableHead className="text-right">Coverage</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {relationships?.soft_relationships?.relationships?.map((e: any) => (
                <TableRow key={e.name}>
                  <TableCell>
                    <div className="text-sm">{e.description}</div>
                    <div className="text-xs text-muted-foreground font-mono">{e.name}</div>
                  </TableCell>
                  <TableCell className="text-right">{e.total_rows}</TableCell>
                  <TableCell className="text-right">{e.matched}</TableCell>
                  <TableCell className="text-right">{e.orphan}</TableCell>
                  <TableCell className="text-right">
                    <Badge className={statusBadgeClass(e.status)}>{pct(e.coverage_pct)}</Badge>
                  </TableCell>
                  <TableCell>
                    {e.orphan > 0 && (
                      <Button size="sm" variant="ghost" onClick={() => setOrphanEdge(e.name)}>
                        View
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {orphanEdge && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Orphan sample — {orphanEdge}</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted/50 rounded-md p-2 overflow-x-auto max-h-80">
              {JSON.stringify(orphans?.orphans, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Real (DB-enforced) foreign keys</CardTitle>
          <CardDescription>Expected to be few — most linkage in this schema is untyped text columns, audited above instead.</CardDescription>
        </CardHeader>
        <CardContent>
          {(relationships?.real_foreign_keys || []).length === 0 ? (
            <p className="text-sm text-muted-foreground">None found.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Table.Column</TableHead>
                  <TableHead>References</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {relationships?.real_foreign_keys?.map((fk: any) => (
                  <TableRow key={fk.constraint_name}>
                    <TableCell className="font-mono text-xs">{fk.table}.{fk.column}</TableCell>
                    <TableCell className="font-mono text-xs">{fk.references_table}.{fk.references_column}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table Classification tab
// ---------------------------------------------------------------------------

function TableClassificationTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["data-intel-tables"],
    queryFn: () => api.dataIntel.tables(),
  });

  if (isLoading) return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;

  const counts = data?.classification_counts || {};

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card><CardContent className="pt-4"><div className="text-2xl font-bold">{data?.total_public_tables}</div><div className="text-xs text-muted-foreground">Public tables</div></CardContent></Card>
        <Card><CardContent className="pt-4"><div className="text-2xl font-bold text-green-700 dark:text-green-300">{counts.Core || 0}</div><div className="text-xs text-muted-foreground">Core</div></CardContent></Card>
        <Card><CardContent className="pt-4"><div className="text-2xl font-bold text-amber-700 dark:text-amber-300">{counts.Unused || 0}</div><div className="text-xs text-muted-foreground">Unused candidates</div></CardContent></Card>
        <Card><CardContent className="pt-4"><div className="text-2xl font-bold text-muted-foreground">{data?.already_archived_count}</div><div className="text-xs text-muted-foreground">Already archived</div></CardContent></Card>
      </div>

      {(data?.unused_candidates || []).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-300" /> Unused candidates — review before archiving
            </CardTitle>
            <CardDescription>Report-only. Never auto-archived — a human must review and write the migration, exactly like the 11 tables migration 086 already archived.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1.5">
            {data.unused_candidates.map((t: string) => (
              <Badge key={t} className="bg-amber-100 text-amber-700 font-mono text-[10px] dark:bg-amber-500/15 dark:text-amber-300">{t}</Badge>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <ListTree className="h-4 w-4" /> All public tables
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Table</TableHead>
                <TableHead>Classification</TableHead>
                <TableHead>Referenced by</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.tables?.map((t: any) => (
                <TableRow key={t.table}>
                  <TableCell className="font-mono text-xs">{t.table}</TableCell>
                  <TableCell>
                    <Badge
                      className={
                        t.classification === "Core"
                          ? "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300"
                          : t.classification === "Referenced"
                          ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                          : "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300"
                      }
                    >
                      {t.classification}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {[...(t.router_refs || []), ...(t.service_refs || []), ...(t.migration_only_refs || [])]
                      .slice(0, 2)
                      .join(", ") || "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root page component
// ---------------------------------------------------------------------------

export default function DataIntelligence() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-full bg-blue-100 flex items-center justify-center dark:bg-blue-500/15">
          <Database className="h-5 w-5 text-blue-700 dark:text-blue-300" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Data Intelligence</h1>
          <p className="text-sm text-muted-foreground">
            Relationship auditing, field coverage, and record-level lineage across the ACE commercial schema
          </p>
        </div>
      </div>

      <Tabs defaultValue="explorer" className="space-y-6">
        <TabsList className="flex-wrap h-auto gap-1">
          <TabsTrigger value="explorer" className="flex items-center gap-1.5">
            <Search className="h-4 w-4" /> Explorer
          </TabsTrigger>
          <TabsTrigger value="coverage" className="flex items-center gap-1.5">
            <Database className="h-4 w-4" /> Field Coverage
          </TabsTrigger>
          <TabsTrigger value="relationships" className="flex items-center gap-1.5">
            <Link2 className="h-4 w-4" /> Relationship Audit
          </TabsTrigger>
          <TabsTrigger value="tables" className="flex items-center gap-1.5">
            <ListTree className="h-4 w-4" /> Table Classification
          </TabsTrigger>
        </TabsList>

        <TabsContent value="explorer"><ExplorerTab /></TabsContent>
        <TabsContent value="coverage"><CoverageTab /></TabsContent>
        <TabsContent value="relationships"><RelationshipAuditTab /></TabsContent>
        <TabsContent value="tables"><TableClassificationTab /></TabsContent>
      </Tabs>
    </div>
  );
}

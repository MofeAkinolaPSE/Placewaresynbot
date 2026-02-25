import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PlusCircle, Search, Filter } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export default function ProjectControls() {
  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Project Controls</h2>
          <p className="text-muted-foreground">
            Manage projects, deliveries, and stock orders.
          </p>
        </div>
        <div className="flex items-center space-x-2">
          <Button>
            <PlusCircle className="mr-2 h-4 w-4" />
            New Project
          </Button>
        </div>
      </div>
      <Tabs defaultValue="projects" className="space-y-4">
        <TabsList>
          <TabsTrigger value="projects">Active Projects</TabsTrigger>
          <TabsTrigger value="deliveries">Deliveries</TabsTrigger>
          <TabsTrigger value="stock_orders">Stock Orders</TabsTrigger>
        </TabsList>
        <TabsContent value="projects" className="space-y-4">
          <ProjectList />
        </TabsContent>
        <TabsContent value="deliveries" className="space-y-4">
          <DeliveryList />
        </TabsContent>
        <TabsContent value="stock_orders" className="space-y-4">
          <StockOrderList />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ProjectList() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Active Projects</CardTitle>
        <CardDescription>
          Overview of ongoing operational projects.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center py-4">
            <Input placeholder="Filter projects..." className="max-w-sm mr-4" />
            <Button variant="outline" size="icon"><Filter className="h-4 w-4" /></Button>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Project Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Start Date</TableHead>
              <TableHead>Due Date</TableHead>
              <TableHead className="text-right">Budget</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell className="font-medium">Vaccine Distribution Phase 1</TableCell>
              <TableCell><Badge>In Progress</Badge></TableCell>
              <TableCell>2026-01-15</TableCell>
              <TableCell>2026-06-30</TableCell>
              <TableCell className="text-right">$1,200,000</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="font-medium">Cold Chain Upgrade</TableCell>
              <TableCell><Badge variant="outline">Planning</Badge></TableCell>
              <TableCell>2026-03-01</TableCell>
              <TableCell>2026-09-01</TableCell>
              <TableCell className="text-right">$450,000</TableCell>
            </TableRow>
             <TableRow>
              <TableCell className="font-medium">Regional Warehouse Expansion</TableCell>
              <TableCell><Badge variant="secondary">On Hold</Badge></TableCell>
              <TableCell>2025-11-01</TableCell>
              <TableCell>2026-12-31</TableCell>
              <TableCell className="text-right">$2,100,000</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function DeliveryList() {
    return (
        <Card>
        <CardHeader>
            <CardTitle>Scheduled Deliveries</CardTitle>
            <CardDescription>
            Upcoming inbound and outbound shipments.
            </CardDescription>
        </CardHeader>
        <CardContent>
            <Table>
            <TableHeader>
                <TableRow>
                <TableHead>Ref ID</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Destination</TableHead>
                <TableHead>ETA</TableHead>
                <TableHead>Status</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                <TableRow>
                <TableCell>DLV-1023</TableCell>
                <TableCell>Outbound</TableCell>
                <TableCell>Lagos General Hospital</TableCell>
                <TableCell>Today, 14:00</TableCell>
                <TableCell><Badge className="bg-blue-500">In Transit</Badge></TableCell>
                </TableRow>
                <TableRow>
                <TableCell>DLV-1024</TableCell>
                <TableCell>Inbound</TableCell>
                <TableCell>Main Warehouse</TableCell>
                <TableCell>Tomorrow, 09:00</TableCell>
                <TableCell><Badge variant="outline">Scheduled</Badge></TableCell>
                </TableRow>
            </TableBody>
            </Table>
        </CardContent>
        </Card>
    )
}

function StockOrderList() {
    return (
        <Card>
        <CardHeader>
            <CardTitle>Stock Requisitions</CardTitle>
            <CardDescription>
            Pending stock orders and approvals.
            </CardDescription>
        </CardHeader>
        <CardContent>
            <Table>
            <TableHeader>
                <TableRow>
                <TableHead>Order ID</TableHead>
                <TableHead>Items</TableHead>
                <TableHead>Requester</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Status</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                <TableRow>
                <TableCell>SO-8821</TableCell>
                <TableCell>Pfizer COVID-19 (x500)</TableCell>
                <TableCell>Dr. Smith (Clinical Ops)</TableCell>
                <TableCell>2026-02-18</TableCell>
                <TableCell><Badge variant="destructive">Approval Required</Badge></TableCell>
                </TableRow>
                <TableRow>
                <TableCell>SO-8820</TableCell>
                <TableCell>Syringes 5ml (x2000)</TableCell>
                <TableCell>Inventory Mgr</TableCell>
                <TableCell>2026-02-17</TableCell>
                <TableCell><Badge className="bg-green-500">Approved</Badge></TableCell>
                </TableRow>
            </TableBody>
            </Table>
        </CardContent>
        </Card>
    )
}

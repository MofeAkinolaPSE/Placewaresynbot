import React from "react";
import LeadsQueue from "@/components/leads/LeadsQueue";
import WalkInForm from "@/components/leads/WalkInForm";

export default function LeadsPage() {
  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Leads</h1>
        <p className="text-muted-foreground">Manage incoming leads and record manual walk-ins.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <LeadsQueue />
        </div>
        <div className="lg:col-span-2">
          <div className="bg-card border rounded p-6">
            <h2 className="text-lg font-medium mb-4">Record Walk-in / Manual Lead</h2>
            <WalkInForm />
          </div>
        </div>
      </div>
    </div>
  );
}

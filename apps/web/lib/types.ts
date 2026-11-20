// Mirrors services/api/app/schemas (see docs/PRD.md "Contracts").

export interface Organization {
  id: string;
  name: string;
  region: string;
  is_sample: boolean;
}

// frontend/src/BootstrapPlaceholder.tsx
//
// Intentionally minimal placeholder component (Checkpoint 4 §28). Exists
// only to prove the React + TypeScript + Vite toolchain builds and mounts
// correctly. Contains no business logic, no dashboard, no trading UI —
// those begin at Checkpoint 14 (Frontend), once real application
// contracts exist to consume.
export function BootstrapPlaceholder(): JSX.Element {
  return (
    <main>
      <h1>IntraDay</h1>
      <p>
        Frontend tooling bootstrap (Checkpoint 4). No screens have been built
        yet — see docs/architecture/TECHNOLOGY_MAPPING.md and taskReport.md.
      </p>
    </main>
  );
}

// frontend/src/app/App.tsx
//
// Checkpoint 9: root application component. Replaces Checkpoint 4's
// BootstrapPlaceholder now that a real screen exists. No routing library
// is introduced yet - a single screen does not need one.
import { ConfigurationViewer } from "../features/configuration/ConfigurationViewer";

export function App(): JSX.Element {
  return (
    <main>
      <ConfigurationViewer />
    </main>
  );
}

// frontend/src/features/correlation/DecisionPipeline.tsx
//
// Checkpoint 64.80-F3 Phases 3, 8, 9, 10, 11: the reusable Decision
// Pipeline - Market Data, Features, Scanner, Strategy, Signal, Paper
// Trade, Outcome - rendered from the audited model in
// `correlationModel.ts` and from nothing else.
//
// WHAT THIS COMPONENT MAY NOT DO:
//  * It may not assert a relationship. Every relationship it renders is
//    read from PIPELINE_LINKS/SUPPLEMENTARY_LINKS, each of which carries
//    its API evidence, and the model's own test re-checks those field
//    names against the generated contract.
//  * It may not render a connector as if it were a working link. A
//    connector is styled from the link's STATUS, and the status word and
//    the explanation are always rendered as text.
//
// ACCESSIBILITY (Phase 11): the chain is an ordered list, so assistive
// technology receives the sequence without depending on visual position
// or on any arrow. Each stage announces its own outgoing relationship as
// a full sentence ("Market Data supplies the raw bar fields that
// Features are computed from."), and the decorative connector is
// aria-hidden so it is never announced as a meaningless glyph. Every
// navigation action is a real <button>, so keyboard users reach every
// destination in document order.
//
// VISUAL RESTRAINT (Phase 8/9): no @keyframes, no infinite animation, no
// `animation:` property - the same restraint 64.80-F2 established and
// its quality gate enforces. Connectors are static precision lines.
import type { JSX } from "react";

import { Icon } from "../../common/icons/Icon";
import { StatusBadge } from "../dashboard/StatusBadge";
import {
  PIPELINE_LINKS,
  PIPELINE_NODES,
  STATUS_MEANING,
  SUPPLEMENTARY_LINKS,
  nodeLabel,
  outgoingLink,
  statusDescriptor,
} from "./correlationModel";
import type { CorrelationLink, CorrelationStatus, PipelineDestination } from "./correlationModel";

/** Every status the model can produce, in the order the legend lists
 * them. Derived from STATUS_MEANING so a new status word cannot be added
 * to the vocabulary without appearing in the legend. */
const LEGEND_ORDER = Object.keys(STATUS_MEANING) as CorrelationStatus[];

export interface DecisionPipelineProps {
  /** Navigation into the EXISTING screens. This project has no router -
   * `App.tsx` holds one piece of screen state - so a destination is
   * requested by id and the shell performs the switch. Omitting this
   * renders the pipeline as a read-only diagram with no dead links. */
  onNavigate?: (destination: PipelineDestination) => void;
}

function LinkDetail({ link }: { link: CorrelationLink }): JSX.Element {
  return (
    <div className="pipeline-link" data-status={link.status}>
      <div className="pipeline-link__header">
        <span className="pipeline-link__pair">
          {nodeLabel(link.source)} to {nodeLabel(link.target)}
        </span>
        <StatusBadge status={statusDescriptor(link.status)} />
      </div>
      <p className="pipeline-link__relationship">{link.relationship}</p>
      <p className="pipeline-link__evidence">
        <span className="pipeline-link__evidence-label">API evidence: </span>
        {link.evidence}
      </p>
      {link.gap ? (
        <p className="pipeline-link__gap">
          <span className="pipeline-link__evidence-label">Gap: </span>
          {link.gap}
        </p>
      ) : null}
    </div>
  );
}

export function DecisionPipeline({ onNavigate }: DecisionPipelineProps): JSX.Element {
  return (
    <section className="pipeline" aria-labelledby="decision-pipeline-heading">
      <header className="pipeline__header">
        <p className="dashboard__eyebrow">
          <Icon name="signal" />
          Decision pipeline
        </p>
        <h2 id="decision-pipeline-heading">Market Data to Outcome</h2>
        <p className="pipeline__intro">
          How this platform moves from ingested market data toward a simulated trade decision.
          Each connection below states whether the relationship is actually exposed by an existing
          API, and names the endpoint and field that proves it. Connections that are not exposed
          are shown as gaps rather than drawn as if they worked. Nothing on this page is inferred.
        </p>
      </header>

      <ol className="pipeline__chain">
        {PIPELINE_NODES.map((node, index) => {
          const link = outgoingLink(node.id);
          return (
            <li className="pipeline__stage" key={node.id}>
              <article className="pipeline-node" aria-labelledby={`pipeline-node-${node.id}`}>
                <div className="pipeline-node__header">
                  <span className="pipeline-node__ordinal">Stage {index + 1}</span>
                  <h3 id={`pipeline-node-${node.id}`} className="pipeline-node__title">
                    <Icon name={node.icon} />
                    {node.label}
                  </h3>
                </div>
                <p className="pipeline-node__summary">{node.summary}</p>
                <ul className="pipeline-node__apis">
                  {node.apis.map((api) => (
                    <li key={api}>
                      <code>{api}</code>
                    </li>
                  ))}
                </ul>
                {node.destination && onNavigate ? (
                  <button
                    type="button"
                    className="dashboard__action"
                    onClick={() => onNavigate(node.destination as PipelineDestination)}
                  >
                    <Icon name={node.icon} />
                    {node.destinationLabel}
                  </button>
                ) : null}
                {node.destinationGap ? (
                  <p className="pipeline-node__summary">{node.destinationGap}</p>
                ) : null}
              </article>

              {link ? (
                <div className="pipeline__connector" data-status={link.status}>
                  {/* Decorative only. The relationship is carried by the
                      text below it, never by this rule. */}
                  <span className="pipeline__connector-rule" aria-hidden="true" />
                  <LinkDetail link={link} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>

      <section className="pipeline__section" aria-labelledby="pipeline-supplementary-heading">
        <h3 id="pipeline-supplementary-heading">Other audited relationships</h3>
        <p className="pipeline__intro">
          These relationships sit outside the single-file chain above. They were audited against
          the same contract and are reported here rather than omitted, because an omitted
          relationship reads as an absent one.
        </p>
        <div className="pipeline__link-list">
          {SUPPLEMENTARY_LINKS.map((link) => (
            <LinkDetail key={link.id} link={link} />
          ))}
        </div>
      </section>

      <section className="pipeline__section" aria-labelledby="pipeline-legend-heading">
        <h3 id="pipeline-legend-heading">What each status means</h3>
        <dl className="pipeline__legend">
          {LEGEND_ORDER.map((status) => (
            <div key={status} className="pipeline__legend-row">
              <dt>
                <StatusBadge status={statusDescriptor(status)} />
              </dt>
              <dd>{STATUS_MEANING[status]}</dd>
            </div>
          ))}
        </dl>
        <p className="pipeline__intro">
          Availability is not correlation, and correlation is not causal proof. A FOUND status
          means the API exposes a join between two records. It does not claim the upstream stage
          caused the downstream outcome.
        </p>
      </section>
    </section>
  );
}

/** Exposed so the honesty test can assert the rendered link set is
 * exactly the audited link set - no extra edge may be drawn. */
export const RENDERED_LINKS: CorrelationLink[] = [...PIPELINE_LINKS, ...SUPPLEMENTARY_LINKS];

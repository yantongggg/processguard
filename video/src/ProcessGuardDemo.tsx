import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

type Decision = 'ALLOW' | 'BLOCK' | 'WARN';
type DemoMode = 'compliant' | 'violation' | 'gray';
type NodeStatus = 'idle' | 'current' | 'completed' | 'blocked' | 'warned';
type NodeKey =
  | 'start'
  | 'verify_2fa'
  | 'amount'
  | 'fraud_check'
  | 'request_manager_approval'
  | 'join'
  | 'execute_refund'
  | 'write_audit_log'
  | 'end';

type AuditRow = {
  at: number;
  tool: string | null;
  decision: Decision;
  violation?: string;
  corrective?: string;
  judge?: {
    provider: string;
    verdict: Decision;
    confidence: number;
    rationale: string;
    correction?: string;
  };
};

const scenes = {
  problem: {start: 0, end: 30},
  solution: {start: 30, end: 75},
  compliant: {start: 75, end: 135},
  violation: {start: 135, end: 195},
  gray: {start: 195, end: 240},
  architecture: {start: 240, end: 280},
  human: {start: 280, end: 300},
};

const captions = [
  {
    start: 0,
    end: 30,
    text: 'AI agents are moving from chat to action. In regulated workflows, they cannot freestyle through approvals, 2FA, refunds, or audits.',
  },
  {
    start: 30,
    end: 75,
    text: 'ProcessGuard turns BPMN into runtime policy for agents: every tool call is checked before it leaves the runtime.',
  },
  {
    start: 75,
    end: 135,
    text: 'Live demo: a compliant refund follows the BPMN path. Nodes turn blue while active and green after completion.',
  },
  {
    start: 135,
    end: 195,
    text: 'Violation demo: skip_2fa_for_vip tries to jump straight to approval. ProcessGuard blocks it and marks the BPMN node red.',
  },
  {
    start: 195,
    end: 240,
    text: 'Gray zone: rules flag suspicious override language. The LLM judge records a verdict, confidence, rationale, and correction.',
  },
  {
    start: 240,
    end: 280,
    text: 'Architecture: UiPath or another agent runtime sends tool calls through ProcessGuard, BPMN policy, the LLM judge, and audit logging.',
  },
  {
    start: 280,
    end: 300,
    text: 'Human role: people define BPMN, approve workflows, review audit logs, and handle escalations.',
  },
];

const clamp01 = (value: number) => Math.max(0, Math.min(1, value));

const smooth = (value: number) => Easing.inOut(Easing.cubic)(clamp01(value));

const sceneOpacity = (time: number, start: number, end: number) => {
  const fadeIn = smooth((time - start) / 1.2);
  const fadeOut = smooth((end - time) / 1.2);
  return Math.min(fadeIn, fadeOut);
};

const currentCaption = (time: number) =>
  captions.find((caption) => time >= caption.start && time < caption.end) ?? captions[0];

export const ProcessGuardDemo: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const time = frame / fps;
  const caption = currentCaption(time);

  return (
    <AbsoluteFill className="video-root">
      <div className="grid-backdrop" />
      <div className="top-brand">
        <div className="brand-mark" />
        <div>
          <div className="brand-name">ProcessGuard</div>
          <div className="brand-subtitle">Runtime compliance firewall for AI agents</div>
        </div>
      </div>
      <Timer time={time} />

      <SceneLayer visible={time < scenes.problem.end} opacity={sceneOpacity(time, scenes.problem.start, scenes.problem.end)}>
        <ProblemScene localTime={time - scenes.problem.start} />
      </SceneLayer>

      <SceneLayer
        visible={time >= scenes.solution.start && time < scenes.solution.end}
        opacity={sceneOpacity(time, scenes.solution.start, scenes.solution.end)}
      >
        <SolutionScene localTime={time - scenes.solution.start} />
      </SceneLayer>

      <SceneLayer
        visible={time >= scenes.compliant.start && time < scenes.compliant.end}
        opacity={sceneOpacity(time, scenes.compliant.start, scenes.compliant.end)}
      >
        <DashboardScene
          heading="Live demo"
          subheading="compliant - $12,500 full flow"
          mode="compliant"
          localTime={time - scenes.compliant.start}
        />
      </SceneLayer>

      <SceneLayer
        visible={time >= scenes.violation.start && time < scenes.violation.end}
        opacity={sceneOpacity(time, scenes.violation.start, scenes.violation.end)}
      >
        <DashboardScene
          heading="Violation demo"
          subheading="skip_2fa_for_vip - $9,500"
          mode="violation"
          localTime={time - scenes.violation.start}
        />
      </SceneLayer>

      <SceneLayer
        visible={time >= scenes.gray.start && time < scenes.gray.end}
        opacity={sceneOpacity(time, scenes.gray.start, scenes.gray.end)}
      >
        <DashboardScene
          heading="Gray-zone demo"
          subheading="emergency override - $4,800"
          mode="gray"
          localTime={time - scenes.gray.start}
        />
      </SceneLayer>

      <SceneLayer
        visible={time >= scenes.architecture.start && time < scenes.architecture.end}
        opacity={sceneOpacity(time, scenes.architecture.start, scenes.architecture.end)}
      >
        <ArchitectureScene localTime={time - scenes.architecture.start} />
      </SceneLayer>

      <SceneLayer
        visible={time >= scenes.human.start}
        opacity={sceneOpacity(time, scenes.human.start, scenes.human.end)}
      >
        <HumanScene localTime={time - scenes.human.start} />
      </SceneLayer>

      <Caption text={caption.text} />
    </AbsoluteFill>
  );
};

const SceneLayer: React.FC<{visible: boolean; opacity: number; children: React.ReactNode}> = ({
  visible,
  opacity,
  children,
}) => {
  if (!visible) {
    return null;
  }

  return (
    <div className="scene-layer" style={{opacity}}>
      {children}
    </div>
  );
};

const Timer: React.FC<{time: number}> = ({time}) => {
  const minutes = Math.floor(time / 60);
  const seconds = Math.floor(time % 60)
    .toString()
    .padStart(2, '0');
  return <div className="timer">{minutes}:{seconds} / 5:00</div>;
};

const Caption: React.FC<{text: string}> = ({text}) => (
  <div className="caption-bar">
    <div className="caption-label">Narration</div>
    <div className="caption-text">{text}</div>
  </div>
);

const ProblemScene: React.FC<{localTime: number}> = ({localTime}) => {
  const calls = [
    {at: 3, text: 'agent.call(execute_refund, amount=12500)', state: 'waiting'},
    {at: 8, text: 'agent.call(skip_2fa_for_vip, customer=C-VIP-007)', state: 'danger'},
    {at: 13, text: 'agent.call(request_manager_approval, reason="later")', state: 'danger'},
    {at: 18, text: 'agent.call(write_audit_log, after_the_fact=true)', state: 'warning'},
  ];
  const visibleCalls = calls.filter((call) => localTime >= call.at);

  return (
    <div className="hero-layout">
      <div className="hero-copy">
        <div className="eyebrow">0:00-0:30 / Problem</div>
        <h1>
          Agents moved from chat
          <span>to action.</span>
        </h1>
        <p>
          That is powerful until an autonomous workflow touches regulated steps: approvals, 2FA,
          refunds, audit evidence, and customer money.
        </p>
      </div>
      <div className="terminal-card">
        <div className="terminal-head">
          <span>RefundAgent runtime</span>
          <span className="status-pill amber">unguarded</span>
        </div>
        <div className="terminal-body">
          {visibleCalls.map((call, index) => (
            <div className={`terminal-line ${call.state}`} key={call.text}>
              <span className="prompt">{String(index + 1).padStart(2, '0')}</span>
              <span>{call.text}</span>
            </div>
          ))}
          {localTime > 22 ? (
            <div className="policy-gap">
              <span className="block-dot" />
              No runtime policy boundary between reasoning and action
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};

const SolutionScene: React.FC<{localTime: number}> = ({localTime}) => {
  const checks = [
    {at: 4, label: '1. Is the tool in BPMN?'},
    {at: 10, label: '2. Is it legal from the current node?'},
    {at: 16, label: '3. Are required tasks complete?'},
    {at: 22, label: '4. Should the LLM judge handle gray-zone intent?'},
  ];

  return (
    <div className="solution-layout">
      <div className="section-copy compact">
        <div className="eyebrow">0:30-1:15 / Solution</div>
        <h2>Turn BPMN into runtime policy.</h2>
        <p>
          Compliance keeps drawing the process in BPMN. ProcessGuard makes that diagram executable:
          every proposed tool call becomes an allow, block, warn, or judged decision.
        </p>
      </div>
      <div className="policy-board">
        <div className="policy-column">
          <div className="policy-title">refund_flow.bpmn</div>
          <MiniBpmn localTime={localTime} />
        </div>
        <div className="policy-column policy-runtime">
          <div className="policy-title">ProcessGuard.check_tool_call()</div>
          {checks.map((check) => (
            <div className={`check-row ${localTime >= check.at ? 'active' : ''}`} key={check.label}>
              <span className="check-light" />
              {check.label}
            </div>
          ))}
          <div className="decision-split">
            <div className="decision-box allow">ALLOW - API call runs</div>
            <div className="decision-box block">BLOCK - agent replans</div>
          </div>
        </div>
      </div>
    </div>
  );
};

const DashboardScene: React.FC<{
  heading: string;
  subheading: string;
  mode: DemoMode;
  localTime: number;
}> = ({heading, subheading, mode, localTime}) => {
  const rows = rowsFor(mode).filter((row) => localTime >= row.at).reverse();
  const stats = rows.reduce(
    (acc, row) => {
      acc[row.decision] += 1;
      return acc;
    },
    {ALLOW: 0, BLOCK: 0, WARN: 0} as Record<Decision, number>
  );
  const total = rows.length;

  return (
    <div className="demo-layout">
      <div className="demo-header">
        <div>
          <div className="eyebrow">{heading}</div>
          <h2>{subheading}</h2>
        </div>
        <div className="live-chip">
          <span className="live-dot" />
          running at http://localhost:8765
        </div>
      </div>
      <div className="dashboard-shell">
        <div className="dashboard-nav">
          <div className="dashboard-brand">
            <div className="mini-brand" />
            <span>ProcessGuard</span>
          </div>
          <div className="dashboard-pills">
            <span className="status-pill violet">judge: Demo judge - offline deterministic</span>
            <span className="status-pill green">live</span>
          </div>
        </div>

        <div className="stats-strip">
          <Stat label="Total decisions" value={total} kind="cyan" />
          <Stat label="Allowed" value={stats.ALLOW} kind="green" />
          <Stat label="Blocked" value={stats.BLOCK} kind="rose" />
          <Stat label="Warnings" value={stats.WARN} kind="amber" />
        </div>

        <div className="control-strip">
          <span className="small-label">Scenario</span>
          <div className="select-box">{scenarioLabel(mode)}</div>
          <div className="run-button">Run scenario</div>
          <div className="ghost-button">Reset</div>
          {localTime < 7 ? <Cursor localTime={localTime} /> : null}
        </div>

        <div className="dashboard-grid">
          <div className="panel panel-large">
            <div className="panel-head">
              <span>BPMN process - live agent position</span>
              <span>refund_flow.bpmn</span>
            </div>
            <BpmnFlow mode={mode} localTime={localTime} />
          </div>
          <div className="panel panel-side">
            <div className="timeline-block">
              <div className="panel-head flat">
                <span>Decision timeline</span>
                <span>per agent</span>
              </div>
              <Timeline rows={rows.slice().reverse()} />
            </div>
            <div className="audit-block">
              <div className="panel-head flat">
                <span>Audit stream - SSE</span>
                <span>no polling</span>
              </div>
              <AuditTable rows={rows} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const Stat: React.FC<{label: string; value: number; kind: string}> = ({label, value, kind}) => (
  <div className={`stat ${kind}`}>
    <div className="stat-value">{value}</div>
    <div className="stat-label">{label}</div>
  </div>
);

const Cursor: React.FC<{localTime: number}> = ({localTime}) => {
  const x = interpolate(localTime, [0, 3.5, 6], [1090, 1226, 1240], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const y = interpolate(localTime, [0, 3.5, 6], [286, 286, 286], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return <div className="cursor" style={{left: x, top: y}} />;
};

const scenarioLabel = (mode: DemoMode) => {
  if (mode === 'compliant') {
    return 'compliant - $12,500 full flow';
  }
  if (mode === 'violation') {
    return 'skip_2fa_for_vip - $9,500';
  }
  return 'gray_zone - LLM judge decides - $4,800';
};

const rowsFor = (mode: DemoMode): AuditRow[] => {
  if (mode === 'compliant') {
    return [
      {at: 9, tool: 'verify_2fa', decision: 'ALLOW', corrective: 'Current node advanced to verify_2fa.'},
      {at: 19, tool: 'fraud_check', decision: 'ALLOW', corrective: 'Amount > $10K branch selected.'},
      {at: 29, tool: 'request_manager_approval', decision: 'ALLOW', corrective: 'Manager approval recorded.'},
      {at: 39, tool: 'execute_refund', decision: 'ALLOW', corrective: 'All gates cleared.'},
      {at: 49, tool: 'write_audit_log', decision: 'ALLOW', corrective: 'Mandatory audit trail written.'},
    ];
  }

  if (mode === 'violation') {
    return [
      {
        at: 10,
        tool: null,
        decision: 'BLOCK',
        violation: 'intent_drift',
        corrective: "LLM judge ruled BLOCK: VIP shortcut language violates the spirit of the BPMN policy.",
        judge: {
          provider: 'demo',
          verdict: 'BLOCK',
          confidence: 0.91,
          rationale: "Reasoning contains bypass language: 'skip 2FA' and 'VIP'.",
          correction: 'verify_2fa({})',
        },
      },
      {
        at: 22,
        tool: 'request_manager_approval',
        decision: 'BLOCK',
        violation: 'wrong_order',
        corrective: "Tool 'request_manager_approval' cannot run now. Legal next steps: ['verify_2fa'].",
        judge: {
          provider: 'demo',
          verdict: 'BLOCK',
          confidence: 0.78,
          rationale: "request_manager_approval is not in allowed_next=['verify_2fa'].",
          correction: 'verify_2fa({})',
        },
      },
    ];
  }

  return [
    {
      at: 7,
      tool: null,
      decision: 'BLOCK',
      violation: 'intent_drift',
      corrective: 'LLM judge ruled BLOCK: emergency override language violates policy intent.',
      judge: {
        provider: 'demo',
        verdict: 'BLOCK',
        confidence: 0.91,
        rationale: "Agent reasoning contains policy-bypass language: 'emergency override' and 'just this once'.",
        correction: 'verify_2fa({})',
      },
    },
    {at: 16, tool: 'verify_2fa', decision: 'ALLOW', corrective: 'Agent replans to the safe next BPMN task.'},
    {at: 26, tool: 'execute_refund', decision: 'ALLOW', corrective: 'Amount is <= $5K after verification.'},
    {at: 35, tool: 'write_audit_log', decision: 'ALLOW', corrective: 'Decision and correction path retained for review.'},
  ];
};

const AuditTable: React.FC<{rows: AuditRow[]}> = ({rows}) => {
  if (rows.length === 0) {
    return <div className="empty-log">Scenario armed. Waiting for agent tool calls...</div>;
  }

  return (
    <div className="audit-table">
      {rows.map((row, index) => (
        <div className="audit-row" key={`${row.at}-${row.tool ?? 'reasoning'}`}>
          <div className="audit-time">+{row.at.toString().padStart(2, '0')}s</div>
          <div className="audit-tool">{row.tool ?? '(reasoning)'}</div>
          <div className={`decision-pill ${row.decision.toLowerCase()}`}>{row.decision}</div>
          <div className="audit-detail">
            {row.violation ? <div className="violation-label">{row.violation}</div> : null}
            <div>{row.corrective}</div>
            {row.judge ? <JudgeBlock judge={row.judge} /> : null}
          </div>
        </div>
      ))}
    </div>
  );
};

const JudgeBlock: React.FC<{judge: NonNullable<AuditRow['judge']>}> = ({judge}) => (
  <div className="judge-block">
    <div className="judge-head">
      LLM judge - {judge.provider} - {judge.verdict}
      <span>{Math.round(judge.confidence * 100)}% confidence</span>
    </div>
    <div className="judge-rationale">{judge.rationale}</div>
    {judge.correction ? <div className="judge-correction">suggested: {judge.correction}</div> : null}
  </div>
);

const Timeline: React.FC<{rows: AuditRow[]}> = ({rows}) => (
  <div className="timeline">
    <div className="timeline-axis" />
    {rows.map((row) => (
      <div
        className={`timeline-item ${row.decision.toLowerCase()}`}
        key={`${row.at}-${row.tool ?? 'reasoning'}`}
        style={{left: `${Math.min(90, 8 + row.at * 1.55)}%`}}
      >
        {row.tool ?? 'reasoning'}
      </div>
    ))}
  </div>
);

const BpmnFlow: React.FC<{mode: DemoMode; localTime: number}> = ({mode, localTime}) => {
  const status = statusFor(mode, localTime);

  return (
    <svg className="bpmn-svg" viewBox="0 0 1240 430" role="img" aria-label="Refund BPMN flow">
      <defs>
        <filter id="nodeGlow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="8" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <BpmnPath d="M86 216 L150 216" />
      <BpmnPath d="M270 216 L330 216" />
      <BpmnPath d="M390 216 L620 216" label="5K-10K" />
      <BpmnPath d="M360 186 L360 96 L458 96" label="> 10K" />
      <BpmnPath d="M360 246 L360 350 L818 350 L818 246" label="<= 5K" />
      <BpmnPath d="M578 96 L688 96 L688 184" />
      <BpmnPath d="M762 216 L790 216" />
      <BpmnPath d="M850 216 L902 216" />
      <BpmnPath d="M1022 216 L1078 216" />
      <BpmnPath d="M1198 216 L1214 216" />

      <CircleNode x={54} y={216} label="receive" status={status.start} />
      <TaskNode x={150} y={184} width={120} label="verify_2fa" status={status.verify_2fa} />
      <GatewayNode x={360} y={216} label="amount?" status={status.amount} />
      <TaskNode x={458} y={64} width={120} label="fraud_check" status={status.fraud_check} />
      <TaskNode x={620} y={184} width={142} label="request_manager_approval" status={status.request_manager_approval} />
      <GatewayNode x={820} y={216} label="join" status={status.join} />
      <TaskNode x={902} y={184} width={120} label="execute_refund" status={status.execute_refund} />
      <TaskNode x={1078} y={184} width={120} label="write_audit_log" status={status.write_audit_log} />
      <CircleNode x={1214} y={216} label="done" status={status.end} end />
    </svg>
  );
};

const statusFor = (mode: DemoMode, localTime: number): Record<NodeKey, NodeStatus> => {
  const idle: Record<NodeKey, NodeStatus> = {
    start: 'completed',
    verify_2fa: 'idle',
    amount: 'idle',
    fraud_check: 'idle',
    request_manager_approval: 'idle',
    join: 'idle',
    execute_refund: 'idle',
    write_audit_log: 'idle',
    end: 'idle',
  };

  if (mode === 'compliant') {
    const sequence: Array<{at: number; key: NodeKey}> = [
      {at: 9, key: 'verify_2fa'},
      {at: 19, key: 'fraud_check'},
      {at: 29, key: 'request_manager_approval'},
      {at: 39, key: 'execute_refund'},
      {at: 49, key: 'write_audit_log'},
    ];
    for (const step of sequence) {
      if (localTime >= step.at) {
        idle[step.key] = 'completed';
      }
    }
    if (localTime >= 9) idle.amount = 'completed';
    if (localTime >= 29) idle.join = 'completed';
    const current = sequence.find((step) => localTime < step.at)?.key ?? 'end';
    if (current !== 'end') {
      idle[current] = 'current';
    } else {
      idle.end = 'current';
    }
    return idle;
  }

  if (mode === 'violation') {
    idle.verify_2fa = localTime < 22 ? 'current' : 'idle';
    if (localTime >= 10) {
      idle.verify_2fa = 'warned';
    }
    if (localTime >= 22) {
      idle.request_manager_approval = 'blocked';
    }
    return idle;
  }

  if (localTime < 7) {
    idle.verify_2fa = 'current';
  } else if (localTime < 16) {
    idle.verify_2fa = 'warned';
  } else if (localTime < 26) {
    idle.verify_2fa = 'completed';
    idle.amount = 'completed';
    idle.execute_refund = 'current';
    idle.join = 'completed';
  } else if (localTime < 35) {
    idle.verify_2fa = 'completed';
    idle.amount = 'completed';
    idle.join = 'completed';
    idle.execute_refund = 'completed';
    idle.write_audit_log = 'current';
  } else {
    idle.verify_2fa = 'completed';
    idle.amount = 'completed';
    idle.join = 'completed';
    idle.execute_refund = 'completed';
    idle.write_audit_log = 'completed';
    idle.end = 'current';
  }
  return idle;
};

const BpmnPath: React.FC<{d: string; label?: string}> = ({d, label}) => (
  <g>
    <path className="bpmn-path" d={d} />
    {label ? <text className="bpmn-label" x={labelX(d)} y={labelY(d)}>{label}</text> : null}
  </g>
);

const labelX = (path: string) => {
  if (path.includes('350')) return 560;
  if (path.includes('96')) return 394;
  return 488;
};

const labelY = (path: string) => {
  if (path.includes('350')) return 332;
  if (path.includes('96')) return 132;
  return 198;
};

const TaskNode: React.FC<{x: number; y: number; width: number; label: string; status: NodeStatus}> = ({
  x,
  y,
  width,
  label,
  status,
}) => (
  <g className={`bpmn-node ${status}`} filter={status === 'current' || status === 'blocked' ? 'url(#nodeGlow)' : undefined}>
    <rect x={x} y={y} width={width} height="64" rx="8" />
    <SplitText label={label} x={x + width / 2} y={y + 30} />
  </g>
);

const GatewayNode: React.FC<{x: number; y: number; label: string; status: NodeStatus}> = ({x, y, label, status}) => (
  <g className={`bpmn-node gateway ${status}`}>
    <path d={`M${x} ${y - 34} L${x + 34} ${y} L${x} ${y + 34} L${x - 34} ${y} Z`} />
    <text x={x} y={y + 55} textAnchor="middle">{label}</text>
  </g>
);

const CircleNode: React.FC<{x: number; y: number; label: string; status: NodeStatus; end?: boolean}> = ({
  x,
  y,
  label,
  status,
  end,
}) => (
  <g className={`bpmn-node circle ${status}`}>
    <circle cx={x} cy={y} r={end ? 24 : 20} />
    <text x={x} y={y + 46} textAnchor="middle">{label}</text>
  </g>
);

const SplitText: React.FC<{label: string; x: number; y: number}> = ({label, x, y}) => {
  const parts = label.split('_');
  const lines = parts.length > 2 ? [parts.slice(0, 2).join('_'), parts.slice(2).join('_')] : [label];
  return (
    <text x={x} y={y} textAnchor="middle">
      {lines.map((line, index) => (
        <tspan x={x} dy={index === 0 ? 0 : 17} key={line}>
          {line}
        </tspan>
      ))}
    </text>
  );
};

const MiniBpmn: React.FC<{localTime: number}> = ({localTime}) => {
  const fill = interpolate(localTime, [4, 22], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div className="mini-bpmn">
      {['request', '2FA', 'amount', 'approval', 'refund', 'audit'].map((node, index) => (
        <React.Fragment key={node}>
          <div className={`mini-node ${fill > index / 6 ? 'lit' : ''}`}>{node}</div>
          {index < 5 ? <div className="mini-edge" /> : null}
        </React.Fragment>
      ))}
    </div>
  );
};

const ArchitectureScene: React.FC<{localTime: number}> = ({localTime}) => {
  const nodes = [
    {label: 'UiPath Automation Cloud', sub: 'Maestro workflow + agent entrypoint', x: 120, y: 210},
    {label: 'Agent tool call', sub: 'verify_2fa, approval, refund, audit', x: 520, y: 210},
    {label: 'ProcessGuard middleware', sub: 'pre-call runtime boundary', x: 920, y: 210},
    {label: 'BPMN engine', sub: 'legal next task + preconditions', x: 720, y: 520},
    {label: 'LLM judge', sub: 'gray-zone verdict + correction', x: 1120, y: 520},
    {label: 'Audit dashboard', sub: 'SSE stream + logs for review', x: 1320, y: 210},
  ];

  return (
    <div className="architecture-layout">
      <div className="section-copy compact">
        <div className="eyebrow">4:00-4:40 / Architecture</div>
        <h2>One runtime boundary for agent action.</h2>
      </div>
      <svg className="architecture-map" viewBox="0 0 1680 760">
        <ArchLine from={[350, 290]} to={[520, 290]} progress={localTime / 8} />
        <ArchLine from={[750, 290]} to={[920, 290]} progress={(localTime - 5) / 8} />
        <ArchLine from={[1090, 360]} to={[790, 520]} progress={(localTime - 10) / 8} />
        <ArchLine from={[1150, 360]} to={[1190, 520]} progress={(localTime - 15) / 8} />
        <ArchLine from={[1160, 290]} to={[1320, 290]} progress={(localTime - 20) / 8} />
        {nodes.map((node, index) => (
          <ArchNode key={node.label} {...node} active={localTime > index * 5} />
        ))}
      </svg>
    </div>
  );
};

const ArchLine: React.FC<{from: [number, number]; to: [number, number]; progress: number}> = ({from, to, progress}) => {
  const pct = smooth(progress);
  const x = from[0] + (to[0] - from[0]) * pct;
  const y = from[1] + (to[1] - from[1]) * pct;
  return (
    <g>
      <line className="arch-line" x1={from[0]} y1={from[1]} x2={to[0]} y2={to[1]} />
      <circle className="arch-pulse" cx={x} cy={y} r="8" />
    </g>
  );
};

const ArchNode: React.FC<{label: string; sub: string; x: number; y: number; active: boolean}> = ({label, sub, x, y, active}) => (
  <g className={`arch-node ${active ? 'active' : ''}`}>
    <rect x={x} y={y} width="260" height="120" rx="8" />
    <text x={x + 24} y={y + 46}>{label}</text>
    <text x={x + 24} y={y + 78} className="arch-sub">{sub}</text>
  </g>
);

const HumanScene: React.FC<{localTime: number}> = ({localTime}) => {
  const roles = [
    {label: 'Define BPMN', detail: 'Compliance owns the process model'},
    {label: 'Approve workflows', detail: 'Humans stay in high-risk loops'},
    {label: 'Review audit logs', detail: 'Every decision is timestamped'},
    {label: 'Handle escalations', detail: 'Blocked agents route to people'},
  ];

  return (
    <div className="human-layout">
      <div className="section-copy centered">
        <div className="eyebrow">4:40-5:00 / Human role</div>
        <h2>Humans define the boundary. Agents run inside it.</h2>
      </div>
      <div className="role-grid">
        {roles.map((role, index) => (
          <div className={`role-card ${localTime > index * 3 ? 'active' : ''}`} key={role.label}>
            <div className="role-index">0{index + 1}</div>
            <h3>{role.label}</h3>
            <p>{role.detail}</p>
          </div>
        ))}
      </div>
      <div className="closing-line">ProcessGuard: BPMN-enforced action control for regulated AI agents.</div>
    </div>
  );
};
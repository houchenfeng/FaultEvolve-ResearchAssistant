import { useEffect, useMemo, useState } from 'react';

import type { DemoEvent, DemoStep, Transfer } from './demo-script';
import { DEMO_TRANSFERS, describeStep } from './demo-script';

export type NodePhase = 'proposed' | 'evaluating' | 'done';

const STEP_MS: Record<DemoStep['kind'], number> = {
  propose: 1500,
  evaluate: 1500,
  result: 720,
  finish: 0,
};

export interface PlayerView {
  index: number;
  step: DemoStep | null;
  phases: Map<string, NodePhase>;
  lastResultId: string | null;
  best: number | null;
  bestId: string | null;
  bestHistory: number[];
  events: DemoEvent[];
  round: number;
  shownTransfers: Transfer[];
  flyingTransfers: Transfer[];
  finished: boolean;
}

export function useDemoPlayer(steps: DemoStep[], autoplay: boolean) {
  const [index, setIndex] = useState(-1);
  const [playing, setPlaying] = useState(autoplay);
  const [speed, setSpeed] = useState(1);

  useEffect(() => {
    if (autoplay) setPlaying(true);
  }, [autoplay]);

  useEffect(() => {
    if (!playing) return;
    if (index >= steps.length - 1) {
      setPlaying(false);
      return;
    }
    const wait = index < 0 ? 200 : STEP_MS[steps[index].kind];
    const timer = window.setTimeout(() => setIndex((i) => i + 1), wait / speed);
    return () => window.clearTimeout(timer);
  }, [playing, index, speed, steps]);

  const view = useMemo<PlayerView>(() => {
    const phases = new Map<string, NodePhase>();
    const events: DemoEvent[] = [];
    const bestHistory: number[] = [];
    const shown = new Set<Transfer>();
    let lastResultId: string | null = null;
    let best: number | null = null;
    let bestId: string | null = null;
    let round = 0;
    for (let i = 0; i <= index && i < steps.length; i += 1) {
      const s = steps[i];
      const ev = describeStep(s, i);
      if (ev) events.push(ev);
      if (s.kind === 'propose') {
        round = s.round;
        s.nodeIds.forEach((id) => phases.set(id, 'proposed'));
        s.injects.forEach((t) => shown.add(t));
      } else if (s.kind === 'evaluate') {
        s.nodeIds.forEach((id) => phases.set(id, 'evaluating'));
      } else if (s.kind === 'result') {
        phases.set(s.nodeId, 'done');
        lastResultId = s.nodeId;
        if (s.isNewBest) bestId = s.nodeId;
        best = s.bestScore;
        bestHistory.push(s.bestScore);
      }
    }
    const step = index >= 0 ? steps[index] : null;
    return {
      index,
      step,
      phases,
      lastResultId,
      best,
      bestId,
      bestHistory,
      events: events.reverse(),
      round,
      shownTransfers: DEMO_TRANSFERS.filter((t) => shown.has(t)),
      flyingTransfers: step?.kind === 'propose' ? step.injects : [],
      finished: step?.kind === 'finish',
    };
  }, [index, steps]);

  return {
    view,
    playing,
    speed,
    setSpeed,
    toggle: () => {
      if (index >= steps.length - 1) {
        setIndex(-1);
        setPlaying(true);
      } else setPlaying((p) => !p);
    },
    restart: () => {
      setIndex(-1);
      setPlaying(true);
    },
    skipToEnd: () => {
      setIndex(steps.length - 1);
      setPlaying(false);
    },
  };
}

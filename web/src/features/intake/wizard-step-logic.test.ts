import { describe, expect, it } from 'vitest';

import type { ArtifactCard } from '@/features/intake/task-artifacts-logic';
import {
  canAdvanceFromWizardStep,
  intensityStepReady,
  taskStepReady,
  targetStepReady,
} from '@/features/intake/wizard-step-logic';

const PASS_CARDS: ArtifactCard[] = [
  { id: 'dataset', title: '', state: 'pass', reason: null, facts: [] },
  { id: 'evaluator', title: '', state: 'pass', reason: null, facts: [] },
  { id: 'init', title: '', state: 'pass', reason: null, facts: [] },
];

const baseCtx = {
  taskId: 'hdd_mvp',
  cards: PASS_CARDS,
  cardsPending: false,
  serversPending: false,
  serversErrored: false,
  serverProfileId: 'p1',
  presetsPending: false,
  presetsErrored: false,
  presetCount: 3,
};

describe('wizard step readiness', () => {
  it('task step waits for three pass cards', () => {
    expect(taskStepReady(null, [], false)).toBe(false);
    expect(taskStepReady('hdd_mvp', PASS_CARDS, true)).toBe(false);
    expect(
      taskStepReady('hdd_mvp', [{ ...PASS_CARDS[0], state: 'checking' }, ...PASS_CARDS.slice(1)], false),
    ).toBe(false);
    expect(taskStepReady('hdd_mvp', PASS_CARDS, false)).toBe(true);
  });

  it('target step waits for server list and selection', () => {
    expect(targetStepReady(true, false, 'p1')).toBe(false);
    expect(targetStepReady(false, true, 'p1')).toBe(false);
    expect(targetStepReady(false, false, null)).toBe(false);
    expect(targetStepReady(false, false, 'p1')).toBe(true);
  });

  it('intensity step waits for presets', () => {
    expect(intensityStepReady(true, false, 3)).toBe(false);
    expect(intensityStepReady(false, false, 0)).toBe(false);
    expect(intensityStepReady(false, false, 3)).toBe(true);
  });

  it('canAdvanceFromWizardStep maps step index', () => {
    expect(canAdvanceFromWizardStep(0, { ...baseCtx, taskId: null })).toBe(false);
    expect(canAdvanceFromWizardStep(0, baseCtx)).toBe(true);
    expect(canAdvanceFromWizardStep(1, { ...baseCtx, serverProfileId: null })).toBe(false);
    expect(canAdvanceFromWizardStep(3, { ...baseCtx, presetsPending: true })).toBe(false);
    expect(canAdvanceFromWizardStep(5, baseCtx)).toBe(false);
  });
});
